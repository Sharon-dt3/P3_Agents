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
from p1.storage.classification_points_repo import ClassificationPointsStore
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
    "m.permalink, m.thread_root_id, c.label "
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
) -> tuple[dict[str, list[DailyFact]], dict[str, str], list[DailyFact]]:
    """Returns (facts grouped by section, message_id -> permalink for
    every fact returned across all sections, questions answered today)
    for one channel and one calendar day.

    A question found answered (see _answered_question_ids) is not
    simply dropped -- from the outside, "detected as a question AND
    correctly found answered" and "never detected as a question at
    all" rendered identically: both just looked like the question
    wasn't there (2026-10-01, see DECISION_LOG.md). It is instead
    returned in its own third list, so the digest can show it was
    asked and resolved today instead of silently vanishing.

    A message with a stored points breakdown (classification_points,
    2026-10-01 -- see ClassificationResult.points' own docstring) is not
    one fact under its single dominant label: each distinct point is
    routed to ITS OWN section under its own label, so a bulky update
    that also contains a real blocker or a real question lands in
    "blockers"/"questions", not buried as an extra line under "what
    moved" the way it would under the message's one dominant label
    alone. A message with no stored points (most of them) falls back to
    exactly the prior, single-fact-per-message behaviour unchanged.

    Two or more of a message's OWN points sharing the same label (two
    distinct update-points in one message, say) are merged into a
    single DailyFact for that (message_id, label) pair, their texts
    joined -- never two separate facts with the same message_id in one
    section. That is not a stylistic choice: _generate_section_lines's
    own message_lookup is a plain {message_id: body_raw} dict, so a
    second fact sharing a message_id already in it would silently
    overwrite the first's text for grounding purposes. One entry per
    (message_id, section) avoids that collision entirely, and still
    lets the daily-summary prompt (v2, 2026-10-01) write one line per
    distinct point within that merged text."""
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
        points_by_message = ClassificationPointsStore(db_path).for_messages(
            [row["message_id"] for row in day_rows]
        )

        items = []
        for row in day_rows:
            points = points_by_message.get(row["message_id"])
            if not points:
                items.append({**dict(row), "body_raw": row["body_raw"]})
                continue
            by_label: dict[str, list[str]] = {}
            for point in points:
                by_label.setdefault(point["label"], []).append(point["point_text"])
            for label, texts in by_label.items():
                items.append({**dict(row), "label": label, "body_raw": " ".join(texts)})

        question_rows = [item for item in items if item["label"] == "question"]
        answered = _answered_question_ids(conn, question_rows)
    finally:
        conn.close()

    sections: dict[str, list[DailyFact]] = {section: [] for section in SECTION_ORDER}
    permalink_by_id: dict[str, str] = {}
    answered_questions: list[DailyFact] = []

    for item in items:
        fact = DailyFact(
            message_id=item["message_id"],
            author_id=item["author_id"],
            body_raw=item["body_raw"],
            permalink=item["permalink"],
            label=item["label"],
        )
        permalink_by_id[item["message_id"]] = item["permalink"]
        if item["label"] == "question" and item["message_id"] in answered:
            answered_questions.append(fact)
            continue
        sections[CONTENT_LABELS[item["label"]]].append(fact)

    return sections, permalink_by_id, answered_questions


def _answered_question_ids(conn, question_rows: list) -> set[str]:
    """A question counts as "still awaiting an answer" unless at least
    one non-deleted message, elsewhere in its own conversation thread,
    was posted after it. This is a deliberate simplification, not an
    oversight: there is no "answer" classification label this system
    produces (CHN-09's six labels are update/question/blocker/decision/
    chatter/noise), so "was this substantively answered" is not a fact
    this codebase can honestly compute yet. Any later message in the
    thread at all is treated as the channel having addressed it, rather
    than this module guessing at which replies count -- see
    DECISION_LOG.md.

    A question posted mid-thread (itself a reply, not the thread's own
    first message) has its OWN thread_root_id pointing at that thread's
    real root -- Teams/Graph channel replies are flat, so a later answer
    in the same thread also points at that same root, never at the
    question's own id. Each question's EFFECTIVE thread id is therefore
    its own thread_root_id when it has one, falling back to its own id
    only when the question itself is the thread's root.

    The asker's own later messages do not count: a person adding to their
    own question's thread has not been answered by anyone (live,
    2026-10-07: a question and the same author's follow-up in its thread
    moved the question to "answered"). Only a message from someone else does."""
    if not question_rows:
        return set()

    effective_thread_id = {
        row["message_id"]: (row["thread_root_id"] or row["message_id"]) for row in question_rows
    }
    question_posted_at = {row["message_id"]: row["posted_at"] for row in question_rows}
    question_author = {row["message_id"]: row["author_id"] for row in question_rows}
    thread_ids = sorted(set(effective_thread_id.values()))

    placeholders = ", ".join("?" for _ in thread_ids)
    sql = (
        "SELECT id, author_id, thread_root_id, posted_at FROM messages "
        f"WHERE thread_root_id IN ({placeholders}) AND is_deleted = 0"
    )
    reply_rows = conn.execute(sql, thread_ids).fetchall()

    answered: set[str] = set()
    for qid, tid in effective_thread_id.items():
        q_posted_at = question_posted_at[qid]
        for row in reply_rows:
            if row["thread_root_id"] != tid or row["id"] == qid or row["posted_at"] <= q_posted_at:
                continue
            if row["author_id"] == question_author[qid]:
                continue
            answered.add(qid)
            break
    return answered


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
