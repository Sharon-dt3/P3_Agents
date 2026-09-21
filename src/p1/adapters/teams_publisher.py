"""
Thin re-export shim -- CHN-33: real implementation (the ABC interface) now
lives in spine.adapters.teams_publisher, moved there verbatim. Concrete
implementations (LogPublisher, PowerAutomateTeamsPublisher) stay in P1 --
only the interface moved. See DECISION_LOG.md, 2026-09-21 CHN-33 entry.
"""

from __future__ import annotations

from spine.adapters.teams_publisher import TeamsPublisher

__all__ = ["TeamsPublisher"]
