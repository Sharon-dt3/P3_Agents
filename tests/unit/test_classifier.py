from p1.adapters.teams_reader import TeamsMessage
from p1.detection.classifier import (
    CLASSIFIER_CAPABILITY,
    classify_message,
    is_uncertain,
)
from p1.llm.gateway import LLMResponse
from p1.prompts import PromptRegistry


class FakeGateway:
    """Stand-in for LLMGateway: returns canned tool-call JSON in order,
    and records every prompt it was actually called with -- so tests can
    prove the message body was really interpolated in, not just that
    some hard-coded label came back."""

    def __init__(self, texts):
        self._texts = list(texts)
        self.calls = 0
        self.prompts = []

    def generate(self, prompt, **kwargs):
        self.calls += 1
        self.prompts.append(prompt)
        text = self._texts.pop(0)
        return LLMResponse(
            text=text, provider="anthropic", model="fake-model",
            prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False,
        )


def make_message(**overrides) -> TeamsMessage:
    defaults = {
        "id": "msg-1",
        "channel_id": "19:proj-test@thread.tacv2",
        "author_id": "alice",
        "posted_at": "2025-06-02T09:30:00+05:30",
        "body": "Finished the auth flow, running the tests now.",
    }
    defaults.update(overrides)
    return TeamsMessage(**defaults)


def test_status_shaped_message_is_labelled_update():
    """CHN-09's own acceptance test, first half: a status-shaped message
    is labelled an update."""
    gateway = FakeGateway(['{"label": "update", "confidence": 0.92}'])
    result = classify_message(
        make_message(body="Finished the auth flow, running the tests now."), gateway
    )
    assert result.label == "update"
    assert result.confidence == 0.92


def test_thanks_will_look_reply_is_not_labelled_update():
    """CHN-09's own acceptance test, second half: a 'thanks, will look'
    reply is not labelled an update -- it's real channel activity
    (chatter), just not an update."""
    gateway = FakeGateway(['{"label": "chatter", "confidence": 0.85}'])
    result = classify_message(make_message(body="Thanks, will look."), gateway)
    assert result.label != "update"
    assert result.label == "chatter"


def test_message_body_is_interpolated_into_the_rendered_prompt():
    gateway = FakeGateway(['{"label": "update", "confidence": 0.9}'])
    classify_message(
        make_message(body="Finished the auth flow, running the tests now."), gateway
    )
    assert "Finished the auth flow, running the tests now." in gateway.prompts[0]


def test_invalid_label_retries_then_succeeds():
    """The forced schema means an out-of-enum label is a validation
    failure like any other -- generate_structured's retry-on-invalid
    applies here exactly as it does for any schema."""
    gateway = FakeGateway(
        ['{"label": "definitely_maybe", "confidence": 0.9}', '{"label": "blocker", "confidence": 0.77}']
    )
    result = classify_message(make_message(), gateway)
    assert result.label == "blocker"
    assert gateway.calls == 2


def test_low_confidence_is_flagged_uncertain():
    assert is_uncertain(0.4) is True
    assert is_uncertain(0.59) is True


def test_high_confidence_is_not_uncertain():
    assert is_uncertain(0.6) is False
    assert is_uncertain(0.9) is False


def test_classifier_capability_prompt_is_loaded_from_the_registry():
    """The prompt itself must live under prompts/, versioned, per
    SPN-05 -- not as a string literal anywhere in this module. This
    loads the real, committed prompt file (no fake registry) to prove
    the capability name this module hard-codes actually resolves."""
    prompt = PromptRegistry().get(CLASSIFIER_CAPABILITY)
    assert prompt.capability == "chn09_classify_message"
    assert "{message_body}" in prompt.text
