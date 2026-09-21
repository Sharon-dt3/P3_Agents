"""
Thin re-export shim -- CHN-33: real implementation now lives in
spine.eval.cases, moved there verbatim. See DECISION_LOG.md, 2026-09-21
CHN-33 entry.
"""

from __future__ import annotations

from spine.eval.cases import (
    GoldenCase,
    GoldenCaseRegistry,
    MetricResult,
    at_least,
    at_most,
    equals,
)

__all__ = [
    "GoldenCase",
    "GoldenCaseRegistry",
    "MetricResult",
    "at_least",
    "at_most",
    "equals",
]
