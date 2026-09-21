"""
Thin re-export shim -- CHN-33: real implementation now lives in
spine.llm.gateway (packages/spine/src/spine/llm/gateway.py), moved there
verbatim. This file exists only so existing `p1.llm.gateway` import sites
across the codebase need no changes. See DECISION_LOG.md, 2026-09-21
CHN-33 entry.
"""

from __future__ import annotations

from spine.llm.gateway import (
    DEFAULT_ANTHROPIC_MODEL,
    LLMGateway,
    LLMGatewayError,
    LLMResponse,
)

__all__ = ["DEFAULT_ANTHROPIC_MODEL", "LLMGateway", "LLMGatewayError", "LLMResponse"]
