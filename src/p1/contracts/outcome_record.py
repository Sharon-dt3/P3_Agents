"""
CHN-26: the versioned outcome record (P1 Channel).

"THIS IS THE CONTRACT THE P2 PM AGENT CONSUMES" -- this row's own
framing, in caps, and taken literally here: one JSON file per channel
per day, its shape published as a JSON Schema
(schema/outcome_record.v1.schema.json, generated from the very
OutcomeRecord model below -- see scripts/generate_outcome_schema.py
and tests/unit/test_outcome_record_schema.py, so the published schema
can never silently drift from the code the way a hand-maintained
schema doc could), carrying exactly the four classified fact
categories CHN-13's own daily summary already computes (updates,
blockers, decisions, questions) plus CHN-10's participation ledger.

Nothing here re-derives those facts independently. build_outcome_record()
takes the SAME DailySummaryResult generate_daily_summary() (CHN-13)
already produces -- the same grounded, retry-verified lines that would
be rendered into the Teams digest -- and serializes it into this
contract's shape. That is what "approved and classified items only"
(the master plan's own note on this row) means in this codebase: never
a raw classified fact straight off the detection pipeline, always one
that has already passed SPN-06's grounding kernel, the same bar the
digest itself is held to. It is deliberately NOT gated on whether that
day's digest PROPOSAL (CHN-17) was itself approved for a Teams post --
a channel owner declining to post a Teams announcement about today
is a decision about Teams, not a reason to keep P2's own morning brief
blind to what genuinely happened in the channel; see DECISION_LOG.md.

read_outcome()'s own signature is the proof behind this row's
acceptance test ("a second process reconstructs the day's updates and
participation from the record with no access to the message store"):
it takes no db_path, no gateway, nothing that could reach messages/
classifications/participation tables at all -- there is no code path
by which reading a record could fall back to querying the database
that produced it, structurally, not merely by convention.

Every evidence item (an update/blocker/decision/question line) carries
the exact message_id and quote SPN-06's grounding kernel already
verified for it -- a second process gets the same citation trail a
human reading the digest would, never a bare unsourced claim.

roster/allowlisted are carried alongside participation so a consumer
can tell contributors from non-responders using the record alone:
build_ledger() only ever emits a row for a non-responder (no_message/
posted_no_update/excluded); anyone in roster with no participation
entry contributed that day -- the "scope/consent flags forward" half
of the master plan's own note on this row.
"""

from __future__ import annotations

import json
import re
from datetime import date as date_type
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from p1.config.schema import ChannelConfig
from p1.grounding.kernel import FactualLine
from p1.participation.ledger import ParticipationRecord
from p1.reporting.daily_summary import DailySummaryResult

SCHEMA_VERSION = "1.0"

DEFAULT_OUTCOMES_DIR = Path("outcomes")

_SECTION_TO_FIELD = {
    "what_moved": "updates",
    "blockers": "blockers",
    "decisions": "decisions",
    "questions": "questions",
}


def schema_version() -> str:
    """The one place this contract's current version lives -- read by
    both write_outcome() (stamped into every record) and
    scripts/generate_outcome_schema.py (stamped into the published
    schema file's own filename and $id)."""
    return SCHEMA_VERSION


class EvidenceItem(BaseModel):
    """One grounded factual line -- an update, blocker, decision, or
    question -- exactly as SPN-06's grounding kernel verified it.
    message_id is required (never null): only a line that already
    carried a resolvable message_id could have passed grounding and
    reached DailySummaryResult.section_lines in the first place."""

    message_id: str
    text: str
    quote: str | None = None


class ParticipationEntry(BaseModel):
    """One non-responder for the day -- CHN-10's own three states.
    Someone on the roster with no entry here contributed that day; see
    this module's own docstring."""

    member_id: str
    state: str = Field(description="no_message | posted_no_update | excluded")
    evidence_message_ids: list[str] = Field(default_factory=list)


