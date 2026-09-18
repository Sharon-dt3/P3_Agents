"""
CHN-26: regenerates schema/outcome_record.v1.schema.json from
p1.contracts.outcome_record.OutcomeRecord itself, so the published
schema can never hand-drift from the code that actually produces
records. Run this after any change to OutcomeRecord's fields, then
commit the regenerated file -- tests/unit/test_outcome_record_schema.py
fails the build if the checked-in file and a fresh regeneration ever
disagree, the same discipline CHN-25 applied to its adaptive cards.
"""

from __future__ import annotations

import json
from pathlib import Path

from p1.contracts.outcome_record import OutcomeRecord, schema_version

OUTPUT_PATH = Path("schema") / "outcome_record.v1.schema.json"


def generate() -> dict:
    schema = OutcomeRecord.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://p1-channel.internal/schema/outcome_record/v{schema_version()}"
    schema["title"] = "P1 Channel outcome record"
    schema["description"] = (
        "One channel's one day's classified updates, blockers, decisions, "
        "questions and participation ledger -- the cross-agent contract P2 "
        "(and later P3) consume. Published by CHN-26; see "
        "docs/outcome_record_contract.md."
    )
    return schema


def main() -> None:
    schema = generate()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
