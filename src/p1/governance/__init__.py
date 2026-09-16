"""Governance components (CHN-04 and onward): the scope gate, and later
proposal/approval enforcement re-exported from the spine."""

from p1.governance.scope_gate import ScopedTeamsReader, ScopeViolationError

__all__ = ["ScopeViolationError", "ScopedTeamsReader"]
