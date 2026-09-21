"""
Thin re-export shim -- CHN-33: real implementation now lives in
spine.approval.write_guard, moved there verbatim. See DECISION_LOG.md,
2026-09-21 CHN-33 entry.
"""

from __future__ import annotations

from spine.approval.write_guard import WriteRefusedError, guarded_send

__all__ = ["WriteRefusedError", "guarded_send"]
