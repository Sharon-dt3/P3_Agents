"""
Thin re-export shim -- CHN-33: real implementation now lives in
spine.prompts.registry, moved there verbatim. See DECISION_LOG.md,
2026-09-21 CHN-33 entry.
"""

from __future__ import annotations

from spine.prompts.registry import (
    DEFAULT_PROMPTS_DIR,
    Prompt,
    PromptNotFoundError,
    PromptRegistry,
)

__all__ = ["DEFAULT_PROMPTS_DIR", "Prompt", "PromptNotFoundError", "PromptRegistry"]
