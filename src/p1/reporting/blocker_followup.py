"""
A blocker that a later message says is sorted out.

The digest lists blockers by who raised them, and until now nothing connected a blocker to a later message that
said it was fixed: both appeared, the blocker under "Blockers raised" and the fix under "What moved", with
nothing saying the first had moved on (live, 2026-10-07).

One extra model call per digest (only when there is at least one blocker and at least one message posted after
it) asks, for each blocker, whether a later message says that same problem is resolved, and to quote the words.
Everything the reader sees is then checked in code, never taken on the model's word:

- the cited message must be one of the messages that was posted AFTER that blocker, today, by anyone;
- the quote must be an exact piece of that message's plain text, at least ``MIN_QUOTE_CHARS`` long;
- the blocker must be one of the labelled ones (B1, B2, ...).

What is rendered is the quote and a link, "later today: “…” (source)", next to the blocker. The blocker line is
never removed or reworded and the digest does not say the blocker IS resolved: the reader sees the words and
decides. A later message saying the problem continues is a reason the model reports nothing.

It can never make a digest worse than it was: any failure (the model unavailable, an answer that is not valid,
a quote that does not check out) gives no annotation and the digest is exactly what it would have been. On by
default; ``P1_BLOCKER_FOLLOWUPS=0`` switches it off.
"""

from __future__ import annotations

import html
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel

from p1.llm.structured import generate_structured
from p1.prompts import PromptRegistry
from p1.reporting.facts import DailyFact

logger = logging.getLogger(__name__)

BLOCKER_FOLLOWUP_CAPABILITY = "chn13_blocker_followup"
ENV_SWITCH = "P1_BLOCKER_FOLLOWUPS"
MIN_QUOTE_CHARS = 12  # a few words; a single word proves nothing
_ANSWER_TOKENS = 2048


class DraftFollowUp(BaseModel):
    blocker_id: str  # "B1", "B2", ... as labelled in the prompt
    later_message_id: str
    quote: str


class BlockerFollowUpDraft(BaseModel):
    follow_ups: list[DraftFollowUp] = []


@dataclass(frozen=True)
class FollowUp:
    """A later message, checked in code, to show next to one blocker line (1-based, in the order the blockers
    section lists them)."""

    blocker_line: int
    later_message_id: str
    quote: str
    permalink: str


def enabled(env=None) -> bool:
    return (os.environ if env is None else env).get(ENV_SWITCH, "") != "0"


def plain_text(text: str) -> str:
    """What a reader sees: tags removed, entities decoded (a non-breaking space is a space), spaces collapsed."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def _when(posted_at: str) -> datetime | None:
    try:
        return datetime.fromisoformat((posted_at or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _blocker_number(label: str) -> int | None:
    """"B3" (any case, any spaces) or a bare "3" -> 3. Labelled rather than counted so there is no 0-or-1 start to
    get wrong (live, 2026-10-07: the model answered 0 for the first blocker and the follow-up was lost)."""
    match = re.fullmatch(r"B?\s*(\d+)", (label or "").strip(), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _later_than(candidate: DailyFact, blocker: DailyFact) -> bool:
    candidate_at, blocker_at = _when(candidate.posted_at), _when(blocker.posted_at)
    if candidate_at is None or blocker_at is None:
        return False
    try:
        return candidate_at > blocker_at
    except TypeError:  # one with a timezone and one without: cannot be compared, so not trusted
        return False


def find_blocker_followups(
    gateway,
    registry: PromptRegistry,
    blocker_lines,
    facts_by_message: dict[str, list[DailyFact]],
    all_facts: list[DailyFact],
    permalink_by_id: dict[str, str],
    *,
    env=None,
) -> dict[int, FollowUp]:
    """{blocker line number: FollowUp}. Never raises."""
    if not enabled(env) or not blocker_lines:
        return {}
    try:
        return _find(gateway, registry, blocker_lines, facts_by_message, all_facts, permalink_by_id)
    except Exception as exc:  # noqa: BLE001 - an annotation must never cost the digest
        logger.warning("could not look for blocker follow-ups, digest unchanged: %s: %s", type(exc).__name__, exc)
        return {}


def _find(gateway, registry, blocker_lines, facts_by_message, all_facts, permalink_by_id) -> dict[int, FollowUp]:
    blocker_fact_for_line: dict[int, DailyFact] = {}
    for number, line in enumerate(blocker_lines, start=1):
        facts = facts_by_message.get(line.message_id) or []
        if facts:
            blocker_fact_for_line[number] = facts[0]

    later_for_line: dict[int, dict[str, DailyFact]] = {}
    for number, blocker in blocker_fact_for_line.items():
        later_for_line[number] = {
            f.message_id: f for f in all_facts if f.message_id != blocker.message_id and _later_than(f, blocker)
        }
    candidates: dict[str, DailyFact] = {}
    for later in later_for_line.values():
        candidates.update(later)
    if not candidates:
        return {}

    blockers_block = "\n".join(
        f"B{number}. (posted {blocker_fact_for_line[number].posted_at}) {line.text}"
        for number, line in enumerate(blocker_lines, start=1)
        if number in blocker_fact_for_line
    )
    candidates_block = "\n".join(
        f'- message_id: {fact.message_id}\n  posted: {fact.posted_at}\n  text: "{plain_text(fact.body_raw)}"'
        for fact in sorted(candidates.values(), key=lambda f: f.posted_at)
    )
    prompt = registry.get(BLOCKER_FOLLOWUP_CAPABILITY).render(
        blockers_block=blockers_block, candidates_block=candidates_block,
    )
    draft = generate_structured(
        gateway, prompt, BlockerFollowUpDraft, tool_name="blocker_followups", max_tokens=_ANSWER_TOKENS,
    )

    found: dict[int, FollowUp] = {}
    for item in draft.follow_ups:
        number = _blocker_number(item.blocker_id)
        later = later_for_line.get(number, {}).get(item.later_message_id) if number is not None else None
        quote = plain_text(item.quote)
        if later is None or number in found or len(quote) < MIN_QUOTE_CHARS:
            continue
        if quote not in plain_text(later.body_raw):
            continue
        found[number] = FollowUp(
            blocker_line=number,
            later_message_id=later.message_id,
            quote=quote,
            permalink=permalink_by_id.get(later.message_id, later.permalink),
        )
    return found
