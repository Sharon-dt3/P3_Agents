"""
Channel config store (CHN-02): loads configuration from committed YAML
files (the system of record), validates it, and mirrors it into SQLite
so the rest of the app has one place to query it. Dataverse is added
later (CHN-25) purely as a human-editable surface on top of this --
never the source of truth.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from p1.config.schema import ChannelConfig
from p1.storage.db import DEFAULT_DB_PATH, get_connection

DEFAULT_CONFIG_DIR = Path("config/channels")


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

    def _load_file(self, path: Path) -> ChannelConfig:
        raw = yaml.safe_load(path.read_text())
        try:
            return ChannelConfig.model_validate(raw)
        except Exception as exc:
            raise ValueError(f"Invalid channel config in {path}: {exc}") from exc

    def sync_to_db(self, db_path: str | Path = DEFAULT_DB_PATH) -> int:
        """Upsert every loaded config into channels + channel_config."""
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
                update_clause = ", ".join(f"{k} = excluded.{k}" for k in values if k != "channel_id")
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
            conn.commit()
            return len(configs)
        finally:
            conn.close()
