"""Eval harness entry point (SPN-07).

Runs every registered golden case from one command and writes a
results file naming metric, measured, target and pass/fail -- this
task's own acceptance test.

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

from p1.eval.cases import GoldenCaseRegistry
from p1.eval.registrations import register_all
from p1.eval.runner import run_eval


def _parse_prompt_versions(pairs: list[str]) -> dict[str, str]:
    versions = {}
    for pair in pairs:
        capability, _, version = pair.partition("=")
        if not version:
            raise ValueError(f"--prompt-version must be capability=version, got {pair!r}")
        versions[capability] = version
    return versions


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the golden-case eval harness.")
    parser.add_argument("--model-id", default=None, help="Model ID to tag this run with.")
    parser.add_argument(
        "--prompt-version",
        action="append",
        default=[],
        metavar="capability=version",
        help="Tag this run with a prompt version (repeatable).",
    )
    args = parser.parse_args()

    registry = GoldenCaseRegistry()
    register_all(registry)

    summary = run_eval(
        registry,
        model_id=args.model_id,
        prompt_versions=_parse_prompt_versions(args.prompt_version),
    )

    status = "ALL PASS" if summary.all_passed else "FAILURES PRESENT"
    print(f"\n{len(summary.results)} metric(s) checked -- {status}")
    return 0 if summary.all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())