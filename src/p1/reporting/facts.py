"""
Daily summary fact-gathering (CHN-13) -- the "facts in code" half of
this capability's own split. Pure, DB-derived computation, exactly like
CHN-10's participation ledger: reads the classifications and messages
tables directly and decides WHAT happened today, never what a model
thinks happened. Deliberately kept in its own module, with no import of
p1.llm or p1.prompts anywhere in it -- tests/unit/test_no_inline_prompts.py
(SPN-05) only scans model-calling modules for prompt-shaped literals,
and this module's own SQL text is long and wordy enough to otherwise
trip that heuristic. Splitting the facts/prose concerns into separate
files is the same architectural boundary the WBS row itself draws
("Facts in code, prose from the model"), just enforced at the module
level too.

A message counts as a fact for one of the four content sections
(what_moved / blockers / decisions / questions) only if ALL of:
  - its classifications.label is update/blocker/decision/question
    (never chatter or noise -- a rule exclusion or a model "not an
    update" call is not a fact this digest reports on at all);
  - its author_id is on this channel's configured roster;
  - it is not deleted;
  - it carries a permalink -- "every factual line carries a message
    permalink" is a firm constraint of this capability, so a message
    with none is unusable here rather than rendered without one;
  - its own local posted_at (channel's configured timezone) falls on
    the requested day.

"Questions still awaiting an answer" additionally excludes any question
with at least one non-deleted thread reply already posted to it -- see
_answered_question_ids for why this doesn't try to judge whether that
reply substantively answers it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from pathlib import Path

from p1.config.calendar import to_local
from p1.config.schema import ChannelConfig
from p1.storage.db import DEFAULT_DB_PATH, get_connection

# The four classifications.label values that are ever a fact this digest
# reports on -- "noise" (every rule exclusion, and any model noise call,
# which CHN-09 never even persists) and "chatter" never appear here.
CONTENT_LABELS = {
    "update": "what_moved",
    "blocker": "blockers",
    "decision": "decisions",
    "question": "questions",
}

SECTION_ORDER = ("what_moved", "blockers", "decisions", "questions")

_SELECT_CLASSIFIED_MESSAGES_SQL = (
    "SELECT m.id AS message_id, m.author_id, m.posted_at, m.body_raw, "
    "m.permalink, c.label "
    "FROM messages m "
    "JOIN classifications c ON c.message_id = m.id "
    "WHERE m.channel_id = :channel_id AND m.is_deleted = 0 "
    "ORDER BY m.posted_at"
)


@dataclass(frozen=True)
class DailyFact:
    """One classified, roster-authored, non-deleted, permalinked message
    that counts as a fact for one of the four content sections today."""

    message_id: str
    author_id: str
    body_raw: str
    permalink: str
    label: str


def gather_daily_facts(
    channel_id: str,
    day: date_type,
    config: ChannelConfig,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> tuple[dict[str, list[DailyFact]], dict[str, str]]:
    """Returns (facts grouped by section, message_id -> permalink for
    every fact returned, across all sections) for one channel and one
    calendar day."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(_SELECT_CLASSIFIED_MESSAGES_SQL, {"channel_id": channel_id}).fetchall()

        roster = set(config.roster)
        day_rows = [
            row
            for row in rows
            if row["label"] in CONTENT_LABELS
            and row["author_id"] in roster
            and row["permalink"]
            and to_local(row["posted_at"], config.timezone).date() == day
        ]

        question_ids = [row["message_id"] for row in day_rows if row["label"] == "question"]
        answered = _answered_question_ids(conn, question_ids)
    finally:
        conn.close()

    sections: dict[str, list[DailyFact]] = {section: [] for section in SECTION_ORDER}
    permalink_by_id: dict[str, str] = {}

    for row in day_rows:
        if row["label"] == "question" and row["message_id"] in answered:
            continue
        section = CONTENT_LABELS[row["label"]]
        sections[section].append(
            DailyFact(
                message_id=row["message_id"],
                author_id=row["author_id"],
                body_raw=row["body_raw"],
                permalink=row["permalink"],
                label=row["label"],
            )
        )
        permalink_by_id[row["message_id"]] = row["permalink"]

    return sections, permalink_by_id


def _answered_question_ids(conn, question_ids: list[str]) -> set[str]:
    """A question counts as "still awaiting an answer" unless at least
    one non-deleted thread reply already exists to it. This is a
    deliberate simplification, not an oversight: there is no "answer"
    classification label this system produces (CHN-09's six labels are
    update/question/blocker/decision/chatter/noise), so "was this
    substantively answered" is not a fact this codebase can honestly
    compute yet. Any reply at all is treated as the channel having
    addressed it, rather than this module guessing at which replies
    count -- see DECISION_LOG.md."""
    if not question_ids:
        return set()
    placeholders = ", ".join("?" for _ in question_ids)
    sql = (
        "SELECT DISTINCT thread_root_id FROM messages "
        f"WHERE thread_root_id IN ({placeholders}) AND is_deleted = 0"
    )
    rows = conn.execute(sql, question_ids).fetchall()
    return {row["thread_root_id"] for row in rows}


def render_facts_block(facts: list[DailyFact]) -> str:
    """Numbered, human- and model-readable rendering of a section's
    facts, for interpolation into the CHN-13 prompt template."""
    lines = []
    for index, fact in enumerate(facts, start=1):
        lines.append(
            f"{index}. message_id: {fact.message_id}\n"
            f"   author: {fact.author_id}\n"
            f'   text: "{fact.body_raw}"'
        )
    return "\n".join(lines)
