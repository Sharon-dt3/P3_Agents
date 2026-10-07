"""Keep the live ``.env`` out of the unit tests.

Importing ``p1.api.copilot_studio_api`` calls ``load_dotenv``, so a full test
run inherits whatever the operator has switched on for the live runners. The
opt-in settings below change what the code does (a shared nudge cap refuses a
second nudge; outcome emission writes files into the repository), so every test
starts with them cleared. A test that needs one sets it itself.
"""

from __future__ import annotations

import pytest

_OPT_IN_SETTINGS = (
    "P1_SHARED_NUDGE_CAP_PER_DAY",
    "P1_PEER_NUDGE_LEDGERS",
    "P1_WRITE_OUTCOME_RECORDS",
    "P1_OUTCOMES_DIR",
)


@pytest.fixture(autouse=True)
def _no_opt_in_settings_from_the_live_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _OPT_IN_SETTINGS:
        monkeypatch.delenv(name, raising=False)
