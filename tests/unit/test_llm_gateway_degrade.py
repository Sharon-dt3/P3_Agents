"""
Regression guard for generate()'s degrade-to-fallback path -- this
logic previously had no test at all covering it directly (every other
gateway test monkeypatches _call_provider to simply succeed). Adding
Bedrock as a second cloud provider touched this exact branch (it used
to be `if self.provider != "anthropic": raise`, now
`if self.provider not in ("anthropic", "bedrock"): raise`), so it now
has real, load-bearing conditional logic worth guarding directly:
anthropic and bedrock both degrade to a local Ollama fallback on
exhaustion; ollama itself (nothing further to fall back to) and an
unrecognized provider do not, and simply re-raise.
"""

from __future__ import annotations

import pytest

from p1.llm.gateway import LLMGateway, LLMGatewayError


def _make_gateway(tmp_path, provider, fail_providers):
    def fake_call_provider(self, called_provider, prompt, system, max_tokens, temperature, tools, tool_choice):
        if called_provider in fail_providers:
            raise LLMGatewayError(f"{called_provider} exhausted (simulated)")
        return f"response from {called_provider}", f"{called_provider}-model", 1, 1

    gateway = LLMGateway(
        provider=provider,
        anthropic_api_key="test-key",
        bedrock_aws_access_key="test-access-key",
        bedrock_aws_secret_key="test-secret-key",
        bedrock_aws_region="us-east-2",
        bedrock_model_id="arn:aws:bedrock:us-east-2:000:inference-profile/fake",
        cache_dir=tmp_path / "cache",
        call_log_path=tmp_path / "calls.jsonl",
    )
    gateway._call_provider = fake_call_provider.__get__(gateway, LLMGateway)
    return gateway


def test_anthropic_degrades_to_ollama_on_exhaustion(tmp_path):
    gateway = _make_gateway(tmp_path, "anthropic", fail_providers={"anthropic"})

    response = gateway.generate("hello", skip_cache=True)

    assert response.provider == "ollama"
    assert response.degraded is True


def test_bedrock_degrades_to_ollama_on_exhaustion(tmp_path):
    gateway = _make_gateway(tmp_path, "bedrock", fail_providers={"bedrock"})

    response = gateway.generate("hello", skip_cache=True)

    assert response.provider == "ollama"
    assert response.degraded is True


def test_ollama_itself_has_no_further_fallback(tmp_path):
    gateway = _make_gateway(tmp_path, "ollama", fail_providers={"ollama"})

    with pytest.raises(LLMGatewayError):
        gateway.generate("hello", skip_cache=True)


def test_unrecognized_provider_has_no_fallback(tmp_path):
    gateway = _make_gateway(tmp_path, "made-up-provider", fail_providers={"made-up-provider"})

    with pytest.raises(LLMGatewayError):
        gateway.generate("hello", skip_cache=True)


def test_degrading_logs_the_primary_providers_real_failure_reason(tmp_path, caplog):
    # CHN-26: generate() used to catch `except LLMGatewayError:` with no
    # bound name, discarding the actual reason the primary provider
    # failed. A real run against real Bedrock hit exactly this: the
    # warning said only "Primary provider exhausted; degrading to local
    # Ollama fallback", with no way to tell why Bedrock itself had been
    # rejected -- only Ollama's own, unrelated failure was ever visible.
    gateway = _make_gateway(tmp_path, "bedrock", fail_providers={"bedrock"})

    with caplog.at_level("WARNING"):
        gateway.generate("hello", skip_cache=True)

    assert "bedrock exhausted (simulated)" in caplog.text
