"""
Per-channel weekly roll-up (CHN-19).

"Rates and trends are computed, never estimated by a model. The
narrative sentence is the only generated part." Every section of this
roll-up except the last is rendered directly from
p1.reporting.weekly_facts.WeeklyFacts -- participation rates, the
week-over-week trend, recurring blockers, decisions, and unanswered
questions are all plain arithmetic and verbatim quotes of the authors'
own message text, with no model call anywhere in their rendering. The
model is asked for exactly one thing: a single closing sentence of
narrative prose giving the week's overall tone, given everything above
it as a briefing.

That one sentence is not allowed to state a number. This is enforced,
not merely requested: WeeklyNarrativeDraft's own field_validator rejects
any digit character in the returned text, which p1.llm.structured.
generate_structured() treats exactly like any other schema validation
failure -- it retries automatically with the validator's own message
fed back as feedback, the same retry loop CHN-13's structured drafts
already use for an invalid label or a malformed field. A model that
tries to restate "3 decisions" or "40%" simply gets asked again, up to
generate_structured's own max_attempts, rather than that figure ever
reaching the rendered roll-up -- see DECISION_LOG.md for why this is a
validator, not just a prompt instruction.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date as date_type
from pathlib import Path

from pydantic import BaseModel, field_validator

from p1.config.schema import ChannelConfig
from p1.llm.structured import generate_structured
from p1.prompts import Prompt, PromptRegistry
from p1.reporting.weekly_facts import (
    ParticipationTrend,
    RecurringBlocker,
    WeeklyFact,
    WeeklyFacts,
    gather_weekly_facts,
)
from p1.storage.db import DEFAULT_DB_PATH, get_connection
from p1.storage.digests_repo import DigestStore
from p1.storage.members_repo import resolve_display_name

# Renders a member_id as a person's name. The default is the raw id, so a
# caller with no members table (a unit test) is unchanged; the real
# generate_weekly_rollup() passes a db-backed resolver.
NameOf = Callable[[str], str]


def _raw_id(member_id: str) -> str:
    return member_id

WEEKLY_ROLLUP_CAPABILITY = "chn19_weekly_narrative"


class WeeklyNarrativeDraft(BaseModel):
    narrative: str

    @field_validator("narrative")
    @classmethod
    def _no_digits(cls, value: str) -> str:
        if any(char.isdigit() for char in value):
            raise ValueError(
                "the narrative sentence must never contain a digit -- every figure is "
                "already rendered elsewhere in the roll-up; describe the week in words only"
            )
        return value


@dataclass(frozen=True)
class WeeklyRollupResult:
    channel_id: str
    week_start: str
    week_end: str
    facts: WeeklyFacts
    narrative: str
    content: str


def _plain(body: str) -> str:
    """A quoted message as readable text: Teams stores bodies as HTML
    (<p>...</p>, &nbsp;), which would otherwise print as literal markup
    in the roll-up. Display only -- the stored body is never changed."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body or ""))).strip()


def _format_pct(rate: float) -> str:
    return f"{round(rate * 100)}%"


def _format_trend(trend: ParticipationTrend) -> str:
    if trend.delta is None:
        return "no prior week to compare"
    points = round(trend.delta * 100)
    prior_pct = _format_pct(trend.prior.rate) if trend.prior.rate is not None else "n/a"
    if points > 0:
        return f"up {points} pts from last week ({prior_pct})"
    if points < 0:
        return f"down {abs(points)} pts from last week ({prior_pct})"
    return f"no change from last week ({prior_pct})"


def _render_participation(facts: WeeklyFacts, name_of: NameOf = _raw_id) -> list[str]:
    lines = ["## Participation", ""]
    for member_id in sorted(facts.participation):
        trend = facts.participation[member_id]
        current = trend.current
        if current.rate is None:
            lines.append(f"- **{name_of(member_id)}**: no working days this week to measure")
            continue
        lines.append(
            f"- **{name_of(member_id)}**: {_format_pct(current.rate)} "
            f"({current.contributed_days} of {current.working_days} working days) "
            f"— {_format_trend(trend)}"
        )
    for excluded in facts.excluded_members:
        lines.append(f"- **{name_of(excluded.member_id)}**: excluded ({excluded.reason})")
    lines.append("")
    return lines


def _render_recurring_blockers(
    blockers: list[RecurringBlocker], body_by_id: dict[str, str], name_of: NameOf = _raw_id,
) -> list[str]:
    lines = ["## Recurring blockers", ""]
    if not blockers:
        lines.append("No recurring blockers this week.")
    else:
        for blocker in blockers:
            days_str = ", ".join(blocker.days)
            lines.append(f"- **{name_of(blocker.author_id)}** raised a blocker on more than one day this week ({days_str}):")
            for message_id in blocker.message_ids:
                lines.append(f'  - "{_plain(body_by_id[message_id])}"')
    lines.append("")
    return lines


