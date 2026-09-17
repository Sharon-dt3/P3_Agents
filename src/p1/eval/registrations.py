"""
Wires every currently-known golden case into a registry. This file is
the one place a new capability's golden cases get plugged in --
CHN-11 (GC1, GC2), CHN-12 (GC5, GC10), and later P2/P3 cases each get
their own small registration module and are added to register_all
here, one line per capability. The harness itself (cases.py, runner.py,
results_store.py) never needs to change when this file grows.

Nothing is registered yet -- CHN-11 is the first task that adds a real
golden case. Running scripts/run_eval.py today is still a legitimate,
useful check of the harness mechanism itself: zero cases, zero
failures, a well-formed (empty) run recorded.
"""

from __future__ import annotations

from p1.eval.cases import GoldenCaseRegistry


def register_all(registry: GoldenCaseRegistry) -> None:
    """CHN-11 adds its cases here once its own module exists, e.g.:

        from p1.eval.chn11_cases import register
        register(registry)
    """
    return