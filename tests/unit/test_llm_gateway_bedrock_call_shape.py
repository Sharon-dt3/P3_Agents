"""
Bedrock counterpart to test_llm_gateway_anthropic_call_shape.py.

AnthropicBedrock exposes the exact same
anthropic.resources.messages.Messages class as the direct Anthropic
client (confirmed here via inspect.signature, not assumed) -- so this
test guards the same thing the Anthropic version does: that
_call_bedrock (by way of the shared _call_messages_api) never sends a
kwarg the actually-installed SDK's own Messages.create signature
doesn't accept. It never makes a live call or constructs a real
AnthropicBedrock() client -- a fake client/messages resource is
substituted directly, so no AWS credentials, network access, or real
Bedrock account are ever touched under pytest.
"""

from __future__ import annotations

import inspect
from typing import ClassVar

import anthropic

from p1.llm.gateway import LLMGateway, LLMGatewayError

_SDK_ESCAPE_HATCHES = {"extra_headers", "extra_query", "extra_body", "timeout"}

_MODEL_ARN = "arn:aws:bedrock:us-east-2:619042036275:inference-profile/us.anthropic.claude-sonnet-4-20250514-v1:0"


class _FakeUsage:
    input_tokens = 1
    output_tokens = 1


class _FakeResponse:
    content: ClassVar[list] = []
    model = _MODEL_ARN
    usage = _FakeUsage()


class _FakeMessages:
    def __init__(self):
        self.captured_kwargs: dict | None = None

    def create(self, **kwargs):
        self.captured_kwargs = kwargs
        return _FakeResponse()


class _FakeBedrockClient:
    def __init__(self):
        self.messages = _FakeMessages()


def _make_gateway(tmp_path, **overrides):
    kwargs = {
        "provider": "bedrock",
        "bedrock_aws_access_key": "test-access-key",
        "bedrock_aws_secret_key": "test-secret-key",
        "bedrock_aws_region": "us-east-2",
        "bedrock_model_id": _MODEL_ARN,
        "cache_dir": tmp_path / "cache",
        "call_log_path": tmp_path / "calls.jsonl",
    }
    kwargs.update(overrides)
    return LLMGateway(**kwargs)


def test_call_bedrock_only_sends_kwargs_the_installed_sdk_actually_accepts(tmp_path):
    gateway = _make_gateway(tmp_path)
    fake_client = _FakeBedrockClient()
    # Pre-set the real attribute _call_bedrock lazily constructs, so it
    # never calls the real anthropic.AnthropicBedrock(...) constructor
    # (which would otherwise try to resolve AWS auth) or touches the
    # network at all.
    gateway._bedrock_client = fake_client

    gateway.generate("hello", skip_cache=True)

    assert fake_client.messages.captured_kwargs is not None, "Messages.create() was never called"

    accepted = set(inspect.signature(anthropic.resources.messages.Messages.create).parameters) - {"self"}
    accepted |= _SDK_ESCAPE_HATCHES

    sent = set(fake_client.messages.captured_kwargs)
    unsupported = sent - accepted
    assert not unsupported, (
        f"_call_bedrock sent kwarg(s) the installed anthropic=={anthropic.__version__} "
        f"SDK's own Messages.create signature does not accept: {sorted(unsupported)}"
    )


def test_call_bedrock_sends_the_inference_profile_arn_as_the_model(tmp_path):
    gateway = _make_gateway(tmp_path)
    fake_client = _FakeBedrockClient()
    gateway._bedrock_client = fake_client

    gateway.generate("hello", skip_cache=True)

    assert fake_client.messages.captured_kwargs["model"] == _MODEL_ARN


def test_temperature_is_never_forwarded_to_the_bedrock_client(tmp_path):
    gateway = _make_gateway(tmp_path)
    fake_client = _FakeBedrockClient()
    gateway._bedrock_client = fake_client

    gateway.generate("hello", temperature=0.0, skip_cache=True)

    assert "temperature" not in fake_client.messages.captured_kwargs


def test_missing_aws_config_raises_before_touching_the_network(tmp_path, monkeypatch):
    """No AnthropicBedrock() client should ever be constructed -- let
    alone called -- when the required AWS config is incomplete.

    Calls _call_bedrock directly rather than generate(): generate()'s
    own degrade-to-Ollama-on-LLMGatewayError path (see
    test_llm_gateway_degrade.py) would otherwise catch this
    misconfiguration and quietly retry against Ollama instead, masking
    exactly the error this test exists to check -- that's a real
    behavior worth knowing about production-side too (a misconfigured
    Bedrock provider degrades rather than failing loudly), but it's not
    what this test is for.

    Also strips AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY from the real
    environment for the duration of this test: LLMGateway.__init__
    falls back to os.environ.get(...) whenever a constructor arg is
    None, and gateway.py's own module-level load_dotenv() means a real
    .env with real AWS credentials (as this repo's now has, for the
    live Bedrock path) would otherwise silently defeat this test's
    bedrock_aws_access_key=None/bedrock_aws_secret_key=None -- passing
    None would stop meaning "missing" and this test would exercise a
    real AnthropicBedrock() call instead of the config-validation path
    it exists to check. Confirmed this was a real, live failure mode
    (not a hypothetical): it broke exactly this way the moment this
    session's real AWS credentials landed in .env."""
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    gateway = _make_gateway(
        tmp_path, bedrock_aws_access_key=None, bedrock_aws_secret_key=None
    )

    try:
        gateway._call_bedrock("hello", None, 1024, 0.0, None, None)
        raise AssertionError("expected LLMGatewayError")
    except LLMGatewayError as exc:
        assert "AWS_ACCESS_KEY_ID" in str(exc)
        assert "AWS_SECRET_ACCESS_KEY" in str(exc)

    assert gateway._bedrock_client is None
