"""
Optional live smoke test for CHN-09: asks the real Claude API the exact
question CHN-09's own acceptance test poses, the same way CHN-01's
device-code script is the one place that asks the real Graph API for a
real message. Everything else in this suite (test_classifier.py,
test_pipeline.py) proves the code's behaviour deterministically with a
FakeGateway and needs no network access or API key; this file is the
one place that genuinely exercises live model judgement, and is skipped
automatically wherever no ANTHROPIC_API_KEY is configured -- it never
fails a run that simply doesn't have one.
"""

import os

import pytest

from p1.adapters.teams_reader import TeamsMessage
from p1.detection.classifier import classify_message
from p1.llm.gateway import LLMGateway

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="Requires a real ANTHROPIC_API_KEY to call the live Claude API",
)


def _message(body: str) -> TeamsMessage:
    return TeamsMessage(
        id="live-1",
        channel_id="19:proj-test@thread.tacv2",
        author_id="alice",
        posted_at="2025-06-02T09:30:00+05:30",
        body=body,
    )


def test_status_shaped_message_is_labelled_update_live():
    gateway = LLMGateway()
    result = classify_message(_message("Finished the auth flow, running the tests now."), gateway)
    assert result.label == "update"


def test_thanks_will_look_reply_is_not_labelled_update_live():
    gateway = LLMGateway()
    result = classify_message(_message("Thanks, will look."), gateway)
    assert result.label != "update"
