"""
Thin re-export shim -- CHN-33: real implementation now lives in
spine.eval.results_store, moved there verbatim. See DECISION_LOG.md,
2026-09-21 CHN-33 entry.
"""

from __future__ import annotations

from spine.eval.results_store import DEFAULT_RESULTS_PATH, append_run

__all__ = ["DEFAULT_RESULTS_PATH", "append_run"]
