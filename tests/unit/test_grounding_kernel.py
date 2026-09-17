import logging

from p1.grounding.kernel import (
    FactualLine,
    ground_with_retry,
    verify_line,
    verify_lines,
)

MESSAGE_TEXT = "Finished the auth flow, running the tests now."


def _lookup(message_id: str) -> str | None:
    return {"m1": MESSAGE_TEXT}.get(message_id)


def test_line_with_resolvable_id_and_no_quote_passes():
    line = FactualLine(text="Priya finished the auth flow.", message_id="m1")
    assert verify_line(line, _lookup) is None


def test_line_with_no_message_id_fails_as_unresolvable():
    line = FactualLine(text="Priya finished the auth flow.", message_id=None)
    failure = verify_line(line, _lookup)
    assert failure is not None
    assert failure.reason == "unresolvable_message_id"


def test_line_with_unknown_message_id_fails_as_unresolvable():
    line = FactualLine(text="Priya finished the auth flow.", message_id="does-not-exist")
    failure = verify_line(line, _lookup)
    assert failure is not None
    assert failure.reason == "unresolvable_message_id"


def test_line_with_verbatim_quote_passes():
    line = FactualLine(text="Priya said she is done.", message_id="m1", quote="running the tests now.")
    assert verify_line(line, _lookup) is None


def test_line_with_near_miss_quote_fails():
    line = FactualLine(
        text="Priya said she is done.", message_id="m1",
        quote="running the test now.",  # singular "test" -- not a literal substring
    )
    failure = verify_line(line, _lookup)
    assert failure is not None
    assert failure.reason == "quote_not_verbatim"


def test_verify_lines_partitions_pass_and_fail():
    good = FactualLine(text="ok", message_id="m1")
    bad = FactualLine(text="bad", message_id=None)
    result = verify_lines([good, bad], _lookup)
    assert result.grounded_lines == [good]
    assert len(result.failures) == 1
    assert result.failures[0].line == bad


def test_ground_with_retry_succeeds_on_first_attempt_without_feedback():
    calls = []

    def generate_fn(feedback):
        calls.append(feedback)
        return [FactualLine(text="ok", message_id="m1")]

    result = ground_with_retry(generate_fn, _lookup, max_attempts=3)

    assert calls == [None]
    assert len(result.grounded_lines) == 1
    assert result.failures == []


def test_ground_with_retry_feeds_the_failure_back_on_the_next_attempt():
    calls = []

    def generate_fn(feedback):
        calls.append(feedback)
        if len(calls) == 1:
            return [FactualLine(text="bad", message_id=None)]
        return [FactualLine(text="fixed", message_id="m1")]

    result = ground_with_retry(generate_fn, _lookup, max_attempts=3)

    assert len(calls) == 2
    assert calls[0] is None
    assert calls[1] is not None
    assert "unresolvable_message_id" in calls[1]
    assert len(result.grounded_lines) == 1
    assert result.grounded_lines[0].text == "fixed"
    assert result.failures == []


def test_ground_with_retry_drops_and_logs_after_exhausting_attempts(caplog):
    def generate_fn(feedback):
        return [FactualLine(text="always bad", message_id=None)]

    with caplog.at_level(logging.WARNING, logger="p1.grounding.kernel"):
        result = ground_with_retry(generate_fn, _lookup, max_attempts=2)

    assert result.grounded_lines == []
    assert len(result.failures) == 1
    assert "grounding_dropped" in caplog.text


def test_hand_forged_line_with_no_message_id_is_dropped_and_logged(caplog):
    """SPN-06's own acceptance test, first half."""
    line = FactualLine(text="Priya finished the auth flow.", message_id=None)

    with caplog.at_level(logging.WARNING, logger="p1.grounding.kernel"):
        result = ground_with_retry(lambda feedback: [line], _lookup, max_attempts=1)

    assert result.grounded_lines == []
    assert result.failures[0].reason == "unresolvable_message_id"
    assert "grounding_dropped" in caplog.text


def test_near_miss_quote_is_rejected_and_retried():
    """SPN-06's own acceptance test, second half: a near-miss quote is
    rejected, and the retry loop gives the caller's generator another
    attempt to fix it before anything is dropped."""
    attempts = []

    def generate_fn(feedback):
        attempts.append(feedback)
        if len(attempts) == 1:
            # missing the comma -- not a literal substring of MESSAGE_TEXT
            return [FactualLine(text="...", message_id="m1", quote="Finished the auth flow running the tests now.")]
        return [FactualLine(text="...", message_id="m1", quote=MESSAGE_TEXT)]

    result = ground_with_retry(generate_fn, _lookup, max_attempts=2)

    assert len(attempts) == 2
    assert attempts[0] is None
    assert attempts[1] is not None
    assert "quote_not_verbatim" in attempts[1]
    assert len(result.grounded_lines) == 1
    assert result.failures == []
