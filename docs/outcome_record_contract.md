# Outcome record contract (CHN-26)

One JSON file per channel per day: P1's published, versioned answer to
"what happened in this channel today" -- classified updates, blockers,
decisions, questions, and the participation ledger. This is the
contract P2 (the PM Delivery Steward) and later P3 consume; per the
master implementation plan, it is meant to be consumed "with no shared
code beyond the schema" -- a second, independently built process can
read a record with nothing more than the JSON Schema below and this
document, no import of anything in `p1.*`.

## Where records live

`outcomes/<slug(channel_id)>/<date>.json`, where `slug()` replaces
every character outside `[A-Za-z0-9_.-]` with `_` (a Teams channel_id
such as `19:proj-alpha@thread.tacv2` is not a safe path component
as-is). `date` is `YYYY-MM-DD`. Writing the same channel/day again
overwrites the file in place -- regenerating a day's record is always
safe, the same "safe to call any number of times" posture every other
idempotent write in this codebase has.

## Schema

Published at `schema/outcome_record.v1.schema.json`, generated
directly from `p1.contracts.outcome_record.OutcomeRecord`
(`scripts/generate_outcome_schema.py`) -- never hand-maintained, and
checked for drift by `tests/unit/test_outcome_record_schema.py`. The
record's own `schema_version` field (currently `"1.0"`) lets a consumer
holding only the JSON, no schema file at all, still tell which version
produced it.

| Field | Meaning |
|---|---|
| `schema_version` | This contract's version, e.g. `"1.0"` |
| `channel_id` | The Teams channel this record is for |
| `channel_display_name` | Human-readable channel name |
| `date` | The day this record covers, `YYYY-MM-DD` |
| `allowlisted` | Whether this channel was in-scope (CHN-04's own allowlist) when this record was produced -- the scope/consent flag this contract carries forward |
| `roster` | Every member_id expected to post in this channel. Anyone here with no entry in `participation` contributed that day |
| `updates` / `blockers` / `decisions` / `questions` | Each a list of grounded evidence items: `message_id`, `text` (the model's one-line prose), `quote` (a verbatim fragment, when the model gave one) |
| `participation` | Every NON-responder for the day: `member_id`, `state` (`no_message` \| `posted_no_update` \| `excluded`), `evidence_message_ids` |
| `generated_at` | When this record was produced (UTC ISO-8601) |

## What is and isn't in a record

Every `updates`/`blockers`/`decisions`/`questions` line is a line that
already passed SPN-06's grounding kernel -- the same bar CHN-13's own
Teams digest is held to, never a raw, unverified classification. This
is deliberately **not** gated on whether that day's digest *publish*
proposal (CHN-17) was itself approved for a Teams post: a channel
owner declining a Teams announcement is a decision about Teams, not a
reason to keep P2's own morning brief blind to what happened. See
`DECISION_LOG.md` for the full reasoning and the alternative considered.

A record never contains raw message bodies -- only the model's grounded
one-line prose plus an optional verbatim quote fragment, exactly what
CHN-13's own digest already shows a human. A consumer needing more than
that is not this contract's job.

## Consuming a record (P2's side)

```python
from p1.contracts.outcome_record import read_outcome
from datetime import date

record = read_outcome("19:proj-alpha@thread.tacv2", date(2026, 6, 1), output_dir="outcomes")
for item in record.updates:
    ...  # item.message_id, item.text, item.quote
contributors = set(record.roster) - {p.member_id for p in record.participation}
```

`read_outcome()` takes no database handle, gateway, or store of any
kind -- there is no parameter it could use to reach P1's message store
even if it wanted to. `tests/unit/test_outcome_record.py` proves this
structurally: several of its tests delete the sqlite database entirely
between writing a record and reading it back.

## Producing a record (P1's side)

```python
from p1.contracts.outcome_record import build_outcome_record, write_outcome
from p1.reporting.daily_summary import generate_daily_summary

result = generate_daily_summary(channel_id, day, config, gateway, db_path=db_path)
record = build_outcome_record(result, config)
write_outcome(record, output_dir="outcomes")
```

This row builds the emission function itself; wiring it into the
production scheduler loop (alongside or independently of CHN-17's own
daily digest job) is left to whichever later row actually schedules
production runs -- see `DECISION_LOG.md`.
