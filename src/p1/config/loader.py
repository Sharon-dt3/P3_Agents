"""
Channel config store (CHN-02, CHN-25): loads configuration from
committed YAML files (the system of record for every field), validates
it, and mirrors it into SQLite so the rest of the app has one place to
query it.

CHN-25 adds the human-editable surface this module's own docstring
anticipated: get_effective_config() is the live read path (SQLite, not
the YAML files) a running job or the approval service should use to
pick up a channel owner's changes without a deploy, and
update_channel_config() is the one write path for exactly the three
fields this row names as theirs to maintain -- roster, the update
window, and the exceptions list. Every other field (timezone, digest
times, nudge_cap_per_day, ...) stays committed-YAML-only, changed only
by a deploy -- see DECISION_LOG.md for why the surface is deliberately
narrower than the whole ChannelConfig. Both the Copilot Studio
connector (src/p1/adapters/copilot_studio_connector.py) and the
Streamlit fallback (app/approval_dashboard.py) call
update_channel_config() directly and identically; neither one ever
touches the channel_config table itself.

2026-09-23: sync_to_db() no longer resets those owner-editable fields
for a channel that already has a row. It used to, and run_daily.py plus
every live runner call sync_to_db() on every run, so a channel owner's
roster/window/exceptions edit only lasted until the next job and then
silently reverted to YAML (the 2026-09-23 06:09 sync did exactly this
to all seven live rows). YAML now seeds those fields for a NEW channel
only; after that the live DB row (fed by the two surfaces above and,
once the table exists, scripts/sync_from_dataverse.py) owns them.
Every other field is still committed-YAML-only and still re-applied on
every sync. sync_to_db(reset_owner_fields=True) is the explicit,
audited way to force YAML to win -- see DECISION_LOG.md.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from p1.config.schema import ChannelConfig, ExceptionEntry
from p1.storage.db import DEFAULT_DB_PATH, get_connection

DEFAULT_CONFIG_DIR = Path("config/channels")

# The fields update_channel_config() lets a channel owner change without
# a deploy. sync_to_db() only seeds these; it never overwrites a live
# value unless reset_owner_fields=True.
OWNER_EDITABLE_FIELDS = ("roster", "update_window_start", "update_window_end", "exceptions")


class ChannelConfigStore:
    def __init__(self, config_dir: str | Path = DEFAULT_CONFIG_DIR):
        self.config_dir = Path(config_dir)

    def list_configured_channels(self) -> list[ChannelConfig]:
        """Load every channel config file, in filename order. An invalid
        file raises -- it is never silently skipped or defaulted."""
        return [self._load_file(path) for path in sorted(self.config_dir.glob("*.yaml"))]

    def list_allowlisted_channels(self) -> list[str]:
        """Channel IDs whose config marks them allowlisted=True. This is
        the explicit allowlist the scope gate (CHN-04) enforces against --
        a channel merely having a config file is not enough on its own,
        it must also be marked allowlisted."""
        return [c.channel_id for c in self.list_configured_channels() if c.allowlisted]

    def get_channel_config(self, channel_id: str) -> ChannelConfig:
        for config in self.list_configured_channels():
            if config.channel_id == channel_id:
                return config
        raise KeyError(f"No configuration found for channel_id={channel_id!r}")

    def version(self) -> str:
        """A fingerprint of the whole store's current content, for cheap
        change-detection (e.g. deciding whether to resync)."""
        digest = hashlib.sha256()
        for path in sorted(self.config_dir.glob("*.yaml")):
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def get_effective_config(self, channel_id: str, *, db_path: str | Path = DEFAULT_DB_PATH) -> ChannelConfig:
        """CHN-25's live read path: what a running job, the approval
        service, or either of its two surfaces should treat as this
        channel's CURRENT config, reflecting any edit made through
        update_channel_config() since the last deploy -- as opposed to
        get_channel_config()/list_configured_channels(), which read
        only the committed YAML, this channel's bootstrap baseline.
        Requires sync_to_db() to have run for this channel at least
        once (the normal deploy-time bootstrap); a channel with no row
        here raises the same way get_channel_config() raises for an
        unknown channel_id, rather than silently falling back to file
        content that may since have drifted from the DB."""
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT cc.*, c.display_name, c.allowlisted FROM channel_config cc "
                "JOIN channels c ON c.id = cc.channel_id WHERE cc.channel_id = ?",
                (channel_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise KeyError(
                f"No configuration found for channel_id={channel_id!r} in {db_path!r} "
                "(has sync_to_db() been run for it?)"
            )
        return ChannelConfig.model_validate(
            {
                "channel_id": channel_id,
                "display_name": row["display_name"],
                "allowlisted": bool(row["allowlisted"]),
                "roster": json.loads(row["roster"]),
                "update_window_start": row["update_window_start"],
                "update_window_end": row["update_window_end"],
                "timezone": row["timezone"],
                "working_days": json.loads(row["working_days"]),
                "non_working_dates": json.loads(row["non_working_dates"]),
                "length_floor": row["length_floor"],
                "count_thread_replies": bool(row["count_thread_replies"]),
                "ignore_bots": bool(row["ignore_bots"]),
                "daily_digest_time": row["daily_digest_time"],
                "weekly_digest_day": row["weekly_digest_day"],
                "weekly_digest_time": row["weekly_digest_time"],
                "nudge_enabled": bool(row["nudge_enabled"]),
                "nudge_cap_per_day": row["nudge_cap_per_day"],
                "escalation_threshold_days": row["escalation_threshold_days"],
                "channel_owner_id": row["channel_owner_id"],
                "exceptions": json.loads(row["exceptions"]),
                "version": row["version"],
            }
        )

    def update_channel_config(
        self,
        channel_id: str,
        *,
        roster: list[str] | None = None,
        update_window_start=None,
        update_window_end=None,
        exceptions: list[ExceptionEntry] | list[dict] | None = None,
        updated_by: str,
        db_path: str | Path = DEFAULT_DB_PATH,
    ) -> ChannelConfig:
        """CHN-25's one write path for the three fields a channel owner
        is meant to maintain without a deploy. Reads the CURRENT
        effective config, applies only the fields actually given,
        re-validates the WHOLE resulting config through ChannelConfig
        itself -- so an invalid window order or an empty roster is
        rejected outright, never silently written -- then writes it
        back (bumping version) and appends exactly one `audit` row
        recording who changed what and the before/after values. This is
        the only function either surface (Copilot Studio's connector or
        the Streamlit fallback) is allowed to call to change config;
        neither one ever writes to channel_config directly, which is
        what makes a change made from either one indistinguishable in
        the audit trail from the other."""
        current = self.get_effective_config(channel_id, db_path=db_path)
        updates = current.model_dump()
        changes: dict[str, dict[str, object]] = {}

        if roster is not None:
            changes["roster"] = {"old": current.roster, "new": roster}
            updates["roster"] = roster
        if update_window_start is not None:
            changes["update_window_start"] = {
                "old": current.update_window_start.isoformat(), "new": update_window_start.isoformat(),
            }
            updates["update_window_start"] = update_window_start
        if update_window_end is not None:
            changes["update_window_end"] = {
                "old": current.update_window_end.isoformat(), "new": update_window_end.isoformat(),
            }
            updates["update_window_end"] = update_window_end
        if exceptions is not None:
            normalized = [
                e if isinstance(e, ExceptionEntry) else ExceptionEntry.model_validate(e) for e in exceptions
            ]
            changes["exceptions"] = {
                "old": [e.model_dump() for e in current.exceptions],
                "new": [e.model_dump() for e in normalized],
            }
            updates["exceptions"] = normalized

        if not changes:
            return current  # nothing given to change -- no write, no audit row

        updates["version"] = current.version + 1
        new_config = ChannelConfig.model_validate(updates)

        conn = get_connection(db_path)
        try:
            conn.execute(
                """
                UPDATE channel_config SET
                    roster = ?, update_window_start = ?, update_window_end = ?,
                    exceptions = ?, version = ?, updated_at = datetime('now')
                WHERE channel_id = ?
                """,
                (
                    json.dumps(new_config.roster),
                    new_config.update_window_start.isoformat(),
                    new_config.update_window_end.isoformat(),
                    json.dumps([e.model_dump() for e in new_config.exceptions]),
                    new_config.version,
                    channel_id,
                ),
            )
            conn.execute(
                "INSERT INTO audit (actor, action, entity_type, entity_id, details) VALUES (?, ?, ?, ?, ?)",
                (updated_by, "channel_config.updated", "channel_config", channel_id, json.dumps(changes)),
            )
            conn.commit()
        finally:
            conn.close()

        return new_config

    def _load_file(self, path: Path) -> ChannelConfig:
        raw = yaml.safe_load(path.read_text())
        try:
            return ChannelConfig.model_validate(raw)
        except Exception as exc:
            raise ValueError(f"Invalid channel config in {path}: {exc}") from exc

    def sync_to_db(self, db_path: str | Path = DEFAULT_DB_PATH, *, reset_owner_fields: bool = False) -> int:
        """Upsert every loaded config into channels + channel_config.

        A new channel gets every field from YAML. An existing channel
        gets every YAML-only field re-applied, but keeps its live
        OWNER_EDITABLE_FIELDS and version untouched -- unless
        reset_owner_fields=True, which overwrites them from YAML, bumps
        version, and writes one audit row per channel so the reset is
        as visible as the edit it discarded."""
        configs = self.list_configured_channels()
        conn = get_connection(db_path)
        try:
            for config in configs:
                conn.execute(
                    """
                    INSERT INTO channels (id, display_name, allowlisted)
                    VALUES (:id, :display_name, :allowlisted)
                    ON CONFLICT(id) DO UPDATE SET
                        display_name = excluded.display_name,
                        allowlisted = excluded.allowlisted
                    """,
                    {
                        "id": config.channel_id,
                        "display_name": config.display_name,
                        "allowlisted": int(config.allowlisted),
                    },
                )

                values = {
                    "channel_id": config.channel_id,
                    "roster": json.dumps(config.roster),
                    "update_window_start": config.update_window_start.isoformat(),
                    "update_window_end": config.update_window_end.isoformat(),
                    "timezone": config.timezone,
                    "working_days": json.dumps(config.working_days),
                    "non_working_dates": json.dumps([d.isoformat() for d in config.non_working_dates]),
                    "length_floor": config.length_floor,
                    "count_thread_replies": int(config.count_thread_replies),
                    "ignore_bots": int(config.ignore_bots),
                    "daily_digest_time": config.daily_digest_time.isoformat(),
                    "weekly_digest_day": config.weekly_digest_day,
                    "weekly_digest_time": config.weekly_digest_time.isoformat(),
                    "nudge_enabled": int(config.nudge_enabled),
                    "nudge_cap_per_day": config.nudge_cap_per_day,
                    "escalation_threshold_days": config.escalation_threshold_days,
                    "channel_owner_id": config.channel_owner_id,
                    "exceptions": json.dumps([e.model_dump() for e in config.exceptions]),
                    "version": config.version,
                }
                columns = ", ".join(values)
                placeholders = ", ".join(f":{k}" for k in values)
                protected = {"channel_id", "version"}
                if not reset_owner_fields:
                    protected.update(OWNER_EDITABLE_FIELDS)
                update_clause = ", ".join(f"{k} = excluded.{k}" for k in values if k not in protected)
                if reset_owner_fields:
                    update_clause += ", version = channel_config.version + 1"
                existed = conn.execute(
                    "SELECT 1 FROM channel_config WHERE channel_id = ?", (config.channel_id,)
                ).fetchone() is not None
                conn.execute(
                    f"""
                    INSERT INTO channel_config ({columns})
                    VALUES ({placeholders})
                    ON CONFLICT(channel_id) DO UPDATE SET
                        {update_clause},
                        updated_at = datetime('now')
                    """,
                    values,
                )
                if reset_owner_fields and existed:
                    conn.execute(
                        "INSERT INTO audit (actor, action, entity_type, entity_id, details) VALUES (?, ?, ?, ?, ?)",
                        (
                            "sync_to_db",
                            "channel_config.reset_from_yaml",
                            "channel_config",
                            config.channel_id,
                            json.dumps({"fields": list(OWNER_EDITABLE_FIELDS)}),
                        ),
                    )
            conn.commit()
            return len(configs)
        finally:
            conn.close()
