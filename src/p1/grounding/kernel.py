"""
Thin re-export shim -- CHN-33: real implementation now lives in
spine.grounding.kernel, moved there verbatim. See DECISION_LOG.md,
2026-09-21 CHN-33 entry.
"""

from __future__ import annotations

from spine.grounding.kernel import (
    FactualLine,
    GroundingFailure,
    GroundingResult,
    MessageLookup,
    ground_with_retry,
    verify_line,
    verify_lines,
)

__all__ = [
    "FactualLine",
    "GroundingFailure",
    "GroundingResult",
    "MessageLookup",
    "ground_with_retry",
    "verify_line",
    "verify_lines",
]
