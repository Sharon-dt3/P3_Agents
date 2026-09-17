"""Tests for the SPN-07 eval harness: golden-case registry, metric
result formatting, the runner's printing/persistence behaviour, and the
CLI's --prompt-version parsing. Uses synthetic golden cases only --
CHN-11 owns the first real ones.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from run_eval import _parse_prompt_versions

from p1.eval.cases import (
    GoldenCase,
    GoldenCaseRegistry,
    MetricResult,
    at_least,
    at_most,
    equals,
)
from p1.eval.runner import run_eval

# --- MetricResult -----------------------------------------------------


def test_metric_result_format_line_pass():
    result = MetricResult(
        metric_id="GC1",
        name="detection precision",
        measured=0.93,
        target=0.9,
        comparator_name="at_least",
        passed=True,
    )
    assert result.format_line() == (
        "GC1 detection precision: measured=0.93 target[at_least]=0.9 PASS"
    )


def test_metric_result_format_line_fail_with_detail():
    result = MetricResult(
        metric_id="GC2",
        name="non-responder set match",
        measured=frozenset({"a", "b"}),
        target=frozenset({"a"}),
        comparator_name="equals",
        passed=False,
        detail="extra: {'b'}",
    )
    line = result.format_line()
    assert line.startswith("GC2 non-responder set match: measured=")
    assert "FAIL" in line
    assert "(extra: {'b'})" in line


def test_comparators():
    assert at_least(0.9, 0.9) is True
    assert at_least(0.89, 0.9) is False
    assert at_most(0.1, 0.1) is True
    assert at_most(0.11, 0.1) is False
    assert equals({"a"}, {"a"}) is True
    assert equals({"a"}, {"b"}) is False


# --- GoldenCaseRegistry -------------------------------------------------


def _case(case_id: str, measured: float = 1.0, target: float = 1.0) -> GoldenCase:
    def measure_fn() -> list[MetricResult]:
        return [
            MetricResult(
                metric_id=case_id,
                name=f"{case_id} metric",
                measured=measured,
                target=target,
                comparator_name="at_least",
                passed=measured >= target,
            )
        ]

    return GoldenCase(case_id=case_id, description=f"synthetic case {case_id}", measure_fn=measure_fn)


def test_registry_register_and_get():
    registry = GoldenCaseRegistry()
    registry.register(_case("ZC1"))
    got = registry.get("ZC1")
    assert got.case_id == "ZC1"


def test_registry_rejects_duplicate_id():
    registry = GoldenCaseRegistry()
    registry.register(_case("ZC1"))
    with pytest.raises(ValueError, match="duplicate golden case id"):
        registry.register(_case("ZC1"))


def test_registry_get_missing_raises_keyerror():
    registry = GoldenCaseRegistry()
    with pytest.raises(KeyError, match="no golden case registered"):
        registry.get("does-not-exist")


def test_registry_all_cases_sorted_by_id_not_registration_order():
    registry = GoldenCaseRegistry()
    registry.register(_case("ZC9"))
    registry.register(_case("ZC1"))
    registry.register(_case("ZC5"))
    assert [c.case_id for c in registry.all_cases()] == ["ZC1", "ZC5", "ZC9"]


def test_registry_is_independent_per_instance():
    # Deliberately instantiable, not a singleton -- two registries never
    # share state.
    r1 = GoldenCaseRegistry()
    r2 = GoldenCaseRegistry()
    r1.register(_case("ZC1"))
    assert r2.all_cases() == []


# --- run_eval ------------------------------------------------------------


def test_run_eval_prints_one_line_per_metric(tmp_path):
    registry = GoldenCaseRegistry()
    registry.register(_case("ZC1", measured=0.95, target=0.9))
    registry.register(_case("ZC2", measured=0.5, target=0.9))

    out = io.StringIO()
    summary = run_eval(
        registry,
        model_id="test-model",
        prompt_versions={"chn09_classify_message": "v1"},
        results_path=tmp_path / "results.jsonl",
        out=out,
    )

    printed = out.getvalue().splitlines()
    assert len(printed) == 2
    assert printed[0].startswith("ZC1 ")
    assert printed[1].startswith("ZC2 ")
    assert summary.all_passed is False
    assert [r.passed for r in summary.results] == [True, False]


def test_run_eval_all_passed_true_only_when_every_metric_passes(tmp_path):
    registry = GoldenCaseRegistry()
    registry.register(_case("ZC1", measured=1.0, target=1.0))
    registry.register(_case("ZC2", measured=1.0, target=1.0))

    summary = run_eval(
        registry,
        results_path=tmp_path / "results.jsonl",
        out=io.StringIO(),
    )
    assert summary.all_passed is True


def test_run_eval_writes_well_formed_results_line(tmp_path):
    registry = GoldenCaseRegistry()
    registry.register(_case("ZC1", measured=0.95, target=0.9))
    results_path = tmp_path / "results.jsonl"

    run_eval(
        registry,
        model_id="claude-sonnet-4-20250514",
        prompt_versions={"chn09_classify_message": "v1"},
        results_path=results_path,
        out=io.StringIO(),
    )

    lines = results_path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["model_id"] == "claude-sonnet-4-20250514"
    assert record["prompt_versions"] == {"chn09_classify_message": "v1"}
    assert record["all_passed"] is True
    assert record["results"][0]["metric_id"] == "ZC1"
    assert set(record["results"][0]) == {
        "metric_id", "name", "measured", "target", "comparator", "passed", "detail",
    }
    assert "run_at" in record


def test_run_eval_appends_rather_than_overwrites(tmp_path):
    registry = GoldenCaseRegistry()
    registry.register(_case("ZC1"))
    results_path = tmp_path / "results.jsonl"

    run_eval(registry, results_path=results_path, out=io.StringIO())
    run_eval(registry, results_path=results_path, out=io.StringIO())

    assert len(results_path.read_text().splitlines()) == 2


def test_run_eval_with_zero_registered_cases_is_a_well_formed_empty_run(tmp_path):
    registry = GoldenCaseRegistry()
    results_path = tmp_path / "results.jsonl"

    summary = run_eval(registry, results_path=results_path, out=io.StringIO())

    assert summary.results == []
    assert summary.all_passed is True
    record = json.loads(results_path.read_text().splitlines()[0])
    assert record["results"] == []
    assert record["all_passed"] is True


# --- CLI: _parse_prompt_versions -----------------------------------------


def test_parse_prompt_versions_single_pair():
    assert _parse_prompt_versions(["chn09_classify_message=v1"]) == {
        "chn09_classify_message": "v1"
    }


def test_parse_prompt_versions_multiple_pairs():
    result = _parse_prompt_versions(["a=1", "b=2"])
    assert result == {"a": "1", "b": "2"}


def test_parse_prompt_versions_empty_list():
    assert _parse_prompt_versions([]) == {}


def test_parse_prompt_versions_rejects_malformed_pair():
    with pytest.raises(ValueError, match="capability=version"):
        _parse_prompt_versions(["not-a-pair"])