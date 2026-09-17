from datetime import date, time

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig
from p1.detection.rules import NOISE_LABEL, evaluate_message, evaluate_messages

TZ = "Asia/Colombo"


def make_config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": "19:proj-test@thread.tacv2",
        "display_name": "Project Test",
        "allowlisted": True,
        "roster": ["alice", "bob"],
        "update_window_start": time(9, 0),
        "update_window_end": time(11, 0),
        "timezone": TZ,
        "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "length_floor": 10,
        "count_thread_replies": True,
        "ignore_bots": True,
        "daily_digest_time": time(11, 30),
        "weekly_digest_day": "Fri",
        "weekly_digest_time": time(16, 0),
        "channel_owner_id": "alice",
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


def make_message(**overrides) -> TeamsMessage:
    defaults = {
        "id": "msg-1",
        "channel_id": "19:proj-test@thread.tacv2",
        "author_id": "alice",
        "posted_at": "2025-06-02T09:30:00+05:30",  # a Monday, within the default window
        "body": "Finished the auth flow, running the tests now.",
    }
    defaults.update(overrides)
    return TeamsMessage(**defaults)


def test_eligible_message_is_left_unsettled():
    decision = evaluate_message(make_message(), make_config())
    assert decision.settled is False
    assert decision.rule_name is None
    assert decision.label is None


def test_deleted_message_is_excluded():
    decision = evaluate_message(make_message(is_deleted=True), make_config())
    assert decision.settled is True
    assert decision.rule_name == "deleted_message"
    assert decision.label == NOISE_LABEL


def test_system_message_is_excluded():
    decision = evaluate_message(make_message(author_id=None, is_system=True, body=""), make_config())
    assert decision.rule_name == "system_message"


def test_bot_post_is_excluded_when_ignore_bots_is_true():
    decision = evaluate_message(make_message(author_id="ci-bot", is_bot=True), make_config(ignore_bots=True))
    assert decision.rule_name == "bot_post"


def test_bot_post_is_not_excluded_when_ignore_bots_is_false():
    """The rule must respect config, never hard-code the policy."""
    decision = evaluate_message(make_message(author_id="ci-bot", is_bot=True), make_config(ignore_bots=False))
    # Falls through to not_on_roster instead, since ci-bot still isn't on the roster --
    # proving the bot check genuinely defers to config rather than always firing.
    assert decision.rule_name == "not_on_roster"


def test_not_on_roster_is_excluded():
    decision = evaluate_message(make_message(author_id="not-a-member"), make_config())
    assert decision.rule_name == "not_on_roster"


def test_thread_reply_excluded_when_config_does_not_count_replies():
    decision = evaluate_message(
        make_message(thread_root_id="root-1"), make_config(count_thread_replies=False)
    )
    assert decision.rule_name == "thread_reply_not_counted"


def test_thread_reply_eligible_when_config_counts_replies():
    decision = evaluate_message(
        make_message(thread_root_id="root-1"), make_config(count_thread_replies=True)
    )
    assert decision.settled is False


def test_weekend_is_excluded_as_non_working_day():
    # 2025-06-07 is a Saturday
    decision = evaluate_message(make_message(posted_at="2025-06-07T09:30:00+05:30"), make_config())
    assert decision.rule_name == "non_working_day"


def test_configured_non_working_date_is_excluded_even_on_a_weekday():
    decision = evaluate_message(
        make_message(posted_at="2025-06-13T09:30:00+05:30"),  # a Friday
        make_config(non_working_dates=[date(2025, 6, 13)]),
    )
    assert decision.rule_name == "non_working_day"


def test_posted_before_window_opens_is_excluded():
    decision = evaluate_message(make_message(posted_at="2025-06-02T08:59:59+05:30"), make_config())
    assert decision.rule_name == "outside_update_window"


def test_posted_one_minute_after_window_closes_is_excluded():
    decision = evaluate_message(make_message(posted_at="2025-06-02T11:01:00+05:30"), make_config())
    assert decision.rule_name == "outside_update_window"


def test_window_boundaries_are_inclusive():
    """Explicit design decision (see rules.py docstring): both the exact
    start and exact end instant count as inside the window."""
    at_start = evaluate_message(make_message(posted_at="2025-06-02T09:00:00+05:30"), make_config())
    at_end = evaluate_message(make_message(posted_at="2025-06-02T11:00:00+05:30"), make_config())
    assert at_start.settled is False
    assert at_end.settled is False


def test_window_is_evaluated_in_the_channels_own_timezone_not_utc():
    # 09:30 America/New_York is 13:30 UTC -- if the rule mistakenly compared
    # in UTC this would wrongly look like it's outside a 09:00-11:00 window.
    decision = evaluate_message(
        make_message(posted_at="2025-06-02T09:30:00-04:00"),
        make_config(timezone="America/New_York"),
    )
    assert decision.settled is False


def test_below_length_floor_is_excluded():
    decision = evaluate_message(make_message(body="Thanks!"), make_config(length_floor=10))
    assert decision.rule_name == "below_length_floor"


def test_at_exactly_length_floor_is_not_excluded():
    decision = evaluate_message(make_message(body="1234567890"), make_config(length_floor=10))
    assert decision.settled is False


def test_edited_message_uses_posted_at_never_edited_at():
    """An edit landing after the window closes must not disqualify a
    message that was posted on time -- CHN-08 must key off posted_at."""
    decision = evaluate_message(
        make_message(
            posted_at="2025-06-02T09:30:00+05:30",
            edited_at="2025-06-02T11:45:00+05:30",  # well after window close
        ),
        make_config(),
    )
    assert decision.settled is False


def test_deleted_message_takes_precedence_over_every_other_rule():
    """A message that is simultaneously deleted, too short and outside
    the window must still be reported as 'deleted', the most specific
    and most decisive fact about it -- not whichever rule happens to be
    checked first for an unrelated reason."""
    decision = evaluate_message(
        make_message(is_deleted=True, body="hi", posted_at="2025-06-02T23:00:00+05:30"),
        make_config(),
    )
    assert decision.rule_name == "deleted_message"


def test_rule_precedence_is_deterministic_not_dict_ordering_luck():
    """A message that is both a bot post and not on the roster must
    always report the more specific 'bot_post', proving the evaluation
    order is a fixed, documented sequence."""
    decision = evaluate_message(
        make_message(author_id="ci-bot", is_bot=True), make_config()
    )
    assert decision.rule_name == "bot_post"


def test_evaluate_messages_preserves_order_and_evaluates_each_independently():
    messages = [
        make_message(id="m1", is_deleted=True),
        make_message(id="m2"),
    ]
    decisions = evaluate_messages(messages, make_config())
    assert [d.message_id for d in decisions] == ["m1", "m2"]
    assert decisions[0].settled is True
    assert decisions[1].settled is False


def test_all_rule_names_are_unique():
    from p1.detection.rules import _RULES

    names = [name for name, _ in _RULES]
    assert len(names) == len(set(names))
