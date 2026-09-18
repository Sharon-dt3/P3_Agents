"""Seed command entry point.

Builds a fresh SQLite database from the committed migrations (SPN-04).
The actual seed fixture data (3 channels, 10 working days, planted
difficulties from source sheet 06 plus CHN-28's additions) is not
regenerated here -- it's deterministic (seed=42) and already committed
under seed/fixtures/, produced once by
`uv run python scripts/generate_seed_fixtures.py`. Re-run that script only
if the fixture generator itself changes.
"""

import logging
import sys
from pathlib import Path

# Ensure `src/` is importable regardless of how this script is invoked --
# works around the unreliable editable-install .pth resolution seen in
# this environment (see DECISION_LOG.md).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from p1.storage.db import init_db

logging.basicConfig(level="INFO")


def main() -> None:
    init_db()
    print(
        "[seed] Database initialised from migrations. Fixture data is committed "
        "under seed/fixtures/ (see scripts/generate_seed_fixtures.py)."
    )


if __name__ == "__main__":
    main()
