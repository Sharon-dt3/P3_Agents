"""Eval harness entry point (SPN-07, CHN-27).

Runs every registered golden case from one command and writes a
results file naming metric, measured, target and pass/fail -- this
task's own acceptance test. CHN-27 adds the second half of that row's
own acceptance test: every committed run is tagged with a timestamp
(runner.py's own run_at, always real), a model id, and every prompt
capability's actual current version -- by DEFAULT, not only when the
caller remembers to pass the right flags.

resolve_model_id()/resolve_prompt_versions() are what make that
default real rather than aspirational: with no flags at all, a plain
`uv run python scripts/run_eval.py` tags its run with
p1.llm.gateway.DEFAULT_ANTHROPIC_MODEL (the same constant this
programme's real LLMGateway defaults to -- never a second, separately
maintained guess at what model this system actually runs against) and
with PromptRegistry().list_capabilities()'s own current version for
EVERY prompt capability checked into prompts/, not just whichever ones
a caller happened to name. --model-id/--prompt-version still override
those defaults explicitly, for reproducing a past run against an older
prompt version deliberately (see PromptRegistry.get()'s own version=
parameter).

Usage:
    uv run python scripts/run_eval.py
    uv run python scripts/run_eval.py --model-id claude-sonnet-4-20250514 \
        --prompt-version chn09_classify_message=v1
"""

import argparse
import sys
from pathlib import Path

# Ensure `src/` is importable regardless of how this script is invoked --
# works around the unreliable editable-install .pth resolution seen in
# this environment (see DECISION_LOG.md).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from p1.eval.cases import GoldenCaseRegistry
from p1.eval.registrations import register_all
from p1.eval.runner import run_eval
from p1.llm.gateway import DEFAULT_ANTHROPIC_MODEL
from p1.prompts import PromptRegistry


def _parse_prompt_versions(pairs: list[str]) -> dict[str, str]:
    versions = {}
    for pair in pairs:
        capability, _, version = pair.partition("=")
        if not version:
            raise ValueError(f"--prompt-version must be capability=version, got {pair!r}")
        versions[capability] = version
    return versions


def resolve_model_id(explicit: str | None) -> str:
    """An explicit --model-id always wins; otherwise this run is tagged
    with the same DEFAULT_ANTHROPIC_MODEL this programme's real
    LLMGateway defaults to -- a plain, flag-less run is still tagged
    with a real model id, never None."""
    return explicit or DEFAULT_ANTHROPIC_MODEL


def resolve_prompt_versions(
    explicit: dict[str, str], *, registry: PromptRegistry | None = None,
) -> dict[str, str]:
    """Every prompt capability currently checked into prompts/, tagged
    with its own current version (PromptRegistry.get()'s own "highest
    version by default" rule) -- then overridden, capability by
    capability, by whatever --prompt-version flags were actually given.
    A capability this run never touches is still recorded (its prompt
    file couldn't have drifted since the last run if it wasn't used,
    but the committed record is honest about what version it WOULD have
    used, which is exactly what a later "why did GC3's numbers change"
    investigation needs)."""
    registry = registry or PromptRegistry()
    resolved = {
        capability: registry.get(capability).version
        for capability in registry.list_capabilities()
    }
    resolved.update(explicit)
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the golden-case eval harness.")
    parser.add_argument(
        "--model-id", default=None,
        help=f"Model ID to tag this run with (default: {DEFAULT_ANTHROPIC_MODEL}).",
    )
    parser.add_argument(
        "--prompt-version",
        action="append",
        default=[],
        metavar="capability=version",
        help="Override one capability's recorded prompt version (repeatable); every other "
             "capability is recorded at its current checked-in version automatically.",
    )
    args = parser.parse_args()

    registry = GoldenCaseRegistry()
    register_all(registry)

    model_id = resolve_model_id(args.model_id)
    prompt_versions = resolve_prompt_versions(_parse_prompt_versions(args.prompt_version))

    print(f"model_id={model_id} prompt_versions={prompt_versions}\n")

    summary = run_eval(registry, model_id=model_id, prompt_versions=prompt_versions)

    status = "ALL PASS" if summary.all_passed else "FAILURES PRESENT"
    print(f"\n{len(summary.results)} metric(s) checked -- {status}")
    return 0 if summary.all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
