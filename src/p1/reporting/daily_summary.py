"""
Per-channel daily summary (CHN-13).

Facts in code, prose from the model -- the split the WBS row itself
names as what "lets the digest be regenerated without factual drift":

  1. p1.reporting.facts.gather_daily_facts reads the classifications and
     messages tables directly (never the model) to decide WHAT happened
     today: which messages were classified update/blocker/decision/question,
     on this channel, on this day, by a roster member, not deleted, and (for
     a question) not yet answered by any thread reply. This is the same
     kind of pure, DB-derived computation CHN-10's ledger already is --
     nothing here is the model's impression of what moved. That
     fact-gathering code lives in its own module, with no import of
     p1.llm or p1.prompts anywhere in it, specifically so
     tests/unit/test_no_inline_prompts.py (SPN-05) -- which only scans
     model-calling modules for prompt-shaped literals -- never has reason
     to flag this module's own long SQL text as a suspected inline prompt.
     See p1.reporting.facts's own docstring for the full rationale.

  2. The model (Claude API, via SPN-03's generate_structured) is asked
     only to turn each fact into one line of plain prose, one section at
     a time, never to decide what counts as a fact in the first place.

  3. Every line the model returns is passed through SPN-06's grounding
     kernel before it is allowed into the rendered digest -- see
     _generate_section_lines for why the message_lookup used here is
     deliberately scoped to just that section's own facts, not the
     general sqlite-backed lookup grounding/message_lookup.py provides.

  4. The participation section (CHN-10's ledger, read fresh via
     build_ledger rather than the persisted participation table, so a
     digest never reports a stale ledger) is rendered directly from
     code with no model call at all -- there is no prose to write for a
     roster diff, and CHN-14's honest-rendering wording
     ("no message posted" / "posted, but no update" /
     "excluded - on the exceptions list") is already the exact phrasing
     the master plan gives for those three states, adopted here now
     rather than left for CHN-14 to rewrite. See DECISION_LOG.md.

A channel with no traffic produces an honest empty summary: when a
section's fact list is empty, _generate_section_lines returns
immediately without ever calling the model -- the empty section is
rendered as a plain, honest statement ("No updates were posted today."),
never left for the model to fill in with invented content.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from pathlib import Path

from pydantic import BaseModel

from p1.config.schema import ChannelConfig
from p1.grounding.kernel import (
    FactualLine,
    GroundingFailure,
    GroundingResult,
    MessageLookup,
    ground_with_retry,
)
from p1.llm.structured import generate_structured
from p1.participation.ledger import (
    EXCLUDED,
    NO_MESSAGE,
    POSTED_NO_UPDATE,
    ParticipationRecord,
    build_ledger,
)
from p1.prompts import Prompt, PromptRegistry
from p1.reporting.facts import (
    SECTION_ORDER,
    DailyFact,
    gather_daily_facts,
    render_facts_block,
)
from p1.storage.db import DEFAULT_DB_PATH
from p1.storage.digests_repo import DigestStore

DAILY_SUMMARY_CAPABILITY = "chn13_daily_summary"

_SECTION_TITLES = {
    "what_moved": "What moved",
    "blockers": "Blockers raised",
    "decisions": "Decisions taken",
    "questions": "Questions still awaiting an answer",
}

# What the prompt calls this section -- matches the WBS row's own
# wording exactly, so the model is asked for precisely what the
# acceptance test names.
_SECTION_PROMPT_LABELS = {
    "what_moved": "what moved",
    "blockers": "blockers raised",
    "decisions": "decisions taken",
    "questions": "questions still awaiting an answer",
}

_EMPTY_SECTION_TEXT = {
    "what_moved": "No updates were posted today.",
    "blockers": "No blockers were raised today.",
    "decisions": "No decisions were taken today.",
    "questions": "No questions are awaiting an answer today.",
}

# CHN-14's own exact wording for the three non-responder states,
# adopted here rather than left as a placeholder -- see this module's
# docstring.
_PARTICIPATION_WORDING = {
    NO_MESSAGE: "no message posted",
    POSTED_NO_UPDATE: "posted, but no update",
    EXCLUDED: "excluded - on the exceptions list",
}


class DraftLine(BaseModel):
    """The model's own one-line prose for exactly one input fact.
    message_id is expected to be echoed back exactly as given -- the
    grounding kernel is what actually enforces that it is, not this
    schema, since a schema can only check shape, not truth."""

    message_id: str
    text: str
    quote: str | None = None


class DailySummarySectionDraft(BaseModel):
    lines: list[DraftLine]


@dataclass(frozen=True)
class DailySummaryResult:
    channel_id: str
    date: str
    section_lines: dict[str, list[FactualLine]]
    dropped: dict[str, list[GroundingFailure]]
    participation: list[ParticipationRecord]
    content: str


def _generate_section_lines(
    gateway,
    prompt: Prompt,
    section_prompt_label: str,
    facts: list[DailyFact],
):
    """Returns a GroundingResult for one section. Calls the model at
    most once per retry attempt, and never at all when facts is empty --
    an empty section is an honest fact, not a prompt to fill in.

    The message_lookup handed to the grounding kernel is built ONLY from
    this section's own facts, deliberately not the general
    sqlite-backed lookup grounding/message_lookup.py provides for other
    callers. A message_id that resolves to some OTHER real message
    elsewhere in the store (a different day, a different section, a
    different channel entirely) is not a fact this section was ever
    given, and reference-or-drop alone can't tell the difference -- only
    scoping the lookup to exactly the facts this call handed the model
    can. See DECISION_LOG.md."""
    if not facts:
        return GroundingResult()

    facts_block = render_facts_block(facts)
    facts_by_id = {fact.message_id: fact.body_raw for fact in facts}
    message_lookup: MessageLookup = facts_by_id.get

    def generate_fn(feedback: str | None) -> list[FactualLine]:
        feedback_block = f"\n{feedback}\n" if feedback else ""
        rendered = prompt.render(
            section_label=section_prompt_label,
            facts_block=facts_block,
            feedback_block=feedback_block,
        )
        draft = generate_structured(
            gateway, rendered, DailySummarySectionDraft, tool_name="daily_summary_section",
        )
        return [
            FactualLine(text=line.text, message_id=line.message_id, quote=line.quote)
            for line in draft.lines
        ]

    return ground_with_retry(generate_fn, message_lookup)


def _render_participation_lines(records: list[ParticipationRecord]) -> list[str]:
    return [f"{record.member_id} — {_PARTICIPATION_WORDING[record.state]}" for record in records]


def _render_digest_markdown(
    display_name: str,
    day: date_type,
    section_lines: dict[str, list[FactualLine]],
    permalink_by_id: dict[str, str],
    participation_lines: list[str],
) -> str:
    parts = [f"# {display_name} — Daily Summary ({day.isoformat()})", ""]

    for section in SECTION_ORDER:
        parts.append(f"## {_SECTION_TITLES[section]}")
        lines = section_lines[section]
        if not lines:
            parts.append(f"- {_EMPTY_SECTION_TEXT[section]}")
        else:
            for line in lines:
                permalink = permalink_by_id.get(line.message_id, "")
                parts.append(f"- {line.text} ([source]({permalink}))")
        parts.append("")

    parts.append("## Participation")
    if participation_lines:
        parts.extend(f"- {entry}" for entry in participation_lines)
    else:
        parts.append("- Every roster member contributed an update today.")
    parts.append("")

    return "\n".join(parts)


def generate_daily_summary(
    channel_id: str,
    day: date_type,
    config: ChannelConfig,
    gateway,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    prompt_registry: PromptRegistry | None = None,
) -> DailySummaryResult:
    registry = prompt_registry or PromptRegistry()
    prompt = registry.get(DAILY_SUMMARY_CAPABILITY)

    facts_by_section, permalink_by_id = gather_daily_facts(channel_id, day, config, db_path)

    section_lines: dict[str, list[FactualLine]] = {}
    dropped: dict[str, list[GroundingFailure]] = {}
    for section in SECTION_ORDER:
        result = _generate_section_lines(
            gateway, prompt, _SECTION_PROMPT_LABELS[section], facts_by_section[section],
        )
        section_lines[section] = result.grounded_lines
        dropped[section] = result.failures

    participation = build_ledger(channel_id, day, config, db_path=db_path)
    participation_lines = _render_participation_lines(participation)

    content = _render_digest_markdown(
        config.display_name, day, section_lines, permalink_by_id, participation_lines,
    )

    return DailySummaryResult(
        channel_id=channel_id,
        date=day.isoformat(),
        section_lines=section_lines,
        dropped=dropped,
        participation=participation,
        content=content,
    )


def generate_and_persist_daily_summary(
    channel_id: str,
    day: date_type,
    config: ChannelConfig,
    gateway,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    prompt_registry: PromptRegistry | None = None,
) -> DailySummaryResult:
    result = generate_daily_summary(
        channel_id, day, config, gateway, db_path=db_path, prompt_registry=prompt_registry,
    )
    DigestStore(db_path).record(
        channel_id=channel_id,
        date=result.date,
        type="daily",
        content=result.content,
        idempotency_key=f"{channel_id}:{result.date}:daily",
    )
    return result
