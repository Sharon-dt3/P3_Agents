"""Smoke test -- confirms the package imports and the environment is wired correctly.

Deliberately trivial: exists so CI has something real to run from day one
(SPN-01), rather than passing vacuously with zero tests.
"""

import p1


def test_package_imports() -> None:
    assert p1 is not None
