"""
LLM gateway — the single call site for every model invocation in P1 (SPN-02).

- One entry point: LLMGateway.generate(...)
- Provider swap by config: LLM_PROVIDER=anthropic|ollama|bedrock (.env)
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
from anthropic import Anthropic, AnthropicBedrock, APIStatusError, RateLimitError
from dotenv import load_dotenv
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

load_dotenv()

logger = logging.getLogger("p1.llm.gateway")

# The one place this programme's actual production model id lives --
# CHN-27's eval harness tags every committed run with this same
# constant by default (see scripts/run_eval.py), so "which model
# produced these numbers" is never a second, independently maintained
# guess at what this parameter's own default says.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"


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
        anthropic_model: str = DEFAULT_ANTHROPIC_MODEL,
        ollama_base_url: str | None = None,
        ollama_model: str | None = None,
        bedrock_aws_access_key: str | None = None,
        bedrock_aws_secret_key: str | None = None,
        bedrock_aws_region: str | None = None,
        bedrock_model_id: str | None = None,
        cache_dir: str | Path = "data/cache/llm",
        call_log_path: str | Path = "data/logs/llm_calls.jsonl",
        max_attempts: int = 4,
    ) -> None:
        self.provider = provider or os.environ.get("LLM_PROVIDER", "anthropic")
        self.anthropic_api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.anthropic_model = anthropic_model
        self.ollama_base_url = ollama_base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_model = ollama_model or os.environ.get("OLLAMA_MODEL", "llama3:8b")
        # AWS Bedrock (SPN-02's third provider): reaches the same Claude
        # models through AWS-hosted infrastructure instead of Anthropic's
        # own API. Authenticates via an explicit access key/secret/region,
        # never AWS's ambient default credential chain (env vars picked up
        # implicitly, ~/.aws/credentials, an EC2/ECS instance role, etc.)
        # -- matching every other adapter in this repo: explicit config in,
        # no implicit environment magic.
        self.bedrock_aws_access_key = bedrock_aws_access_key or os.environ.get("AWS_ACCESS_KEY_ID")
        self.bedrock_aws_secret_key = bedrock_aws_secret_key or os.environ.get("AWS_SECRET_ACCESS_KEY")
        self.bedrock_aws_region = bedrock_aws_region or os.environ.get("AWS_REGION")
        self.bedrock_model_id = bedrock_model_id or os.environ.get("BEDROCK_MODEL_ID")
        self.max_attempts = max_attempts

        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.call_log_path = Path(call_log_path)
        self.call_log_path.parent.mkdir(parents=True, exist_ok=True)

        self._anthropic_client: Anthropic | None = None
        self._bedrock_client: AnthropicBedrock | None = None

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
            # Both cloud providers (direct Anthropic API, or the same
            # models via AWS Bedrock) degrade to the local Ollama
            # fallback on exhaustion; a request already targeting Ollama,
            # or an unrecognized provider, has nowhere further to fall
            # back to and simply re-raises.
            if self.provider not in ("anthropic", "bedrock"):
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
        if provider == "bedrock":
            return self._call_bedrock(prompt, system, max_tokens, temperature, tools, tool_choice)
        if provider == "ollama":
            return self._call_ollama(prompt, system, max_tokens, temperature)
        raise LLMGatewayError(f"Unknown LLM provider: {provider}")

    def _call_anthropic(self, prompt, system, max_tokens, temperature, tools, tool_choice):
        """Direct Anthropic API path. See _call_messages_api for the
        shared request/retry/response-parsing logic (including the
        temperature SDK-compatibility note from CHN-31, which applies
        here too) -- this method's only job is constructing the right
        client and model identifier."""
        if self._anthropic_client is None:
            if not self.anthropic_api_key:
                raise LLMGatewayError("ANTHROPIC_API_KEY is not set")
            self._anthropic_client = Anthropic(api_key=self.anthropic_api_key)

        return self._call_messages_api(
            self._anthropic_client, self.anthropic_model, "Anthropic",
            prompt, system, max_tokens, tools, tool_choice,
        )

    def _call_bedrock(self, prompt, system, max_tokens, temperature, tools, tool_choice):
        """AWS Bedrock path (SPN-02's third provider): the same Claude
        model, reached via AWS-hosted infrastructure instead of
        Anthropic's own API. Authenticates via an explicit AWS access
        key/secret/region (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
        AWS_REGION) -- never AWS's ambient default credential chain --
        matching this repo's existing pattern of explicit config in, no
        implicit environment magic. The model identifier is an AWS
        inference-profile ARN (BEDROCK_MODEL_ID), not the plain
        Anthropic model name _call_anthropic uses.

        See _call_messages_api for the shared request/retry/parsing
        logic -- verified identical in shape to the direct Anthropic
        path via inspect.signature in
        tests/unit/test_llm_gateway_bedrock_call_shape.py, since
        AnthropicBedrock exposes the exact same
        anthropic.resources.messages.Messages class as Anthropic (a
        thin auth-layer swap in the SDK, not a different API shape --
        confirmed by inspection, not assumed)."""
        if self._bedrock_client is None:
            missing = [
                name
                for name, value in (
                    ("AWS_ACCESS_KEY_ID", self.bedrock_aws_access_key),
                    ("AWS_SECRET_ACCESS_KEY", self.bedrock_aws_secret_key),
                    ("AWS_REGION", self.bedrock_aws_region),
                    ("BEDROCK_MODEL_ID", self.bedrock_model_id),
                )
                if not value
            ]
            if missing:
                raise LLMGatewayError(
                    f"Bedrock provider is missing required config: {', '.join(missing)}"
                )
            self._bedrock_client = AnthropicBedrock(
                aws_access_key=self.bedrock_aws_access_key,
                aws_secret_key=self.bedrock_aws_secret_key,
                aws_region=self.bedrock_aws_region,
            )

        return self._call_messages_api(
            self._bedrock_client, self.bedrock_model_id, "Bedrock",
            prompt, system, max_tokens, tools, tool_choice,
        )

    def _call_messages_api(self, client, model, provider_label, prompt, system, max_tokens, tools, tool_choice):
        """The Messages-API request-building, retry, and
        response-parsing logic shared by _call_anthropic and
        _call_bedrock -- both talk to the exact same
        anthropic.resources.messages.Messages class (AnthropicBedrock is
        a thin auth-layer swap over the same SDK, not a different
        client library), so this only needs to exist once.

        `temperature` is deliberately not a parameter here (and never
        forwarded to Messages.create()) -- CHN-31's clean-clone
        verification found that the currently locked anthropic SDK
        (1.5.0 -- see pyproject.toml/uv.lock) has removed
        temperature/top_p/top_k from Messages.create() entirely
        (confirmed by reading that SDK's own installed type stubs, not
        by trial and error): passing it raised a hard TypeError on every
        real, uncached call, in both a fresh clone and the existing repo
        -- see DECISION_LOG.md's CHN-31 entry. There is no replacement
        sampling-control parameter in this SDK version, so explicit
        temperature=0.0 determinism is no longer enforceable on either
        the Anthropic or the Bedrock path (both go through this same
        Messages class); Ollama's own call still honours it (see
        _call_ollama) since Ollama's API is unaffected.
        tests/unit/test_llm_gateway_anthropic_call_shape.py and
        tests/unit/test_llm_gateway_bedrock_call_shape.py both guard
        against this ever regressing silently again -- each asserts
        every kwarg this method builds is one the actually-installed
        SDK's own Messages.create signature accepts, without ever
        making a live call."""
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
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
            resp = retrying(lambda: client.messages.create(**kwargs))
        except RateLimitError as exc:
            raise LLMGatewayError(f"{provider_label} rate-limited after {self.max_attempts} attempts") from exc
        except APIStatusError as exc:
            raise LLMGatewayError(f"{provider_label} API error: {exc}") from exc

        tool_use_blocks = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if tool_use_blocks:
            text = json.dumps(tool_use_blocks[0].input)
        else:
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
        if self.provider == "anthropic":
            model = self.anthropic_model
        elif self.provider == "bedrock":
            model = self.bedrock_model_id
        else:
            model = self.ollama_model
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
