"""
Participation ledger and non-responder detection (CHN-10) -- Gate G0,
the first thin end-to-end slice: ingestion -> detection -> a ledger a
person can actually read.

Pure set arithmetic over the roster and the day's already-classified
messages -- never a model's impression of who was quiet. For one
channel and one calendar day (in the channel's own configured
timezone):

  roster          = every member_id in config.roster
  contributors    = roster members with >=1 message that day whose
                    classifications.label is update/question/blocker/
                    decision (chatter and noise never count, however
                    many of them a person posts)
  non_responders  = roster - contributors

A contributor is never written to the ledger at all -- this module (and
the participation table's own state column) only ever records
non-responders. Every member in non_responders gets exactly one of
three honest states, checked in this priority order -- never collapsed
into one, never guessed at:

  1. excluded          -- member_id is on config.exceptions, for as
                          long as that entry exists. An exception here
                          is NOT date-scoped: membership on the list is
                          the only fact used, never a date range parsed
                          out of its free-text `reason`. Attempting to
                          infer an effective date range from prose would
                          itself be exactly the kind of inference this
                          task's acceptance test forbids ("never infers
                          a reason for absence"). See DECISION_LOG.md.
                          Note this only applies to a non-responder: a
                          member on the exceptions list who nonetheless
                          posts a real update that day is a contributor
                          like anyone else and is not in the ledger.
  2. posted_no_update  -- member posted at least one non-deleted
                          message that day (any message at all -- late,
                          chatter, a thread reply this channel doesn't
                          count -- it still proves they weren't silent).
  3. no_message        -- neither of the above: nothing this member
                          wrote surfaced anywhere in the message store
                          for this day.

A deleted message is deliberately not "evidence of having posted" -- see
CHN-07's DIFF-DEL-01/02/03: the day must revert to a genuine no_message
day for that member, not a fabricated posted_no_update, since the
content was retracted.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date as date_type
from pathlib import Path

from p1.config.calendar import is_working_day, to_local
from p1.config.schema import ChannelConfig
from p1.storage.db import DEFAULT_DB_PATH, get_connection
from p1.storage.participation_repo import ParticipationStore

NO_MESSAGE = "no_message"
POSTED_NO_UPDATE = "posted_no_update"
EXCLUDED = "excluded"

_CONTRIBUTOR_LABELS = frozenset({"update", "question", "blocker", "decision"})


class NonWorkingDayError(Exception):
    """Raised when a ledger is requested for a day the channel's own
    config says nobody was expected to post on -- computing a
    non-responder set for a day nobody was asked to respond on would be
    a fabricated result, not an honest one."""


@dataclass(frozen=True)
class ParticipationRecord:
    channel_id: str
    member_id: str
    date: str  # ISO date, YYYY-MM-DD
    state: str
    evidence_message_ids: tuple[str, ...]


def build_ledger(
    channel_id: str,
    day: date_type,
    config: ChannelConfig,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[ParticipationRecord]:
    if not is_working_day(day, config):
        raise NonWorkingDayError(
            f"{day.isoformat()} is not a configured working day for {channel_id!r}; "
            "there is no non-responder set to compute for a day nobody was expected to post."
        )

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT m.id AS message_id, m.author_id, m.posted_at, m.is_deleted, c.label
            FROM messages m
            LEFT JOIN classifications c ON c.message_id = m.id
            WHERE m.channel_id = :channel_id
            """,
            {"channel_id": channel_id},
        ).fetchall()
    finally:
        conn.close()

    day_messages = [row for row in rows if to_local(row["posted_at"], config.timezone).date() == day]

    roster = set(config.roster)
    excepted = {e.member_id for e in config.exceptions}

    contributors: set[str] = set()
    posted: set[str] = set()
    evidence: dict[str, list[str]] = defaultdict(list)

    for row in day_messages:
        author = row["author_id"]
        if author is None or author not in roster:
            continue  # bot/system posts, or someone not on this channel's roster at all
        if row["is_deleted"]:
            continue  # a retracted message is not evidence of having posted
        posted.add(author)
        evidence[author].append(row["message_id"])
        if row["label"] in _CONTRIBUTOR_LABELS:
            contributors.add(author)

    non_responders = roster - contributors

    records = []
    for member_id in sorted(non_responders):
        if member_id in excepted:
            state = EXCLUDED
        elif member_id in posted:
            state = POSTED_NO_UPDATE
        else:
            state = NO_MESSAGE
        records.append(
            ParticipationRecord(
                channel_id=channel_id,
                member_id=member_id,
                date=day.isoformat(),
                state=state,
                evidence_message_ids=tuple(evidence.get(member_id, [])),
            )
        )
    return records


def build_and_persist_ledger(
    channel_id: str,
    day: date_type,
    config: ChannelConfig,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[ParticipationRecord]:
    records = build_ledger(channel_id, day, config, db_path=db_path)
    ParticipationStore(db_path).record(records)
    return records
