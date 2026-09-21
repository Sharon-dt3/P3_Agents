"""
Thin re-export shim -- CHN-33: real implementation now lives in
spine.approval.proposals, moved there verbatim. See DECISION_LOG.md,
2026-09-21 CHN-33 entry.
"""

from __future__ import annotations

from spine.approval.proposals import (
    APPLIED,
    APPROVED,
    PENDING,
    REJECTED,
    IllegalTransitionError,
    Proposal,
    ProposalNotFoundError,
    ProposalStore,
)

__all__ = [
    "APPLIED",
    "APPROVED",
    "PENDING",
    "REJECTED",
    "IllegalTransitionError",
    "Proposal",
    "ProposalNotFoundError",
    "ProposalStore",
]
