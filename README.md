# P1 — Teams Channel Intelligence

Reads allowlisted Microsoft Teams channels, tracks who has and hasn't posted an update against a per-channel roster, and publishes daily and weekly digests. Part of the Incubation Pod Three-Agent Delivery Plan (P1 of P1/P2/P3).

**Status:** Week 1, Day 1 (SPN-01 — repo scaffold) in progress.

## Prerequisites

- uv (Python package/project manager): https://docs.astral.sh/uv/
- Python 3.10+ (uv manages this automatically)
- Git

## Quick start

    git clone https://github.com/Sharon-dt3/P3_Agents.git
    cd P3_Agents
    cp .env.example .env   # fill in real values before running against live services
    make install            # uv sync -- installs all dependencies
    make seed                # seeds mock/fixture data (stub for now, see CHN-06/07)
    make run                  # runs the daily job (stub for now, see CHN-17)

Run tests and lint:

    make test
    make lint

## Project structure

    src/p1/             application code (adapters, detection, participation, grounding, approval, publishing, ...)
    tests/unit/         unit tests
    scripts/            entry-point scripts used by the Makefile
    docs/               implementation plan and other project documentation
    .github/workflows/  CI (lint + test on every push)

See docs/P1_IMPLEMENTATION_PLAN.md for the full architecture and day-by-day build plan.

## Status

| Capability | Status |
|---|---|
| SPN-01 Repo scaffold | In progress |

(This table gets filled in from the actual code as capabilities land -- see CHN-30.)

## AI assistance

Portions of this repository's scaffolding, code, and documentation were written with assistance from Claude (Anthropic), used interactively during development. Every file's purpose is understood and can be explained by the author.
