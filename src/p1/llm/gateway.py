"""
LLM gateway — the single call site for every model invocation in P1 (SPN-02).

- One entry point: LLMGateway.generate(...)
- Provider swap by config: LLM_PROVIDER=anthropic|ollama (.env)
- On-disk cache keyed by a hash of the full request
- Exponential backoff on rate limits, then an explicit degrade-to-fallback path
- Every call logged: provider, model, tokens, latency, cache hit, degraded
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from anthropic import Anthropic, APIStatusError, RateLimitError
from dotenv import load_dotenv
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

load_dotenv()

logger = logging.getLogger("p1.llm.gateway")


class LLMGatewayError(RuntimeError):
    """Raised when a provider could not satisfy the request."""


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    cache_hit: bool
    degraded: bool = False


class LLMGateway:
    def __init__(
        self,
        provider: str | None = None,
        anthropic_api_key: str | None = None,
        anthropic_model: str = "claude-sonnet-4-20250514",
        ollama_base_url: str | None = None,
        ollama_model: str | None = None,
        cache_dir: str | Path = "data/cache/llm",
        call_log_path: str | Path = "data/logs/llm_calls.jsonl",
        max_attempts: int = 4,
    ) -> None:
        self.provider = provider or os.environ.get("LLM_PROVIDER", "anthropic")
        self.anthropic_api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.anthropic_model = anthropic_model
        self.ollama_base_url = ollama_base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_model = ollama_model or os.environ.get("OLLAMA_MODEL", "llama3:8b")
        self.max_attempts = max_attempts

        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.call_log_path = Path(call_log_path)
        self.call_log_path.parent.mkdir(parents=True, exist_ok=True)

        self._anthropic_client: Anthropic | None = None

    # ---- public entry point ------------------------------------------------

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        tools: list[dict] | None = None,
        tool_choice: dict | None = None,
        skip_cache: bool = False,
    ) -> LLMResponse:
        """The one call site every P1 capability must go through."""
        cache_key = self._cache_key(prompt, system, max_tokens, temperature, tools, tool_choice)

        if not skip_cache:
            cached = self._read_cache(cache_key)
            if cached is not None:
                response = LLMResponse(**cached, cache_hit=True)
                self._log_call(response, cache_key)
                return response

        start = time.monotonic()
        degraded = False
        try:
            text, model, in_tok, out_tok = self._call_provider(
                self.provider, prompt, system, max_tokens, temperature, tools, tool_choice
            )
            provider_used = self.provider
        except LLMGatewayError:
            if self.provider != "anthropic":
                raise
            logger.warning("Primary provider exhausted; degrading to local Ollama fallback")
            degraded = True
            text, model, in_tok, out_tok = self._call_provider(
                "ollama", prompt, system, max_tokens, temperature, tools, tool_choice
            )
            provider_used = "ollama"

        latency_ms = (time.monotonic() - start) * 1000
        response = LLMResponse(
            text=text,
            provider=provider_used,
            model=model,
            prompt_tokens=in_tok,
            completion_tokens=out_tok,
            latency_ms=latency_ms,
            cache_hit=False,
            degraded=degraded,
        )

        if not skip_cache:
            self._write_cache(cache_key, response)
        self._log_call(response, cache_key)
        return response

    # ---- provider dispatch ---------------------------------------------------

    def _call_provider(self, provider, prompt, system, max_tokens, temperature, tools, tool_choice):
        if provider == "anthropic":
            return self._call_anthropic(prompt, system, max_tokens, temperature, tools, tool_choice)
        if provider == "ollama":
            return self._call_ollama(prompt, system, max_tokens, temperature)
        raise LLMGatewayError(f"Unknown LLM provider: {provider}")

    def _call_anthropic(self, prompt, system, max_tokens, temperature, tools, tool_choice):
        if self._anthropic_client is None:
            if not self.anthropic_api_key:
                raise LLMGatewayError("ANTHROPIC_API_KEY is not set")
            self._anthropic_client = Anthropic(api_key=self.anthropic_api_key)

        kwargs: dict[str, Any] = {
            "model": self.anthropic_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        retrying = Retrying(
            retry=retry_if_exception_type(RateLimitError),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            stop=stop_after_attempt(self.max_attempts),
            reraise=True,
        )
        try:
            resp = retrying(lambda: self._anthropic_client.messages.create(**kwargs))
        except RateLimitError as exc:
            raise LLMGatewayError(f"Anthropic rate-limited after {self.max_attempts} attempts") from exc
        except APIStatusError as exc:
            raise LLMGatewayError(f"Anthropic API error: {exc}") from exc

        text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
        return text, resp.model, resp.usage.input_tokens, resp.usage.output_tokens

    def _call_ollama(self, prompt, system, max_tokens, temperature):
        payload = {
            "model": self.ollama_model,
            "prompt": f"{system}\n\n{prompt}" if system else prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            with httpx.Client(base_url=self.ollama_base_url, timeout=60.0) as client:
                resp = client.post("/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMGatewayError(f"Ollama request failed: {exc}") from exc

        text = data.get("response", "")
        in_tok = data.get("prompt_eval_count", 0)
        out_tok = data.get("eval_count", 0)
        return text, self.ollama_model, in_tok, out_tok

    # ---- cache ---------------------------------------------------------------

    def _cache_key(self, prompt, system, max_tokens, temperature, tools, tool_choice) -> str:
        model = self.anthropic_model if self.provider == "anthropic" else self.ollama_model
        payload = json.dumps(
            {
                "provider": self.provider,
                "model": model,
                "prompt": prompt,
                "system": system,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "tools": tools,
                "tool_choice": tool_choice,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _cache_path(self, cache_key: str) -> Path:
        return self.cache_dir / f"{cache_key}.json"

    def _read_cache(self, cache_key: str) -> dict | None:
        path = self._cache_path(cache_key)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        data.pop("cache_hit", None)
        return data

    def _write_cache(self, cache_key: str, response: LLMResponse) -> None:
        data = {
            "text": response.text,
            "provider": response.provider,
            "model": response.model,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "latency_ms": response.latency_ms,
            "degraded": response.degraded,
        }
        self._cache_path(cache_key).write_text(json.dumps(data))

    # ---- call log --------------------------------------------------------

    def _log_call(self, response: LLMResponse, cache_key: str) -> None:
        entry = {
            "timestamp": time.time(),
            "cache_key": cache_key,
            "provider": response.provider,
            "model": response.model,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "latency_ms": round(response.latency_ms, 2),
            "cache_hit": response.cache_hit,
            "degraded": response.degraded,
        }
        with self.call_log_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        logger.info("llm_call %s", entry)
