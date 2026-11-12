"""Tests of the mechanism rule that compares hypotheses with the anomaly window assessment."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from verum.agents.diagnostic_reasoning.mechanism import (
    FLOW_METER,
    Family,
    family_of,
    judge,
)
from verum.agents.diagnostic_reasoning.rules import (
    NO_TARGET_QUESTION,
    enrich_hypothesis_with_rules,
    evaluate_upstream_checks,
)

pytestmark = pytest.mark.fast
IDS = {
    "R1": "R1_mass_balance",
    "R2": "R2_pump_head",
    "R3": "R3_discharge_loss",
    "R4": "R4_receipt_line",
}
REPORT_ID = "anomaly-report-1"


def assessment(states: dict[str, str] | None = None, complete: bool = True) -> dict[str, Any]:
    """A window assessment; every residual is within normal unless the states say otherwise."""
    wanted = states or {}
    rows = [
        {
            "residual_id": rid,
            "state": wanted.get(key, "within_normal"),
            "reason": "no value" if wanted.get(key) == "unknown" else None,
        }
        for key, rid in IDS.items()
    ]
    return {
        "score": 1.0, "window_threshold": 3.0, "exceeded": False, "complete": complete,
        "persistence_rule": {"k": 2, "n": 3, "threshold": 1.5}, "residuals": rows,
    }  # fmt: skip


def event(category: str, tags: list[str]) -> dict[str, Any]:
    """An anomaly event with the given category and tags."""
    return {
        "event_id": f"EV-{category}", "tag_ids": tags, "asset_ids": [], "category": category,
        "score": None, "method_id": "m", "evidence_ids": ["obs"], "limitations": ["x"],
    }  # fmt: skip


def report(
    window: dict[str, Any] | None = None, events: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """An anomaly report, with or without a window assessment."""
    result: dict[str, Any] = {"events": events or [], "coverage": "assessed"}
    if window is not None:
        result["window_assessment"] = window
    return {"report_id": REPORT_ID, "status": "complete", "issues": [], "result": result}


def hypothesis(mechanism: str, asset: str | None, tag: str | None = None) -> dict[str, Any]:
    """A single-component hypothesis."""
    return {
        "hypothesis_id": f"HYP-{mechanism}-{asset}",
        "components": [{"mechanism": mechanism, "asset_id": asset, "tag_id": tag}],
        "score": {"value": 0.5, "kind": "decision_score", "method_id": "m", "calibration_id": None},
        "support_evidence_ids": [], "conflict_evidence_ids": [], "unresolved_questions": [],
    }  # fmt: skip


def compare(hyp: dict[str, Any], rep: dict[str, Any] | None) -> tuple[bool, bool, list[str]]:
    """Whether the report is cited as support and as conflict, and the questions."""
    out = enrich_hypothesis_with_rules(hyp, {"anomaly_report": rep}, ["obs"])
    return (
        REPORT_ID in out["support_evidence_ids"],
        REPORT_ID in out["conflict_evidence_ids"],
        out["unresolved_questions"],
    )


def test_an_exceeded_expected_residual_is_support() -> None:
    """A pump head loss with R2 exceeded cites the report as support only.

    Independent: yes, because the pump head residual is the one the topology expects to move.
    """
    support, conflict, _ = compare(
        hypothesis("pump", "P-101A"), report(assessment({"R2": "exceeded"}))
    )
    assert (support, conflict) == (True, False)


def test_a_reliable_family_with_every_expected_residual_within_normal_is_conflict() -> None:
    """For the pump families, a fully assessed window with R2 within normal contradicts the fault.

    Independent: yes, because the pump families are the ones marked reliable by hand.
    """
    support, conflict, _ = compare(hypothesis("pump", "P-101A"), report(assessment()))
    assert (support, conflict) == (False, True)
    inlet = compare(hypothesis("restriction_position_visible", "XV-PAI"), report(assessment()))
    outlet = compare(hypothesis("restriction_obstruction", "XV-PBO"), report(assessment()))
    assert inlet[:2] == (False, True) and outlet[:2] == (False, True)


def test_the_outlet_valve_family_reads_r3_and_the_inlet_valve_family_reads_r2() -> None:
    """A restriction at an outlet valve is supported by R3 and not by R2.

    Independent: yes, because the valve sits after the pump discharge transmitter by the layout.
    """
    hyp = hypothesis("restriction_position_visible", "XV-PAO")
    assert compare(hyp, report(assessment({"R3": "exceeded"})))[:2] == (True, False)
    assert compare(hyp, report(assessment({"R2": "exceeded"})))[:2] == (False, True)


@pytest.mark.parametrize(
    ("mechanism", "asset"),
    [
        ("leak", "E002"),
        ("restriction_position_visible", "XV-R101"),
        ("drift", "FT-001"),
        ("stuck", "LT-102"),
    ],
)
def test_silence_of_an_unreliable_family_is_not_conflict(mechanism: str, asset: str) -> None:
    """With the expected residual within normal the report neither supports nor contradicts.

    Independent: yes, because only the pump families are marked reliable.
    """
    support, conflict, questions = compare(hypothesis(mechanism, asset), report(assessment()))
    assert (support, conflict) == (False, False)
    assert any("weak evidence" in q for q in questions)


def test_a_reliable_family_in_an_incomplete_window_is_not_conflict() -> None:
    """If the window was not fully assessed, a quiet pump residual is not held against the fault.

    Independent: yes, because the incomplete flag is set by hand on the assessment.
    """
    support, conflict, questions = compare(
        hypothesis("pump", "P-101A"), report(assessment(complete=False))
    )
    assert (support, conflict) == (False, False)
    assert any("incomplete" in q for q in questions)


def test_an_unknown_expected_residual_is_neither_support_nor_conflict() -> None:
    """With R2 unknown the report says nothing about a pump fault, and says why.

    Independent: yes, because unknown is set by hand on the expected residual.
    """
    support, conflict, questions = compare(
        hypothesis("pump", "P-101A"), report(assessment({"R2": "unknown"}))
    )
    assert (support, conflict) == (False, False)
    assert any("R2_pump_head" in q and "unknown" in q and "no value" in q for q in questions)


def test_exceeded_beats_unknown_and_unknown_beats_within_normal() -> None:
    """With several expected residuals the order is exceeded, then unknown, then within normal.

    Independent: yes, because the family and states are built by hand for the check.
    """
    family = Family("two residuals", ("R1", "R4"), True)
    assert judge(assessment({"R1": "exceeded", "R4": "unknown"}), family)[0] == "support"
    assert judge(assessment({"R1": "unknown"}), family)[0] == "unknown"
    assert judge(assessment(), family)[0] == "conflict"


@pytest.mark.parametrize(
    ("mechanism", "asset"),
    [
        ("restriction_position_visible", "XV-S101"),
        ("misroute_a", "XV-PBI"),
        ("bias", "LT-101"),
        ("leak", "E001"),
    ],
)
def test_a_family_with_no_expected_residual_is_unknown_whatever_the_residuals_do(
    mechanism: str, asset: str
) -> None:
    """No residual of the assessment is expected to move for these faults, so none counts.

    Independent: yes, because the topology puts these losses outside every residual.
    """
    everything = assessment({k: "exceeded" for k in IDS})
    for rep in (report(everything), report(assessment())):
        support, conflict, questions = compare(hypothesis(mechanism, asset), rep)
        assert (support, conflict) == (False, False)
        assert any("No residual" in q for q in questions)


@pytest.mark.parametrize(
    "hyp",
    [
        hypothesis("leak", None),
        hypothesis("restriction_position_visible", None),
        hypothesis("bias", "PT-201", "PT-201"),
        hypothesis("pump", "P-101A")
        | {
            "components": [
                {"mechanism": "pump", "asset_id": "P-101A", "tag_id": None},
                {"mechanism": "leak", "asset_id": "E002", "tag_id": None},
            ]
        },
    ],
)
def test_a_hypothesis_that_maps_to_no_family_is_unknown(hyp: dict[str, Any]) -> None:
    """Unlocated, uncovered and multi-component hypotheses are not judged.

    Independent: yes, because none of them names a family in the fixed table.
    """
    support, conflict, questions = compare(hyp, report(assessment({"R2": "exceeded"})))
    assert (support, conflict) == (False, False)
    assert any("maps to no kind of fault" in q for q in questions)


def test_quality_events_never_support_or_conflict() -> None:
    """Events that name the hypothesis' own asset or tags do not decide anything.

    Independent: yes, because the decision is taken from the assessment only.
    """
    pump = hypothesis("pump", "P-101A")
    events = [event("non_good_quality", ["PT-202A"]), event("missing_reading", ["TT-103"])]
    quiet_unassessed = report(None, events)
    assert compare(pump, quiet_unassessed)[:2] == (False, False)
    loud = report(assessment({"R2": "exceeded"}), [event("missing_reading", ["TT-103"])])
    quiet = report(assessment(), [event("missing_reading", ["TT-103"])])
    assert compare(pump, loud)[:2] == (True, False)
    assert compare(pump, quiet)[:2] == (False, True)


def test_a_quality_event_on_a_tag_the_hypothesis_relies_on_adds_a_caveat_and_blocks_conflict() -> (
    None
):
    """If the pump's own pressure tag is reported missing, silence is not held against the fault.

    Independent: yes, because PT-202A is one of the primary tags of the pump asset.
    """
    rep = report(assessment(), [event("missing_reading", ["PT-202A"])])
    support, conflict, questions = compare(hypothesis("pump", "P-101A"), rep)
    assert (support, conflict) == (False, False)
    assert any("Data-quality caveat" in q and "PT-202A" in q for q in questions)


def test_a_tag_less_event_is_ignored_and_adds_only_the_old_caveat() -> None:
    """A tag-less event neither changes the decision nor hides the assessment.

    Independent: yes, because the assessment alone says the pump residual is exceeded.
    """
    rep = report(assessment({"R2": "exceeded"}), [event("reported_signal_departure", [])])
    support, conflict, questions = compare(hypothesis("pump", "P-101A"), rep)
    assert (support, conflict) == (True, False) and NO_TARGET_QUESTION in questions


@pytest.mark.parametrize("damage", ["absent", "missing_row", "bad_state", "bad_flag"])
def test_an_absent_or_unusable_window_assessment_is_unknown(damage: str) -> None:
    """Older reports and damaged assessments leave the hypothesis without support or conflict.

    Independent: yes, because each damage removes one thing the rule needs.
    """
    window = assessment({"R2": "exceeded"})
    if damage == "missing_row":
        window["residuals"].pop()
    elif damage == "bad_state":
        window["residuals"][1]["state"] = "healthy"
    elif damage == "bad_flag":
        window["complete"] = "yes"
    rep = report(None if damage == "absent" else window, [event("non_good_quality", ["PT-202A"])])
    support, conflict, questions = compare(hypothesis("pump", "P-101A"), rep)
    assert (support, conflict) == (False, False)
    assert any("no usable window assessment" in q for q in questions)


def test_the_upstream_check_follows_the_citations() -> None:
    """The anomaly check passes on support, fails on conflict and is unknown without an assessment.

    Independent: yes, because the expected outcome follows from the state set by hand.
    """
    pump = hypothesis("pump", "P-101A")
    outcomes = {}
    for name, window in (("pass", {"R2": "exceeded"}), ("fail", {}), ("unknown", None)):
        rep = report(None if window is None else assessment(window))
        enriched = enrich_hypothesis_with_rules(pump, {"anomaly_report": rep}, ["obs"])
        checks = evaluate_upstream_checks({"anomaly_report": rep}, [enriched])
        outcomes[name] = next(c["outcome"] for c in checks if c["check_id"] == "anomaly_report")
    assert outcomes == {"pass": "pass", "fail": "fail", "unknown": "unknown"}


def test_hypothesis_identity_and_score_never_change_and_the_rule_is_deterministic() -> None:
    """Ids, components and scores survive every branch, inputs are untouched, results repeat.

    Independent: yes, because the check compares the result with deep copies of the inputs.
    """
    for window in (
        None,
        assessment(),
        assessment({"R2": "exceeded"}),
        assessment({"R2": "unknown"}),
    ):
        hyp, rep = hypothesis("pump", "P-101A"), report(window)
        before = copy.deepcopy((hyp, rep))
        first = enrich_hypothesis_with_rules(hyp, {"anomaly_report": rep}, ["obs"])
        second = enrich_hypothesis_with_rules(hyp, {"anomaly_report": rep}, ["obs"])
        assert first == second and (hyp, rep) == before
        for key in ("hypothesis_id", "components", "score"):
            assert first[key] == hyp[key]


def test_the_fixed_expectation_table() -> None:
    """The flow meters and the level transmitters read R1; only the pump families are reliable.

    Independent: yes, because the expected table is written out here by hand from the topology.
    """
    assert FLOW_METER.expected == ("R1",) and not FLOW_METER.reliable
    cases = [
        (hypothesis("pump", "P-101B"), ("R2",), True),
        (hypothesis("restriction_position_visible", "XV-PBI"), ("R2",), True),
        (hypothesis("restriction_position_visible", "XV-PBO"), ("R3",), True),
        (hypothesis("restriction_position_visible", "XV-R102"), ("R4",), False),
        (hypothesis("leak", "E-PB2"), ("R1",), False),
        (hypothesis("drift", "FT-201", "FT-201"), ("R1",), False),
        (hypothesis("stuck", "LT-103", "LT-103"), ("R1",), False),
    ]
    for hyp, expected, reliable in cases:
        family = family_of(hyp)
        assert family is not None and (family.expected, family.reliable) == (expected, reliable)
