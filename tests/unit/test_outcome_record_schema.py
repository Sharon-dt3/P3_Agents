"""
CHN-26: the published JSON Schema (schema/outcome_record.v1.schema.json)
must never drift from p1.contracts.outcome_record.OutcomeRecord --
this test regenerates it in-process (scripts/generate_outcome_schema.py's
own generate()) and fails if that disagrees with the checked-in file,
the same "docs cannot outrun the code" discipline CHN-25 applied to its
adaptive cards.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema" / "outcome_record.v1.schema.json"


def _regenerate() -> dict:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import generate_outcome_schema

    return generate_outcome_schema.generate()


def test_checked_in_schema_file_exists():
    assert SCHEMA_PATH.exists(), "run scripts/generate_outcome_schema.py and commit its output"


def test_checked_in_schema_matches_a_fresh_regeneration():
    checked_in = json.loads(SCHEMA_PATH.read_text())
    fresh = _regenerate()
    assert checked_in == fresh, (
        "schema/outcome_record.v1.schema.json is out of date -- "
        "run `python scripts/generate_outcome_schema.py` and commit the result"
    )


def test_schema_declares_every_required_top_level_field():
    schema = json.loads(SCHEMA_PATH.read_text())
    assert set(schema["required"]) == {
        "schema_version", "channel_id", "channel_display_name", "date",
        "allowlisted", "roster", "generated_at",
    }
    assert set(schema["properties"]) == set(schema["required"]) | {
        "updates", "blockers", "decisions", "questions", "participation",
    }