class OutcomeRecord(BaseModel):
    """The published contract itself. schema_version is a plain string
    field (not just a filename convention) so a consumer holding only
    the JSON -- no code, no schema file -- can still tell which version
    produced it."""

    schema_version: str
    channel_id: str
    channel_display_name: str
    date: date_type
    allowlisted: bool
    roster: list[str]
    updates: list[EvidenceItem] = Field(default_factory=list)
    blockers: list[EvidenceItem] = Field(default_factory=list)
    decisions: list[EvidenceItem] = Field(default_factory=list)
    questions: list[EvidenceItem] = Field(default_factory=list)
    participation: list[ParticipationEntry] = Field(default_factory=list)
    generated_at: str


def _evidence_items(lines: list[FactualLine]) -> list[EvidenceItem]:
    return [EvidenceItem(message_id=line.message_id, text=line.text, quote=line.quote) for line in lines]


def _participation_entries(records: list[ParticipationRecord]) -> list[ParticipationEntry]:
    return [
        ParticipationEntry(
            member_id=r.member_id, state=r.state, evidence_message_ids=list(r.evidence_message_ids),
        )
        for r in records
    ]


def build_outcome_record(result: DailySummaryResult, config: ChannelConfig) -> OutcomeRecord:
    """Serializes an already-computed DailySummaryResult (CHN-13) into
    this contract's shape -- never a second, independent read of the
    classifications/messages tables. See this module's own docstring
    for why that is the load-bearing design choice here."""
    kwargs = {
        section_field: _evidence_items(result.section_lines[section])
        for section, section_field in _SECTION_TO_FIELD.items()
    }
    return OutcomeRecord(
        schema_version=schema_version(),
        channel_id=result.channel_id,
        channel_display_name=config.display_name,
        date=date_type.fromisoformat(result.date),
        allowlisted=config.allowlisted,
        roster=list(config.roster),
        participation=_participation_entries(result.participation),
        generated_at=datetime.now(timezone.utc).isoformat(),
        **kwargs,
    )


def _slug(channel_id: str) -> str:
    """channel_id (e.g. "19:proj-alpha@thread.tacv2") is not always a
    safe path component -- this is the one place that gets normalized,
    so write_outcome()/read_outcome() always agree on where a given
    channel's records live without either one guessing at the other's
    convention."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", channel_id)


def _record_path(channel_id: str, day: date_type, output_dir: str | Path) -> Path:
    return Path(output_dir) / _slug(channel_id) / f"{day.isoformat()}.json"


def write_outcome(record: OutcomeRecord, *, output_dir: str | Path = DEFAULT_OUTCOMES_DIR) -> Path:
    """Writes one channel's one day's record, overwriting whatever was
    there before -- regenerating today's record is always safe, the
    same "safe to call any number of times" posture every other
    idempotent write in this codebase has, just as a plain file
    overwrite here rather than an upsert-on-key, since nothing about
    writing a data file to disk needs SPN-08/09's proposal/approval
    machinery -- that machinery exists for actions that send something
    to a person (a channel post, a DM); this never does."""
    path = _record_path(record.channel_id, record.date, output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True) + "\n")
    return path


def read_outcome(
    channel_id: str, day: date_type, *, output_dir: str | Path = DEFAULT_OUTCOMES_DIR,
) -> OutcomeRecord:
    """Reads one channel's one day's record back, re-validated through
    the exact same OutcomeRecord model that wrote it -- a malformed or
    hand-edited file fails loudly here, never silently. Deliberately
    takes no db_path/gateway/store of any kind: there is no parameter
    this function could use to reach the message store even if it
    wanted to, which is the actual mechanism behind this row's own
    acceptance test, not merely a promise kept by convention."""
    path = _record_path(channel_id, day, output_dir)
    if not path.exists():
        raise FileNotFoundError(f"No outcome record for channel_id={channel_id!r} date={day.isoformat()!r} at {path}")
    return OutcomeRecord.model_validate(json.loads(path.read_text()))
