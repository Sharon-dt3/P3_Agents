"""
LogPublisher (CHN-22): the mock behind TeamsPublisher, with zero
network egress.

"Every nudge, escalation and digest is a row you can show on camera
before anything is ever sent" -- this row's own acceptance test, and
the same phrase SPN-09's write_guard.py already quotes as CHN-22's
rationale, ahead of this class actually existing. Every call to
post_channel_message/post_direct_message appends exactly one JSON
object, on its own line, to an append-only file -- never held in
memory only, never overwritten -- so the file itself is the "row you
can show on camera": open it during a demo and every outbound message
this run ever produced is sitting there, in the order it was sent,
independent of whatever the caller does with this method's return
value.

This is the adapter every test, eval and demo in this repo actually
exercises. The real Power Automate implementation
(teams_publisher_power_automate.py) is written and ready to wire in,
but nothing in the scored path depends on it -- see that module's own
docstring.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from p1.adapters.teams_publisher import TeamsPublisher

DEFAULT_LOG_PATH = Path("data/outbound_log.jsonl")

CHANNEL_POST = "channel_post"
DIRECT_MESSAGE = "direct_message"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LogPublisher(TeamsPublisher):
    def __init__(self, log_path: str | Path = DEFAULT_LOG_PATH) -> None:
        self._log_path = Path(log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def post_channel_message(self, channel_id: str, content: str) -> dict:
        return self._log(action_type=CHANNEL_POST, target=channel_id, content=content)

    def post_direct_message(self, member_id: str, content: str) -> dict:
        return self._log(action_type=DIRECT_MESSAGE, target=member_id, content=content)

    def _log(self, *, action_type: str, target: str, content: str) -> dict:
        record = {
            "logged_at": _now_iso(),
            "action_type": action_type,
            "target": target,
            "content": content,
        }
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return {"ok": True, "mode": "mock", **record}

    def read_log(self) -> list[dict]:
        """Reads back every row this instance's log path has ever
        recorded, in order -- the "inspectable" half of "inspectable
        JSONL log." Not part of the TeamsPublisher interface (it's
        mock-only bookkeeping for demos and tests), and reads whatever
        is on disk right now, including rows written by an earlier
        LogPublisher instance pointed at the same path."""
        if not self._log_path.exists():
            return []
        with self._log_path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
