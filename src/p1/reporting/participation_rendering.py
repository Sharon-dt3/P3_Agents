"""
Honest participation rendering (CHN-14).

The three non-responder states CHN-10's ledger produces (NO_MESSAGE,
POSTED_NO_UPDATE, EXCLUDED) are rendered here, and only here, into the
exact wording a manager reads about a named colleague: "no message
posted", "posted, but no update", "excluded - on the exceptions list".
This lives in its own module -- not inlined into daily_summary.py's
digest assembly, where CHN-13 originally put it -- for two reasons:

1. The wording is a design decision, not a formatting detail (the WBS
   row's own words). Keeping it in exactly one place, reused by every
   digest surface that ever needs to render participation (today: the
   daily digest; tomorrow, a weekly one), is what keeps that decision
   from drifting into a slightly different phrasing the next time
   someone touches digest assembly.

2. "No inferred reasons, no adjectives, no ranking of people" is
   enforced structurally here, not just promised in a docstring:

   - No inferred reasons: render_participation_lines takes only
     ParticipationRecord (channel_id, member_id, date, state,
     evidence_message_ids) plus db_path -- and db_path is used only to
     resolve WHO member_id refers to (p1.storage.members_repo's own
     resolve_display_name, 2026-09-23, the same lookup CHN-23's
     escalation messages already used -- see DECISION_LOG.md), never to
     look up or interpolate anything about WHY they're in this state.
     CHN-10's ledger never copies a channel's
     configured exception reason (ChannelConfig.exceptions[*].reason,
     e.g. "On leave") onto the record in the first place -- see
     p1.participation.ledger.build_ledger -- so there is no reason
     text this function could reach for even if it wanted to. A
     member excluded on the exceptions list is rendered identically
     regardless of why they're on it.

   - No adjectives: PARTICIPATION_WORDING is a fixed map of exactly
     three literal strings. Nothing here interpolates a count, a
     duration, or a judgment call into them.

   - No ranking of people: this module never reorders records. It
     renders them in whatever order build_ledger already returned
     (sorted by member_id -- see test_ledger_is_sorted_by_member_id in
     test_participation_ledger.py), never by state, by how long
     someone's been silent, or by any other measure of severity.
"""

from __future__ import annotations

from pathlib import Path

from p1.participation.ledger import (
    EXCLUDED,
    NO_MESSAGE,
    POSTED_NO_UPDATE,
    ParticipationRecord,
)
from p1.storage.db import DEFAULT_DB_PATH
from p1.storage.members_repo import resolve_display_name

# The exact three-state wording the WBS row itself specifies. A manager
# reads this about a named colleague -- see this module's own docstring
# for why it is a fixed map, never built up from parts.
PARTICIPATION_WORDING = {
    NO_MESSAGE: "no message posted",
    POSTED_NO_UPDATE: "posted, but no update",
    EXCLUDED: "excluded - on the exceptions list",
}

_FALLBACK_LINE = "Every roster member contributed an update today."


def render_participation_lines(
    records: list[ParticipationRecord], *, db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    """One line per non-responder, in the order given -- see this
    module's own docstring for why that order is never touched here.
    Each member_id is resolved to a real display name via
    resolve_display_name() when one is known (see that function's own
    docstring); falls back to the bare id otherwise, exactly the
    previous behaviour -- see DECISION_LOG.md, 2026-09-23."""
    return [
        f"{resolve_display_name(record.member_id, db_path=db_path)} — {PARTICIPATION_WORDING[record.state]}"
        for record in records
    ]


def render_participation_section(
    records: list[ParticipationRecord], *, db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    """The full '## Participation' block of a digest, as a list of
    markdown lines ready to append to the rest of the digest. A day
    with no non-responders at all reads as an honest positive
    statement, never a bare, ambiguous empty section."""
    lines = ["## Participation"]
    entries = render_participation_lines(records, db_path=db_path)
    if entries:
        lines.extend(f"- {entry}" for entry in entries)
    else:
        lines.append(f"- {_FALLBACK_LINE}")
    lines.append("")
    return lines
