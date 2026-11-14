"""Tests of the targets and window-derived checks that the runner gives Agent 6."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from _runner_cases import placeholders, reference, snapshot, summary
from verum.agents.common import StubAgent, check_request
from verum.agents.inspection_planning import InspectionPlanningAgent
from verum.agents.runner import run_analysis
from verum.agents.runner.builders import inspection_planning
from verum.agents.runner.prepare import FEATURES, prepare
from verum.agents.runner.targets import RECEIPT_TEXT, implicated_assets
from verum.contracts.agent_interfaces import FORBIDDEN

pytestmark = pytest.mark.fast
ASSETS = {a["asset_id"] for a in reference()["assets"]}
REPORT_KEYS = (
    "predictive_health", "anomaly_detection", "topology_dependency",
    "historical_asset_intelligence", "diagnostic_reasoning", "inspection_planning",
    "inspection_quality_documentation", "evidence_verification_decision",
)  # fmt: skip


def hypothesis(mechanism: str, asset: str | None, tag: str | None = None) -> dict[str, Any]:
    """A hypothesis with one component."""
    return {
        "hypothesis_id": f"HYP-{mechanism}-{asset}-{tag}",
        "components": [{"mechanism": mechanism, "asset_id": asset, "tag_id": tag}],
        "score": None, "support_evidence_ids": [], "conflict_evidence_ids": [],
        "unresolved_questions": [],
    }  # fmt: skip


def diagnosis(*hyps: dict[str, Any]) -> dict[str, Any]:
    """A diagnosis report holding the hypotheses."""
    return {"report_id": "diag", "result": {"hypotheses": list(hyps)}}


def with_state(
    tag: str, value: float | None, quality: str = "good", status: str = "measured"
) -> Any:
    """A summary in which one on-off tag has the given latest state."""
    window = copy.deepcopy(summary())
    for signal in window["signals"]:
        if signal["tag_id"] == tag:
            signal.update(latest_value=value, latest_quality=quality, latest_availability=status)
    return window


def built(diag: dict[str, Any] | None, window: Any = None, **changes: Any) -> tuple[Any, Any]:
    """The Agent 6 input the builder makes, and the notes it recorded."""
    snap = snapshot(**({"summary": window} if window is not None else {}), **changes)
    prep = prepare(snap, "runtime")
    reports: dict[str, Any] = dict.fromkeys(REPORT_KEYS)
    reports["diagnostic_reasoning"] = diag
    return inspection_planning(prep, reports), prep.notes


class Scripted:
    """Agent 5 stand-in: the placeholder response with the given hypotheses."""

    def __init__(self, *hyps: dict[str, Any]) -> None:
        self.hyps = list(hyps)

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        response = StubAgent("diagnostic_reasoning").run(request)
        response["result"]["hypotheses"] = copy.deepcopy(self.hyps)
        response["result"]["assessment"] = "candidates_available"
        return response


def run_with(hyps: list[dict[str, Any]], window: Any = None) -> Any:
    """A run with a scripted Agent 5 and the real Agent 6."""
    agents: dict[str, Any] = {
        **placeholders(), "diagnostic_reasoning": Scripted(*hyps),
        "inspection_planning": InspectionPlanningAgent(),
    }  # fmt: skip
    snap = snapshot(**({"summary": window} if window is not None else {}))
    return run_analysis(snap, "runtime", agents=agents)


def test_implicated_assets_become_the_targets_in_rank_order_without_repeats() -> None:
    """Assets named by the hypotheses are the targets, first-ranked first.

    Independent: yes, because the expected list is written out from the hypotheses.
    """
    diag = diagnosis(
        hypothesis("restriction_position_visible", "XV-PBI"),
        hypothesis("pump", "P-101A"),
        hypothesis("leak", "XV-PBI"),
    )
    assert implicated_assets(diag, ASSETS) == ["XV-PBI", "P-101A"]
    built_input, _ = built(diag)
    assert built_input["target_asset_ids"] == ["XV-PBI", "P-101A"]


def test_a_tag_is_implicated_only_when_it_is_itself_an_asset() -> None:
    """A pressure transmitter is an asset, a level transmitter is not, an unknown name is not.

    Independent: yes, because the reference lists PT-202A as an asset and LT-101 as a tag only.
    """
    diag = diagnosis(
        hypothesis("bias", None, "PT-202A"),
        hypothesis("drift", None, "LT-101"),
        hypothesis("leak", "NOPE-1"),
    )
    assert "PT-202A" in ASSETS and "LT-101" not in ASSETS
    assert implicated_assets(diag, ASSETS) == ["PT-202A"]


def test_no_implicated_asset_gives_no_target_and_a_plain_note() -> None:
    """With no named asset, or no diagnosis, the target list is empty and the note says so.

    Independent: yes, because the lists are empty by construction.
    """
    for diag in (diagnosis(hypothesis("leak", None)), diagnosis(), None):
        planned, notes = built(diag)
        assert planned["target_asset_ids"] == []
        assert ("inspection_planning", "NO_IMPLICATED_ASSETS") in {
            (n["role"], n["code"]) for n in notes
        }


def test_several_implicated_assets_are_all_passed_and_stay_unknown() -> None:
    """With two targets Agent 6 cannot establish a precondition, whatever the window shows.

    Independent: yes, because the rule 'exactly one target' is part of the contract of Agent 6.
    """
    bundle = run_with([hypothesis("leak", "TK-101"), hypothesis("leak", "TK-102")])
    report = bundle.reports["inspection_planning"]
    assert bundle.requests["inspection_planning"]["input"]["target_asset_ids"] == [
        "TK-101",
        "TK-102",
    ]
    assert {o["feasibility"] for o in report["result"]["options"]} == {"unknown"}


def test_a_check_comes_only_from_the_window_and_only_as_a_pass() -> None:
    """A closed receipt valve gives one pass for the tank; an open one gives nothing.

    Independent: yes, because the window values are set by the test.
    """
    closed, _ = built(diagnosis(hypothesis("leak", "TK-101")), with_state("XV-R101", 0.0))
    assert closed["constraint_checks"] == [
        {
            "check_id": "ACT-INSP-06-TK-101-WINDOW-01",
            "description": RECEIPT_TEXT,
            "outcome": "pass",
            "evidence_ids": [FEATURES],
        }  # fmt: skip
    ]
    opened, notes = built(diagnosis(hypothesis("leak", "TK-101")), with_state("XV-R101", 1.0))
    assert opened["constraint_checks"] == []
    assert "PRECONDITION_FAILURES_NOT_DERIVED" in {n["code"] for n in notes}


@pytest.mark.parametrize(
    "window",
    [
        with_state("XV-R101", None),
        with_state("XV-R101", 0.0, quality="bad"),
        with_state("XV-R101", 0.0, status="missing"),
        with_state("XV-R101", 0.5),
    ],  # fmt: skip
)
def test_an_unreadable_contact_gives_no_check(window: Any) -> None:
    """A missing, bad or non-boolean contact reading derives nothing.

    Independent: yes, because each window damages the one reading the check would use.
    """
    planned, _ = built(diagnosis(hypothesis("leak", "TK-101")), window)
    assert planned["constraint_checks"] == []


def test_nothing_is_derived_for_pumps_valves_or_pipes() -> None:
    """Only the tank precondition is read; a running pump or a valve gives no pass.

    Independent: yes, because the 20 minutes of the pump precondition exceed the 300 s window.
    """
    diag = diagnosis(hypothesis("pump", "P-101A"), hypothesis("leak", "E002"),
                     hypothesis("restriction_position_visible", "XV-PBI"))  # fmt: skip
    planned, _ = built(diag, with_state("P-101A", 1.0))
    assert planned["constraint_checks"] == []


def test_a_stopped_pump_is_counted_but_not_derived_as_a_failure() -> None:
    """A stopped pump leaves its precondition unknown and is recorded in a note.

    Independent: yes, because failures are never derived by design.
    """
    planned, notes = built(diagnosis(hypothesis("pump", "P-101A")), with_state("P-101A", 0.0))
    assert planned["constraint_checks"] == []
    assert "PRECONDITION_FAILURES_NOT_DERIVED" in {n["code"] for n in notes}


def test_an_absent_check_leaves_the_option_unknown_and_a_present_one_makes_it_eligible() -> None:
    """With one tank target the receipt option is eligible only when the window shows it.

    Independent: yes, because the precondition list of ACT-INSP-06 has one entry.
    """
    for value, expected in ((0.0, "eligible_for_human_review"), (1.0, "unknown")):
        bundle = run_with([hypothesis("leak", "TK-101")], with_state("XV-R101", value))
        options = bundle.reports["inspection_planning"]["result"]["options"]
        by_action = {o["action_id"]: o["feasibility"] for o in options}
        assert by_action["ACT-INSP-06"] == expected
        assert by_action["ACT-INSP-01"] == "unknown" and by_action["ACT-INSP-05"] == "unknown"


def test_older_call_patterns_still_work() -> None:
    """A caller's assets and checks are used as given and a derived check is not duplicated.

    Independent: yes, because the caller's values are literals.
    """
    given = ("PT-001", "TK-101")
    planned, notes = built(None, query_asset_ids=given)
    assert planned["target_asset_ids"] == list(given)
    assert "NO_IMPLICATED_ASSETS" not in {n["code"] for n in notes}
    own = {"check_id": "ACT-INSP-06-TK-101-MINE", "description": RECEIPT_TEXT,
           "outcome": "pass", "evidence_ids": [FEATURES]}  # fmt: skip
    planned, _ = built(diagnosis(hypothesis("leak", "TK-101")), constraint_checks=(own,))
    assert planned["constraint_checks"] == [own]
    assert planned["budget"] == {"max_cost_usd": None, "max_duration_min": None}


def test_nothing_label_like_reaches_the_agent_6_request() -> None:
    """The built request is valid, has the usual keys, and holds no forbidden field anywhere.

    Independent: yes, because the forbidden names come from the contract validator.
    """
    bundle = run_with([hypothesis("leak", "TK-101")])
    request = bundle.requests["inspection_planning"]
    check_request(request)

    def keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {k for v in value.values() for k in keys(v)}
        if isinstance(value, list):
            return {k for v in value for k in keys(v)}
        return set()

    assert not keys(request) & FORBIDDEN
    assert set(request["input"]) == {
        "diagnosis_report", "catalog", "catalog_evidence_ids", "observations",
        "constraint_checks", "budget", "target_asset_ids", "assets", "workflow_requests",
    }  # fmt: skip
    assert "episode" not in str(request["context"]).lower()


def test_the_built_input_is_deterministic_and_leaves_its_inputs_alone() -> None:
    """The same snapshot and report give the same input, and the report is not modified.

    Independent: yes, because the check compares two builds and a deep copy.
    """
    diag = diagnosis(hypothesis("leak", "TK-101"))
    before = copy.deepcopy(diag)
    first, _ = built(diag)
    second, _ = built(diag)
    assert first == second and diag == before
