"""Seed command entry point.

Currently: builds a fresh SQLite database from the committed migrations
(SPN-04). Fixture data itself lands in CHN-06/CHN-07.
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
    print("[seed] Database initialised from migrations. Fixture data not yet implemented -- see CHN-06/CHN-07.")


if __name__ == "__main__":
    main()
