"""
Thin re-export shim -- CHN-33: real implementation now lives in
spine.llm.structured, moved there verbatim. See DECISION_LOG.md,
2026-09-21 CHN-33 entry.
"""

from __future__ import annotations

from spine.llm.structured import StructuredOutputError, generate_structured

__all__ = ["StructuredOutputError", "generate_structured"]
