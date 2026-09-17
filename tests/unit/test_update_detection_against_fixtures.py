"""
CHN-08 exercised against the real CHN-07 fixtures and labels.csv, not
just hand-written test cases -- this is what proves the planted
difficulties are actually useful, not just present. For every planted
message where sheet 06 gives an unambiguous structural verdict, assert
the rule engine reaches it, with the specific rule named.

Cases planted deliberately for CHN-09 (content judgement) rather than
CHN-08 -- the edited messages, the reply-only update, posting on behalf
of another, the ambiguous @mention -- are asserted here as the opposite:
structurally ELIGIBLE, never excluded by a rule. If CHN-08 ever started
excluding one of these, it would be silently doing CHN-09's job badly
instead of leaving it for the classifier, which is exactly the failure
mode this task exists to prevent.
"""

import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from p1.adapters.fixtures import load_teams_fixtures
from p1.config.loader import ChannelConfigStore
from p1.detection.rules import evaluate_message

FIXTURES_DIR = Path("seed/fixtures")


def _load_labels() -> dict[str, dict]:
    with open(FIXTURES_DIR / "labels.csv", newline="") as f:
        return {row["difficulty_id"]: row for row in csv.DictReader(f)}


def _message_index():
    _, _, messages = load_teams_fixtures()
    index = {}
    for msgs in messages.values():
        for m in msgs:
            index[m.id] = m
    return index


def _configs_by_channel():
    store = ChannelConfigStore()
    return {c.channel_id: c for c in store.list_configured_channels()}


def test_bot_posts_are_excluded_as_bot_post():
    labels = _load_labels()
    messages = _message_index()
    configs = _configs_by_channel()

    for difficulty_id in ("DIFF-BOT-01", "DIFF-BOT-02"):
        msg_id = labels[difficulty_id]["message_ids"]
        message = messages[msg_id]
        decision = evaluate_message(message, configs[message.channel_id])
        assert decision.rule_name == "bot_post", f"{difficulty_id} ({msg_id}) should be excluded as bot_post"


def test_system_post_is_excluded_as_system_message():
    labels = _load_labels()
    messages = _message_index()
    configs = _configs_by_channel()

    msg_id = labels["DIFF-SYS-01"]["message_ids"]
    message = messages[msg_id]
    decision = evaluate_message(message, configs[message.channel_id])
    assert decision.rule_name == "system_message"


def test_deleted_messages_are_excluded_as_deleted_message():
    labels = _load_labels()
    messages = _message_index()
    configs = _configs_by_channel()

    for difficulty_id in ("DIFF-DEL-01", "DIFF-DEL-02", "DIFF-DEL-03"):
        msg_id = labels[difficulty_id]["message_ids"]
        message = messages[msg_id]
        # DIFF-DEL-03 lives in proj-gamma, which is not allowlisted -- in
        # the real pipeline CHN-04's scope gate means it would never reach
        # this point at all. Evaluated directly here anyway, since the
        # rule engine itself is a pure function with no opinion on scope.
        decision = evaluate_message(message, configs[message.channel_id])
        assert decision.rule_name == "deleted_message", f"{difficulty_id} ({msg_id})"


def test_late_post_is_excluded_as_outside_update_window():
    labels = _load_labels()
    messages = _message_index()
    configs = _configs_by_channel()

    msg_id = labels["DIFF-LATE-01"]["message_ids"]
    message = messages[msg_id]
    decision = evaluate_message(message, configs[message.channel_id])
    assert decision.rule_name == "outside_update_window"


def test_edited_messages_remain_eligible_for_classification():
    """Editing must never disqualify an on-time post -- CHN-08 keys off
    posted_at, and none of these edits should trip any structural rule."""
    labels = _load_labels()
    messages = _message_index()
    configs = _configs_by_channel()

    for difficulty_id in ("DIFF-EDIT-01", "DIFF-EDIT-02", "DIFF-EDIT-03"):
        msg_id = labels[difficulty_id]["message_ids"]
        message = messages[msg_id]
        decision = evaluate_message(message, configs[message.channel_id])
        assert decision.settled is False, f"{difficulty_id} ({msg_id}) should be eligible, not rule-excluded"


def test_thread_reply_only_update_remains_eligible():
    messages = _message_index()
    configs = _configs_by_channel()

    reply_id = "diff-thread-01-reply-1"
    message = messages[reply_id]
    decision = evaluate_message(message, configs[message.channel_id])
    assert decision.settled is False


def test_posting_on_behalf_of_another_remains_eligible():
    labels = _load_labels()
    messages = _message_index()
    configs = _configs_by_channel()

    msg_id = labels["DIFF-ONBEHALF-01"]["message_ids"]
    message = messages[msg_id]
    decision = evaluate_message(message, configs[message.channel_id])
    assert decision.settled is False


def test_ambiguous_mention_remains_eligible():
    labels = _load_labels()
    messages = _message_index()
    configs = _configs_by_channel()

    msg_id = labels["DIFF-MENTION-01"]["message_ids"]
    message = messages[msg_id]
    decision = evaluate_message(message, configs[message.channel_id])
    assert decision.settled is False


def test_departed_tenant_members_historical_messages_remain_eligible():
    """sofia.almeida's messages, posted while she was still active, must
    not be excluded by any structural rule -- she was a valid roster
    member in good standing at the time she posted."""
    labels = _load_labels()
    messages = _message_index()
    configs = _configs_by_channel()

    msg_ids = labels["DIFF-DEPART-01"]["message_ids"].split(";")
    for msg_id in msg_ids:
        message = messages[msg_id]
        decision = evaluate_message(message, configs[message.channel_id])
        assert decision.settled is False, msg_id


def test_chatter_only_members_longer_messages_are_not_excluded_by_rules():
    """fatima.hassan's chatter is structurally eligible for several of
    her messages (long enough, posted in-window, on the roster) even
    though it is semantically never a real update -- proving CHN-08 does
    not attempt the content judgement that is CHN-09's job.

    Candidates are filtered to messages actually posted inside the
    channel's update window, not just long enough: the window is itself
    a legitimate structural gate (see outside_update_window), and a
    message posted outside it -- however long -- is correctly excluded
    by CHN-08 for a structural reason that has nothing to do with
    content. Conflating "long enough" with "structurally eligible" here
    would make this test assert something CHN-08 was never meant to
    guarantee.
    """
    _, _, messages = load_teams_fixtures()
    configs = _configs_by_channel()
    alpha = "19:proj-alpha@thread.tacv2"
    config = configs[alpha]
    tz = ZoneInfo(config.timezone)

    fatima_messages = [m for m in messages[alpha] if m.author_id == "fatima.hassan"]
    assert fatima_messages, "expected at least one organic message from fatima.hassan"

    def _posted_in_window(message) -> bool:
        local_time = datetime.fromisoformat(message.posted_at).astimezone(tz).time()
        return config.update_window_start <= local_time <= config.update_window_end

    candidates = [
        m
        for m in fatima_messages
        if len(m.body.strip()) >= config.length_floor and _posted_in_window(m)
    ]
    assert candidates, (
        "expected at least one of her chatter messages to be both long enough "
        "and posted inside the update window"
    )

    for message in candidates:
        decision = evaluate_message(message, config)
        assert decision.settled is False, (
            f"{message.id} ({message.body!r}) should be eligible for CHN-09 to judge as chatter, "
            "not excluded by a structural rule"
        )