def _render_fact_list(title: str, facts: list[WeeklyFact], empty_text: str) -> list[str]:
    lines = [f"## {title}", ""]
    if not facts:
        lines.append(empty_text)
    else:
        for fact in facts:
            lines.append(f'- {fact.date}: "{_plain(fact.body_raw)}" ([source]({fact.permalink}))')
    lines.append("")
    return lines


def _render_briefing_block(facts: WeeklyFacts, name_of: NameOf = _raw_id) -> str:
    """The model-facing summary of everything already computed -- this
    MAY include numbers (the model needs real context to write a
    relevant sentence), the rule is only that its OWN output sentence
    may not restate one."""
    lines = []
    for member_id in sorted(facts.participation):
        trend = facts.participation[member_id]
        current = trend.current
        rate_str = _format_pct(current.rate) if current.rate is not None else "n/a"
        lines.append(f"- {name_of(member_id)}: {rate_str} this week ({_format_trend(trend)})")
    for excluded in facts.excluded_members:
        lines.append(f"- {name_of(excluded.member_id)}: excluded this week ({excluded.reason})")
    lines.append(f"- recurring blockers: {len(facts.recurring_blockers)} author(s)")
    lines.append(f"- decisions taken: {len(facts.decisions)}")
    lines.append(f"- questions unanswered all week: {len(facts.unanswered_questions)}")
    return "\n".join(lines)


def generate_weekly_rollup(
    channel_id: str,
    week_end: date_type,
    config: ChannelConfig,
    gateway,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    prompt_registry: PromptRegistry | None = None,
) -> WeeklyRollupResult:
    facts = gather_weekly_facts(channel_id, week_end, config, db_path=db_path)

    def name_of(member_id: str) -> str:
        return resolve_display_name(member_id, db_path=db_path)

    registry = prompt_registry or PromptRegistry()
    prompt: Prompt = registry.get(WEEKLY_ROLLUP_CAPABILITY)
    briefing_block = _render_briefing_block(facts, name_of)
    rendered_prompt = prompt.render(briefing_block=briefing_block)
    draft = generate_structured(
        gateway, rendered_prompt, WeeklyNarrativeDraft, tool_name="weekly_narrative",
    )

    body_by_id = {
        message_id: body
        for blocker in facts.recurring_blockers
        for message_id, body in _blocker_bodies(blocker, channel_id, config, db_path)
    }

    parts = [f"# {config.display_name} — Weekly Roll-up ({facts.week_start} to {facts.week_end})", ""]
    parts.extend(_render_participation(facts, name_of))
    parts.extend(_render_recurring_blockers(facts.recurring_blockers, body_by_id, name_of))
    parts.extend(_render_fact_list("Decisions this week", facts.decisions, "No decisions were taken this week."))
    parts.extend(
        _render_fact_list(
            "Questions that went unanswered all week", facts.unanswered_questions,
            "No questions went unanswered all week.",
        )
    )
    parts.append("## This week in brief")
    parts.append("")
    parts.append(draft.narrative)

    content = "\n".join(parts)

    return WeeklyRollupResult(
        channel_id=channel_id,
        week_start=facts.week_start,
        week_end=facts.week_end,
        facts=facts,
        narrative=draft.narrative,
        content=content,
    )


def _blocker_bodies(
    blocker: RecurringBlocker, channel_id: str, config: ChannelConfig, db_path: str | Path,
) -> list[tuple[str, str]]:
    """Looks up each recurring blocker's own message body, so the
    rendered roll-up can quote it verbatim -- RecurringBlocker itself
    only carries message_ids (it is a grouping fact, not a rendering
    one), the same separation WeeklyFact already draws for every other
    section."""
    if not blocker.message_ids:
        return []
    conn = get_connection(db_path)
    try:
        placeholders = ", ".join("?" for _ in blocker.message_ids)
        rows = conn.execute(
            f"SELECT id, body_raw FROM messages WHERE id IN ({placeholders})",
            blocker.message_ids,
        ).fetchall()
    finally:
        conn.close()
    return [(row["id"], row["body_raw"]) for row in rows]


def generate_and_persist_weekly_rollup(
    channel_id: str,
    week_end: date_type,
    config: ChannelConfig,
    gateway,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    prompt_registry: PromptRegistry | None = None,
) -> WeeklyRollupResult:
    result = generate_weekly_rollup(
        channel_id, week_end, config, gateway, db_path=db_path, prompt_registry=prompt_registry,
    )
    DigestStore(db_path).record(
        channel_id=channel_id,
        date=result.week_end,
        type="weekly",
        content=result.content,
        idempotency_key=f"{channel_id}:{result.week_end}:weekly",
    )
    return result
