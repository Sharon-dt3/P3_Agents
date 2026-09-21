"""
Thin re-export shim -- CHN-33: real implementation (the ABC interface and
its data models) now lives in spine.adapters.teams_reader, moved there
verbatim. Concrete implementations (MockTeamsReader, GraphTeamsReader)
stay in P1 -- only the interface moved. See DECISION_LOG.md, 2026-09-21
CHN-33 entry.
"""

from __future__ import annotations

from spine.adapters.teams_reader import (
    DeltaLinkRejectedError,
    DeltaTokenExpiredError,
    MessagePage,
    TeamsChannel,
    TeamsMember,
    TeamsMessage,
    TeamsReader,
)

__all__ = [
    "DeltaLinkRejectedError",
    "DeltaTokenExpiredError",
    "MessagePage",
    "TeamsChannel",
    "TeamsMember",
    "TeamsMessage",
    "TeamsReader",
]
