"""
Wires every currently-known golden case into a registry. This file is
the one place a new capability's golden cases get plugged in -- CHN-11
was the first (GC1, GC2); CHN-12 (GC5, GC10) and later P2/P3 cases each
get their own small registration module and are added to register_all
here, one line per capability. The harness itself (cases.py, runner.py,
results_store.py) never needs to change when this file grows.
"""

from __future__ import annotations

from p1.eval.cases import GoldenCaseRegistry


def register_all(registry: GoldenCaseRegistry) -> None:
    from p1.eval.chn11_cases import register as register_chn11
    from p1.eval.chn12_cases import register as register_chn12

    register_chn11(registry)
    register_chn12(registry)
