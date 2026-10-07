"""An estate-wide per-person per-day nudge cap, shared with the other agents (P2) -- opt-in.

P1's own cap (config.nudge_cap_per_day) is per person per CHANNEL and counts only P1's own nudges table. P2 keeps a
nudges table of the same shape (member_id, date, sent_at) and its own cap, which can see P1's ledger; but P1 could not
see P2's, so a person P2 reminded in the morning could still be nudged by P1 in the evening. Two agents each politely
chasing the same person is how an agent estate becomes a nuisance.

This is the missing half. Switch it on with two environment variables (deployment settings, not per-channel config):

  P1_SHARED_NUDGE_CAP_PER_DAY   whole number of nudges one person may receive in a day, from all agents together
  P1_PEER_NUDGE_LEDGERS         comma-separated paths of the other agents' SQLite databases (P2's data/pm.db)

Left unset, none of this runs and P1 behaves exactly as it always has.

A person's count for a day is their DELIVERED nudges (rows with a sent_at: a pending or rejected one never reached
them): P1's own, in every channel, plus each peer ledger's. Peer ledgers are only ever opened read-only. A person is not
always the same id in both systems, so the peer count includes every id they appear under there: their own, and those
of peer people with the same display name (exact, ignoring case and spacing). Two peer people sharing a name are both
counted: not knowing which is which, the safe answer is to count both.

It fails closed: a peer ledger that is listed and cannot be read (missing, locked, not a ledger) means NOBODY is nudged:
not knowing whether someone was already chased is a reason to wait, not to send. "A day" is the date P1's nudge job is
running for (its channel's local date); the peer stores its own project's local date.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from p1.storage.db import get_connection

ENV_CAP = "P1_SHARED_NUDGE_CAP_PER_DAY"
ENV_PEERS = "P1_PEER_NUDGE_LEDGERS"
_PEOPLE_TABLES = ("assignees", "members")  # where a peer names its people


class SharedCapUnavailableError(RuntimeError):
    """A peer ledger is listed but cannot be read: the cap cannot be checked, so nothing is sent."""


@dataclass(frozen=True)
class SharedCapReading:
    member_id: str
    day: str
    own: int
    peers: int
    cap: int

    @property
    def total(self) -> int:
        return self.own + self.peers

    @property
    def reached(self) -> bool:
        return self.total >= self.cap

    def describe(self) -> str:
        return (f"{self.member_id} has had {self.total} nudge(s) on {self.day} "
                f"({self.own} from P1, {self.peers} from another agent); the shared cap is {self.cap}")


class SharedNudgeCap:
    def __init__(self, *, db_path: str | Path, cap: int, peer_paths: list[Path] | list[str]) -> None:
        self._db_path = db_path
        self.cap = cap
        self._peers = [Path(p) for p in peer_paths]

    def _own(self, member_id: str, day: str) -> tuple[int, str | None]:
        conn = get_connection(self._db_path)
        try:
            count = conn.execute("SELECT COUNT(*) AS n FROM nudges WHERE member_id = ? AND date = ? AND sent_at IS NOT NULL",
                                 (member_id, day)).fetchone()["n"]
            row = conn.execute("SELECT display_name FROM members WHERE id = ?", (member_id,)).fetchone()
        finally:
            conn.close()
        return count, (row["display_name"] if row else None)

    def _peer(self, path: Path, member_id: str, name: str | None, day: str) -> int:
        if not path.exists():
            raise SharedCapUnavailableError(f"the nudge ledger {path} is listed but does not exist")
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
            try:
                ids = {member_id}
                if name:
                    for table in _PEOPLE_TABLES:
                        try:
                            ids |= {r[0] for r in conn.execute(
                                f"SELECT id FROM {table} WHERE lower(trim(display_name)) = lower(trim(?))", (name,))}
                        except sqlite3.OperationalError as exc:
                            if "no such table" not in str(exc):
                                raise
                ordered = sorted(ids)
                return conn.execute(
                    f"SELECT COUNT(*) FROM nudges WHERE member_id IN ({','.join('?' * len(ordered))}) AND date = ? AND sent_at IS NOT NULL",
                    (*ordered, day)).fetchone()[0]
            finally:
                conn.close()
        except sqlite3.Error as exc:
            raise SharedCapUnavailableError(f"the nudge ledger {path} could not be read ({type(exc).__name__}: {exc})") from exc

    def reading(self, member_id: str, day: str) -> SharedCapReading:
        """Raises SharedCapUnavailableError if any listed peer ledger cannot be read."""
        own, name = self._own(member_id, day)
        peers = sum(self._peer(path, member_id, name, day) for path in self._peers)
        return SharedCapReading(member_id, day, own, peers, self.cap)


def shared_cap_from_environment(db_path: str | Path, env: Mapping[str, str] | None = None) -> SharedNudgeCap | None:
    """None when the shared cap is not switched on. A set-but-bad value is an error, never a quiet default."""
    env = os.environ if env is None else env
    raw = (env.get(ENV_CAP) or "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise ValueError(f"{ENV_CAP} must be a whole number of nudges per person per day, not {raw!r}")
    peers = [p.strip() for p in (env.get(ENV_PEERS) or "").split(",") if p.strip()]
    return SharedNudgeCap(db_path=db_path, cap=int(raw), peer_paths=peers)
