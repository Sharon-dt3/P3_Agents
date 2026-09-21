"""
Thin re-export shim -- CHN-33: real implementation now lives in
spine.eval.runner, moved there verbatim. See DECISION_LOG.md, 2026-09-21
CHN-33 entry.
"""

from __future__ import annotations

from spine.eval.runner import EvalRunSummary, run_eval

__all__ = ["EvalRunSummary", "run_eval"]
