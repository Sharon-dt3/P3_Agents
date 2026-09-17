"""
Update detection -- deterministic rules first (CHN-08).

Every rule here answers one question: can we say, from structure alone
and without reading what the message actually says, that it can never
count as someone's update? If yes, that is settled right here, for
free, and traceably -- the acceptance test is that every settled
decision names the exact rule that fired and the message it fired on.
If no rule fires, the message is left deliberately unsettled: that is
the honest "this needs judgement" case, and it is exactly the set
CHN-09's classifier looks at. The model never sees a message a rule has
already decided.

Design decisions made here, not silently assumed:

- The update window is INCLUSIVE of both update_window_start and
  update_window_end (start <= posted_time <= end, in the channel's own
  configured timezone). This was deliberately left open during the
  CHN-07 rework -- the ambiguous exact-boundary fixture case was
  dropped in favour of an unambiguous one-minute-late one specifically
  so this choice could be made properly here. See DECISION_LOG.md.

- "Not a reaction" (named explicitly in the WBS) has no dedicated rule:
  Teams reactions never appear as messages at all in this system's
  model (Microsoft Graph does not expose them the same way as chat
  messages -- see CHN-07's DIFF-REACTION-01), so there is nothing at
  the message level to filter. A reaction-only member is a participation
  question (CHN-10), not a detection one.

- A rule decision assigns the classifications.label value "noise" when
  it settles a message, since none of these cases are genuine
  communication content a person should be credited or asked about.
  This is a rule-vs-model distinction, not a contradiction of CHN-09's
  "noise is discarded, not stored" note: that note is about the
  classifier declining to persist its own low-confidence noise calls;
  a rule's noise verdict IS persisted (when CHN-09 wires up storage),
  because a named, inspectable exclusion is the entire point of this
  task's acceptance test.

Persistence into the classifications table is intentionally NOT part of
this module. That table's rows are shared between rule- and model-
settled messages (method='rule'|'model'), and unifying "what still needs
classifying" is CHN-09's job, once the classifier path exists to unify
with. This module is a pure, DB-free decision function so it is fully
testable in isolation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig

NOISE_LABEL = "noise"

_WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class RuleDecision:
    """The outcome of running the deterministic rules against one
    message. settled=False means no rule could conclude anything --
    rule_name and label are then both None, and the message is eligible
    for CHN-09's classifier."""

    message_id: str
    settled: bool
    rule_name: str | None
    label: str | None
    reason: str

    @staticmethod
    def excluded(message_id: str, rule_name: str, reason: str) -> RuleDecision:
        return RuleDecision(message_id=message_id, settled=True, rule_name=rule_name, label=NOISE_LABEL, reason=reason)

    @staticmethod
    def eligible(message_id: str) -> RuleDecision:
        return RuleDecision(
            message_id=message_id,
            settled=False,
            rule_name=None,
            label=None,
            reason="no deterministic rule fired; eligible for classification",
        )


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 timestamp, tolerating a trailing 'Z' (UTC) the
    way datetime.fromisoformat on Python 3.10 does not."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _local_datetime(message: TeamsMessage, config: ChannelConfig) -> datetime:
    """The message's ORIGINAL post time (never edited_at), converted into
    the channel's own configured timezone -- window and working-day
    membership are always computed there, never in whatever zone the
    timestamp happened to arrive in."""
    posted = _parse_instant(message.posted_at)
    return posted.astimezone(ZoneInfo(config.timezone))


def _is_working_day(day: date, config: ChannelConfig) -> bool:
    if day in config.non_working_dates:
        return False
    return _WEEKDAY_NAMES[day.weekday()] in config.working_days


def _within_update_window(local_dt: datetime, config: ChannelConfig) -> bool:
    """Inclusive of both ends -- see the module docstring for why."""
    return config.update_window_start <= local_dt.time() <= config.update_window_end


# Each rule is (name, predicate, reason_template). Evaluated in this
# fixed order; the first predicate that returns True wins, so a given
# message always gets the same rule_name -- that determinism is what
# makes the audit trail meaningful rather than an artifact of dict
# ordering or evaluation luck.
def _rule_deleted_message(message: TeamsMessage, config: ChannelConfig) -> str | None:
    if message.is_deleted:
        return "message was deleted; deletion is not evidence of anything and can never count as an update"
    return None


def _rule_system_message(message: TeamsMessage, config: ChannelConfig) -> str | None:
    if message.is_system or message.author_id is None:
        return "Teams-generated system message with no human author"
    return None


def _rule_bot_post(message: TeamsMessage, config: ChannelConfig) -> str | None:
    if message.is_bot and config.ignore_bots:
        return "posted by a bot/connector and this channel's config ignores bot posts"
    return None


def _rule_not_on_roster(message: TeamsMessage, config: ChannelConfig) -> str | None:
    if message.author_id not in config.roster:
        return f"author_id={message.author_id!r} is not on this channel's config roster"
    return None


def _rule_thread_reply_not_counted(message: TeamsMessage, config: ChannelConfig) -> str | None:
    if message.thread_root_id is not None and not config.count_thread_replies:
        return "message is a thread reply and this channel's config does not count thread replies"
    return None


def _rule_non_working_day(message: TeamsMessage, config: ChannelConfig) -> str | None:
    local_dt = _local_datetime(message, config)
    if not _is_working_day(local_dt.date(), config):
        return f"{local_dt.date().isoformat()} is not a configured working day for this channel"
    return None


def _rule_outside_update_window(message: TeamsMessage, config: ChannelConfig) -> str | None:
    local_dt = _local_datetime(message, config)
    if not _within_update_window(local_dt, config):
        return (
            f"posted at {local_dt.time().isoformat()} {config.timezone}, outside the configured "
            f"update window {config.update_window_start}-{config.update_window_end}"
        )
    return None


def _rule_below_length_floor(message: TeamsMessage, config: ChannelConfig) -> str | None:
    body = (message.body or "").strip()
    if len(body) < config.length_floor:
        return f"message body is {len(body)} characters, below this channel's length_floor of {config.length_floor}"
    return None


_RuleFn = Callable[[TeamsMessage, ChannelConfig], "str | None"]

_RULES: list[tuple[str, _RuleFn]] = [
    ("deleted_message", _rule_deleted_message),
    ("system_message", _rule_system_message),
    ("bot_post", _rule_bot_post),
    ("not_on_roster", _rule_not_on_roster),
    ("thread_reply_not_counted", _rule_thread_reply_not_counted),
    ("non_working_day", _rule_non_working_day),
    ("outside_update_window", _rule_outside_update_window),
    ("below_length_floor", _rule_below_length_floor),
]


def evaluate_message(message: TeamsMessage, config: ChannelConfig) -> RuleDecision:
    """Run every rule, in order, against one message. Returns the first
    rule that fires, or an unsettled decision if none do."""
    for rule_name, rule_fn in _RULES:
        reason = rule_fn(message, config)
        if reason is not None:
            return RuleDecision.excluded(message.id, rule_name, reason)
    return RuleDecision.eligible(message.id)


def evaluate_messages(messages: list[TeamsMessage], config: ChannelConfig) -> list[RuleDecision]:
    return [evaluate_message(m, config) for m in messages]
