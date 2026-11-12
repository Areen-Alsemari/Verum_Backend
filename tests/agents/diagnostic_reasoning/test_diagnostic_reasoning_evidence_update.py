"""Tests of the odds update of Agent 5 scores from the anomaly window assessment."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
from typing import Any

import pytest

from verum.agents.diagnostic_reasoning import evidence_update
from verum.agents.diagnostic_reasoning.evidence_update import (
    METHOD_SUFFIX,
    combined_ratio,
    load_ratios,
    load_ratios_from,
    odds_update,
    update_scores,
)
from verum.contracts.paths import repo_root

pytestmark = pytest.mark.fast
IDS = {
    "R1": "R1_mass_balance",
    "R2": "R2_pump_head",
    "R3": "R3_discharge_loss",
    "R4": "R4_receipt_line",
}


def entry(expected: list[str], up: float, down: float, combine: str = "single") -> dict[str, Any]:
    """A family entry with the same ratios for every expected residual."""
    ratios = {k: {"exceeded": {"ratio": up}, "within_normal": {"ratio": down}} for k in expected}
    return {"expected": expected, "combine": combine, "ratios": ratios}


TABLE = {
    "pump head loss": entry(["R2"], 10.0, 0.1),
    "restriction at a pump outlet valve": entry(["R3"], 4.0, 0.5),
    "pump A discharge transmitter fault": entry(["R2", "R3"], 3.0, 0.5, "product"),
    "pump B discharge transmitter fault": entry(["R2", "R3"], 3.0, 0.5, "largest"),
}


def assessment(states: dict[str, str]) -> dict[str, Any]:
    """A window assessment; residuals not named are within normal."""
    rows = [
        {"residual_id": rid, "state": states.get(key, "within_normal"), "reason": None}
        for key, rid in IDS.items()
    ]
    return {"score": 1.0, "complete": True, "residuals": rows}


def report(window: dict[str, Any] | None) -> dict[str, Any]:
    """An anomaly report with or without a window assessment."""
    result: dict[str, Any] = {"events": [], "coverage": "assessed"}
    if window is not None:
        result["window_assessment"] = window
    return {"report_id": "A2", "status": "complete", "issues": [], "result": result}


def hypothesis(mechanism: str, asset: str | None, score: float, index: int = 1) -> dict[str, Any]:
    """A single-component hypothesis with a decision score."""
    tag = asset if mechanism in ("bias", "drift", "stuck") else None
    return {
        "hypothesis_id": f"HYP-{index:02d}-{mechanism}-{asset}",
        "components": [{"mechanism": mechanism, "asset_id": asset, "tag_id": tag}],
        "score": {
            "value": score, "kind": "decision_score", "method_id": "m", "calibration_id": None,
        },
        "support_evidence_ids": [], "conflict_evidence_ids": [], "unresolved_questions": [],
    }  # fmt: skip


def scores(hyps: list[dict[str, Any]]) -> dict[str, float]:
    """Score by identifier."""
    return {h["hypothesis_id"]: h["score"]["value"] for h in hyps}


def test_an_exceeded_residual_raises_the_matching_family_and_not_the_others() -> None:
    """With R2 exceeded and R3 unknown the pump score rises and the outlet valve one stays.

    Independent: yes, because 0.5 odds of 1 times 10 is 10/11, worked by hand.
    """
    hyps = [
        hypothesis("pump", "P-101A", 0.5),
        hypothesis("restriction_position_visible", "XV-PAO", 0.5, 2),
    ]
    out = update_scores(hyps, report(assessment({"R2": "exceeded", "R3": "unknown"})), TABLE)
    got = scores(out)
    assert got["HYP-01-pump-P-101A"] == pytest.approx(10 / 11, abs=1e-6)
    assert got["HYP-02-restriction_position_visible-XV-PAO"] == 0.5


def test_within_normal_in_a_reliable_family_lowers_the_score() -> None:
    """With R2 within normal the pump score falls to 1/11 and the list is sorted again.

    Independent: yes, because odds of 1 times 0.1 is 1/11, worked by hand.
    """
    hyps = [
        hypothesis("pump", "P-101A", 0.6),
        hypothesis("restriction_position_visible", "XV-PAO", 0.5, 2),
    ]
    out = update_scores(hyps, report(assessment({"R3": "unknown"})), TABLE)
    assert scores(out)["HYP-01-pump-P-101A"] == pytest.approx(0.1 * 1.5 / (1 + 0.1 * 1.5), abs=1e-6)
    assert [h["hypothesis_id"] for h in out] == [
        "HYP-02-restriction_position_visible-XV-PAO",
        "HYP-01-pump-P-101A",
    ]


def test_an_unknown_expected_residual_changes_nothing() -> None:
    """An unknown residual gives a ratio of 1: scores, order and objects are unchanged.

    Independent: yes, because the expected output equals the input.
    """
    hyps = [hypothesis("pump", "P-101A", 0.7), hypothesis("pump", "P-101B", 0.4, 2)]
    out = update_scores(hyps, report(assessment({"R2": "unknown"})), TABLE)
    assert out == hyps


@pytest.mark.parametrize("window", [None, {"complete": True, "residuals": []}])
def test_an_absent_or_unusable_assessment_leaves_the_list_as_it_was(
    window: dict[str, Any] | None,
) -> None:
    """Older reports and damaged assessments give back the very same list.

    Independent: yes, because the check compares with the input list.
    """
    hyps = [hypothesis("pump", "P-101A", 0.7), hypothesis("pump", "P-101B", 0.9, 2)]
    assert update_scores(hyps, report(window), TABLE) == hyps
    assert update_scores(hyps, None, TABLE) == hyps


@pytest.mark.parametrize(
    ("mechanism", "asset"),
    [("misroute_a", "XV-PBI"), ("leak", None), ("restriction_position_visible", "XV-S101")],
)
def test_a_family_with_no_expected_residual_or_none_at_all_is_unchanged(
    mechanism: str, asset: str | None
) -> None:
    """Misrouting, an unlocated leak and a tank-outlet restriction keep their scores.

    Independent: yes, because none of them has an expected residual in the fixed table.
    """
    hyps = [hypothesis(mechanism, asset, 0.8)]
    out = update_scores(hyps, report(assessment({k: "exceeded" for k in IDS})), TABLE)
    assert out == hyps


def test_scores_stay_in_range_and_extreme_scores_stay() -> None:
    """A large ratio cannot take a score above 1 or below 0; exactly 0 and 1 stay.

    Independent: yes, because the bounds follow from the odds transform.
    """
    for score in (0.0, 1e-9, 0.5, 0.999999, 1.0):
        for ratio in (0.05, 1.0, 20.0, 1e9):
            assert 0.0 <= odds_update(score, ratio) <= 1.0
    assert odds_update(0.0, 20.0) == 0.0 and odds_update(1.0, 0.05) == 1.0
    assert odds_update(0.5, 20.0) == pytest.approx(20 / 21, abs=1e-6)


def test_identity_method_and_flags_survive_and_the_update_is_deterministic() -> None:
    """Ids and components never change, the method is labelled, inputs are untouched.

    Independent: yes, because the check compares with deep copies of the inputs.
    """
    hyps = [hypothesis("pump", "P-101A", 0.5), hypothesis("pump", "P-101B", 0.4, 2)]
    rep = report(assessment({"R2": "exceeded"}))
    before = copy.deepcopy((hyps, rep))
    first, second = update_scores(hyps, rep, TABLE), update_scores(hyps, rep, TABLE)
    assert first == second and (hyps, rep) == before
    for old, new in zip(hyps, sorted(first, key=lambda h: h["hypothesis_id"]), strict=True):
        assert (old["hypothesis_id"], old["components"]) == (
            new["hypothesis_id"],
            new["components"],
        )
        assert new["score"]["method_id"] == "m" + METHOD_SUFFIX
        assert new["score"]["kind"] == "decision_score" and new["score"]["calibration_id"] is None


def test_two_residuals_combine_by_product_or_by_the_largest_effect() -> None:
    """The product multiplies both ratios; 'largest' keeps the one furthest from 1.

    Independent: yes, because the ratios are set by hand: 3 and 0.5 give 1.5 or 3.
    """
    states = {IDS["R2"]: "exceeded", IDS["R3"]: "within_normal"}
    assert combined_ratio(TABLE["pump A discharge transmitter fault"], states) == pytest.approx(1.5)
    assert combined_ratio(TABLE["pump B discharge transmitter fault"], states) == pytest.approx(3.0)


def test_the_ratio_file_is_pinned_and_its_ratios_are_bounded() -> None:
    """A changed file is refused, and every shipped ratio lies between the floor and the cap.

    Independent: yes, because the bounds are the pre-registered 0.05 and 20.
    """
    path = evidence_update.RATIOS_PATH
    with pytest.raises(ValueError, match="hash mismatch"):
        load_ratios_from(path, "0" * 64)
    table = load_ratios()
    ratios = [
        cell["ratio"]
        for fam in table.values()
        for res in fam["ratios"].values()
        for cell in (res["exceeded"], res["within_normal"])
    ]
    assert ratios and all(0.05 <= r <= 20.0 for r in ratios)
    assert json.loads(path.read_text())["provenance"]["splits_used"] == ["train"]


def fit_module() -> Any:
    """The estimation script as a module."""
    path = repo_root() / "tools" / "agents" / "fit_evidence_ratios.py"
    spec = importlib.util.spec_from_file_location("fit_evidence_ratios", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fit_evidence_ratios"] = module
    spec.loader.exec_module(module)
    return module


def test_the_estimate_is_smoothed_floored_and_capped() -> None:
    """Add-one smoothing, the floor, the cap and the minimum window count, by hand.

    Independent: yes, because every expected number is worked out from the counts.
    """
    import numpy as np

    fit = fit_module()
    code = np.asarray([[2]] * 40 + [[2]] * 1 + [[1]] * 959 + [[1]] * 40, dtype=np.intp)
    rows = np.asarray([True] * 40 + [False] * 1000)
    free = ~rows
    table = fit.ratio_table(code, rows, free, 0)
    assert table["exceeded"]["ratio"] == fit.CAP  # (41/42) / (2/1002) is far above the cap
    assert table["within_normal"]["ratio"] == fit.FLOOR  # (1/42) / (1000/1002) is below it
    few = fit.ratio_table(
        code, np.asarray([True] * 5 + [False] * 1035), ~np.asarray([True] * 5 + [False] * 1035), 0
    )
    assert few["exceeded"]["ratio"] == 1.0 and few["within_normal"]["ratio"] == 1.0


def test_the_estimation_script_reads_the_train_split_only() -> None:
    """The script names no validation or test split in its code.

    Independent: yes, because the check reads the source of the script, not its output.
    """
    path = repo_root() / "tools" / "agents" / "fit_evidence_ratios.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef))
                  and n.body and isinstance(n.body[0], ast.Expr)}  # fmt: skip
    names = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
             and isinstance(n.value, str) and id(n) not in docstrings}  # fmt: skip
    assert "train" in names and not names & {"validation", "test"}
