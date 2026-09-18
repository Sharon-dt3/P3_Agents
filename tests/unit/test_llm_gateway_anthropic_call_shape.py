"""
CHN-31: regression guard for the SDK-compatibility break its own
clean-clone verification found -- anthropic==1.5.0 (currently locked in
uv.lock) removed temperature/top_p/top_k from Messages.create()
entirely, and every existing gateway test monkeypatches
LLMGateway._call_provider itself, so nothing had ever actually
exercised _call_anthropic's real call shape against the real,
installed SDK -- the break went unnoticed until a real, uncached call
crashed outright (see DECISION_LOG.md's CHN-31 entry).

This test never makes a live call. It substitutes a fake
_anthropic_client (so no real Anthropic() client or network request is
ever created) and asserts every kwarg _call_anthropic actually builds
is one the REAL, currently-installed anthropic package's own
Messages.create signature accepts -- read via inspect.signature, not
assumed. A future SDK upgrade that drops or renames another parameter
fails this test immediately, at test time, instead of waiting for the
next real demo or production run to discover it.
"""

from __future__ import annotations

import inspect
from typing import ClassVar

import anthropic

from p1.llm.gateway import LLMGateway

# The SDK's own generic escape hatches -- always present on every
# resource method regardless of API version, so they're never a sign
# gateway.py is relying on a parameter the server-side API doesn't
# actually have.
_SDK_ESCAPE_HATCHES = {"extra_headers", "extra_query", "extra_body", "timeout"}


class _FakeUsage:
    input_tokens = 1
    output_tokens = 1


class _FakeResponse:
    content: ClassVar[list] = []
    model = "fake-model"
    usage = _FakeUsage()


class _FakeMessages:
    def __init__(self):
        self.captured_kwargs: dict | None = None

    def create(self, **kwargs):
        self.captured_kwargs = kwargs
        return _FakeResponse()


class _FakeAnthropicClient:
    def __init__(self):
        self.messages = _FakeMessages()


def test_call_anthropic_only_sends_kwargs_the_installed_sdk_actually_accepts(tmp_path):
    gateway = LLMGateway(
        provider="anthropic",
        anthropic_api_key="test-key",
        cache_dir=tmp_path / "cache",
        call_log_path=tmp_path / "calls.jsonl",
    )
    # Pre-set the real attribute _call_anthropic lazily constructs, so
    # it never calls the real anthropic.Anthropic(...) constructor or
    # touches the network at all.
    fake_client = _FakeAnthropicClient()
    gateway._anthropic_client = fake_client

    gateway.generate("hello", skip_cache=True)

    assert fake_client.messages.captured_kwargs is not None, "Messages.create() was never called"

    accepted = set(inspect.signature(anthropic.resources.messages.Messages.create).parameters) - {"self"}
    accepted |= _SDK_ESCAPE_HATCHES

    sent = set(fake_client.messages.captured_kwargs)
    unsupported = sent - accepted
    assert not unsupported, (
        f"_call_anthropic sent kwarg(s) the installed anthropic=={anthropic.__version__} "
        f"SDK's own Messages.create signature does not accept: {sorted(unsupported)}"
    )


def test_temperature_is_never_forwarded_to_the_anthropic_client(tmp_path):
    """Belt-and-suspenders: the specific parameter this row's own
    investigation found broken must never reappear in what's actually
    sent, even if some future refactor re-widens the accepted set for
    an unrelated reason."""
    gateway = LLMGateway(
        provider="anthropic",
        anthropic_api_key="test-key",
        cache_dir=tmp_path / "cache",
        call_log_path=tmp_path / "calls.jsonl",
    )
    fake_client = _FakeAnthropicClient()
    gateway._anthropic_client = fake_client

    gateway.generate("hello", temperature=0.0, skip_cache=True)

    assert "temperature" not in fake_client.messages.captured_kwargs
