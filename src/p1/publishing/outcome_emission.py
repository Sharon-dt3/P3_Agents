"""Writing the channel's outcome record after each daily digest (opt-in).

CHN-26 built the outcome record (schema/outcome_record.v1.schema.json: "THE CONTRACT THE P2 PM AGENT CONSUMES", one JSON
file per channel per day) but nothing in P1's running jobs ever wrote one, so P2's commitment tracking had no live input.
This is the missing call, and it is built to change nothing else about how P1 works:

- OFF unless P1_WRITE_OUTCOME_RECORDS=1 (exactly "1"). Unset, no file is written and nothing differs.
- It writes a file from the DailySummaryResult the digest job has ALREADY built (the same grounded lines): no model call,
  no Teams call, nothing posted, nothing proposed or approved.
- It never fails the job: if the record cannot be built or written, the failure is logged and the digest goes ahead.
- It is not gated on the digest's own approval (CHN-26's decision, DECISION_LOG.md): a digest awaiting its first approval
  still gets its record, because "what happened in the channel today" is not a decision about a Teams post.

Where: P1_OUTCOMES_DIR, else `outcomes/` in the P1 repo (git-ignored: it holds real channel content), which is where P2's
`PM_OUTCOMES_DIR` looks by default. Each file is overwritten by the same day's next run, so re-running a day is safe.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path

from p1.config.schema import ChannelConfig
from p1.contracts.outcome_record import build_outcome_record, write_outcome
from p1.reporting.daily_summary import DailySummaryResult

logger = logging.getLogger(__name__)

ENV_ENABLED = "P1_WRITE_OUTCOME_RECORDS"
ENV_DIR = "P1_OUTCOMES_DIR"
_REPO_ROOT = Path(__file__).resolve().parents[3]  # src/p1/publishing/outcome_emission.py -> the repo root


def enabled(env: Mapping[str, str] | None = None) -> bool:
    return (os.environ if env is None else env).get(ENV_ENABLED, "") == "1"


def outcomes_dir(env: Mapping[str, str] | None = None) -> Path:
    explicit = (os.environ if env is None else env).get(ENV_DIR)
    return Path(explicit) if explicit else _REPO_ROOT / "outcomes"


def emit_outcome_record(result: DailySummaryResult, config: ChannelConfig, *, env: Mapping[str, str] | None = None) -> Path | None:
    """The path written, or None if switched off or if anything went wrong (logged). Never raises."""
    if not enabled(env):
        return None
    try:
        return write_outcome(build_outcome_record(result, config), output_dir=outcomes_dir(env))
    except Exception as exc:  # noqa: BLE001 - the digest must never be held up by a data file
        logger.warning("could not write the outcome record for channel=%s date=%s: %s: %s",
                       getattr(result, "channel_id", "?"), getattr(result, "date", "?"), type(exc).__name__, exc)
        return None
