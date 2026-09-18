"""
CHN-27's own acceptance test, the part not already covered by
runner.py's own tests: a plain, flag-less `run_eval.py` invocation
tags its committed run with a real model id and every prompt
capability's real current version, by default -- not only when a
caller remembers the right flags.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import run_eval as run_eval_script

from p1.llm.gateway import DEFAULT_ANTHROPIC_MODEL
from p1.prompts import PromptRegistry


def test_resolve_model_id_defaults_to_the_real_gateway_default():
    assert run_eval_script.resolve_model_id(None) == DEFAULT_ANTHROPIC_MODEL


def test_resolve_model_id_prefers_an_explicit_value():
    assert run_eval_script.resolve_model_id("some-other-model") == "some-other-model"


def test_resolve_prompt_versions_covers_every_real_checked_in_capability():
    registry = PromptRegistry()
    resolved = run_eval_script.resolve_prompt_versions({}, registry=registry)

    real_capabilities = registry.list_capabilities()
    assert real_capabilities, "expected at least one real prompt capability under prompts/"
    assert set(resolved) == set(real_capabilities)
    for capability in real_capabilities:
        assert resolved[capability] == registry.get(capability).version


def test_resolve_prompt_versions_lets_an_explicit_override_win():
    registry = PromptRegistry()
    a_real_capability = registry.list_capabilities()[0]

    resolved = run_eval_script.resolve_prompt_versions(
        {a_real_capability: "v999-pinned-for-a-repro"}, registry=registry,
    )

    assert resolved[a_real_capability] == "v999-pinned-for-a-repro"


def test_resolve_prompt_versions_does_not_silently_drop_an_unknown_capability_override(tmp_path):
    """An override for a capability that doesn't exist under prompts/ is
    still recorded, not silently dropped -- resolve_prompt_versions()
    never second-guesses what the caller explicitly asked to pin."""
    empty_registry = PromptRegistry(prompts_dir=tmp_path)

    resolved = run_eval_script.resolve_prompt_versions(
        {"not_a_real_capability": "v1"}, registry=empty_registry,
    )

    assert resolved == {"not_a_real_capability": "v1"}
