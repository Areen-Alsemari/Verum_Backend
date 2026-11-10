"""Tests for evidence-backed inspection precondition evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from verum.agents.common import attached_report_ids, check_response
from verum.agents.inspection_planning import agent as planning_agent
from verum.agents.inspection_planning.agent import InspectionPlanningAgent, _within_budget
from verum.agents.inspection_planning.preconditions import (
    evaluate_preconditions,
)


def make_request(
    constraint_checks: list[dict[str, Any]],
    target_asset_ids: list[str] | None = None,
    approval_status: str = "APPROVED",
    *,
    permit_number: str | None = "PERMIT-001",
    workflow_action: str = "ACT-INSP-01",
    workflow_target: str = "TK-101",
) -> dict[str, Any]:
    """Build a minimal request for precondition tests."""
    return {
        "evidence": [
            {
                "evidence_id": "EV-001",
                "kind": "observation_window",
                "source_ref": "observations:window-001",
                "available_at_s": 0.0,
                "content_sha256": "a" * 64,
                "root_evidence_ids": ["EV-001"],
                "provenance": "simulated_observation",
            },
            {
                "evidence_id": "EV-002",
                "kind": "inspection_request",
                "source_ref": "inspection_request:REQ-INSP-00001",
                "available_at_s": 0.0,
                "content_sha256": "b" * 64,
                "root_evidence_ids": ["EV-002"],
                "provenance": "simulated_workflow",
            },
        ],
        "input": {
            "constraint_checks": constraint_checks,
            "target_asset_ids": target_asset_ids or ["TK-101"],
            "workflow_requests": [
                {
                    "request_id": "REQ-INSP-00001",
                    "action_id": workflow_action,
                    "target_asset": workflow_target,
                    "human_approval": {
                        "status": approval_status,
                        "work_permit_number": permit_number,
                    },
                }
            ],
        },
    }


def make_action() -> dict[str, Any]:
    """Build a catalog action with two preconditions."""
    return {
        "action_id": "ACT-INSP-01",
        "preconditions": [
            "Tank level above 1.8 m",
            "Authorised permit issued by the approval",
        ],
    }


def passing_checks(
    level_evidence: list[str] | None = None,
    permit_evidence: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Two passing checks, one per precondition of the test action."""
    return [
        {
            "check_id": "ACT-INSP-01-TK-101-PRE-01",
            "description": "Tank level above 1.8 m",
            "outcome": "pass",
            "evidence_ids": ["EV-001"] if level_evidence is None else level_evidence,
        },
        {
            "check_id": "ACT-INSP-01-TK-101-PRE-02",
            "description": "Authorised permit issued by the approval",
            "outcome": "pass",
            "evidence_ids": ["EV-002"] if permit_evidence is None else permit_evidence,
        },
    ]


def test_all_sourced_preconditions_pass() -> None:
    """All supported checks allow human review.

    Independent: yes, because this tests the evaluator without the agent runtime.
    """
    request = make_request(
        [
            {
                "check_id": "ACT-INSP-01-TK-101-PRE-01",
                "description": "Tank level above 1.8 m",
                "outcome": "pass",
                "evidence_ids": ["EV-001"],
            },
            {
                "check_id": "ACT-INSP-01-TK-101-PRE-02",
                "description": "Authorised permit issued by the approval",
                "outcome": "pass",
                "evidence_ids": ["EV-002"],
            },
        ]
    )

    checks, feasibility = evaluate_preconditions(make_action(), request, "TK-101")

    assert feasibility == "eligible_for_human_review"
    assert [check["outcome"] for check in checks] == ["pass", "pass"]


def test_missing_preconditions_remain_unknown() -> None:
    """Missing checks cannot be treated as passing.

    Independent: yes, because the request contains no constraint evidence.
    """
    checks, feasibility = evaluate_preconditions(make_action(), make_request([]), "TK-101")

    assert feasibility == "unknown"
    assert [check["outcome"] for check in checks] == ["unknown", "unknown"]


def test_failed_precondition_blocks_the_action() -> None:
    """An evidenced failed precondition blocks human review.

    Independent: yes, because the evaluator receives an explicit failed check.
    """
    request = make_request(
        [
            {
                "check_id": "ACT-INSP-01-TK-101-PRE-01",
                "description": "Tank level above 1.8 m",
                "outcome": "fail",
                "evidence_ids": ["EV-001"],
            }
        ]
    )

    checks, feasibility = evaluate_preconditions(make_action(), request, "TK-101")

    assert feasibility == "blocked"
    assert checks[0]["outcome"] == "fail"
    assert checks[1]["outcome"] == "unknown"


def test_unregistered_evidence_cannot_support_a_check() -> None:
    """Unregistered evidence cannot establish a precondition.

    Independent: yes, because the check references a missing evidence ID.
    """
    request = make_request(
        [
            {
                "check_id": "ACT-INSP-01-TK-101-PRE-01",
                "description": "Tank level above 1.8 m",
                "outcome": "pass",
                "evidence_ids": ["EV-MISSING"],
            },
            {
                "check_id": "ACT-INSP-01-TK-101-PRE-02",
                "description": "Authorised permit issued by the approval",
                "outcome": "pass",
                "evidence_ids": ["EV-002"],
            },
        ]
    )

    checks, feasibility = evaluate_preconditions(make_action(), request, "TK-101")

    assert feasibility == "unknown"
    assert [check["outcome"] for check in checks] == ["unknown", "pass"]


def test_pending_approval_does_not_satisfy_permit() -> None:
    """Pending approval cannot establish permit eligibility.

    Independent: yes, because the workflow has not received approval.
    """
    request = make_request(
        [
            {
                "check_id": "ACT-INSP-01-TK-101-PRE-01",
                "description": "Tank level above 1.8 m",
                "outcome": "pass",
                "evidence_ids": ["EV-001"],
            },
            {
                "check_id": "ACT-INSP-01-TK-101-PRE-02",
                "description": "Authorised permit issued by the approval",
                "outcome": "pass",
                "evidence_ids": ["EV-002"],
            },
        ],
        approval_status="PENDING",
    )

    checks, feasibility = evaluate_preconditions(make_action(), request, "TK-101")

    assert feasibility == "unknown"
    assert [check["outcome"] for check in checks] == ["pass", "unknown"]


def test_rejected_approval_does_not_satisfy_permit() -> None:
    """Rejected approval cannot establish permit eligibility.

    Independent: yes, because the workflow explicitly records rejection.
    """
    request = make_request(
        [
            {
                "check_id": "ACT-INSP-01-TK-101-PRE-01",
                "description": "Tank level above 1.8 m",
                "outcome": "pass",
                "evidence_ids": ["EV-001"],
            },
            {
                "check_id": "ACT-INSP-01-TK-101-PRE-02",
                "description": "Authorised permit issued by the approval",
                "outcome": "pass",
                "evidence_ids": ["EV-002"],
            },
        ],
        approval_status="REJECTED",
    )

    checks, feasibility = evaluate_preconditions(make_action(), request, "TK-101")

    assert feasibility == "unknown"
    assert [check["outcome"] for check in checks] == ["pass", "unknown"]


def test_conflicting_checks_remain_unknown() -> None:
    """Conflicting outcomes cannot establish a precondition.

    Independent: yes, because two checks disagree about the same condition.
    """
    request = make_request(
        [
            {
                "check_id": "ACT-INSP-01-TK-101-PRE-01",
                "description": "Tank level above 1.8 m",
                "outcome": "pass",
                "evidence_ids": ["EV-001"],
            },
            {
                "check_id": "ACT-INSP-01-TK-101-PRE-02",
                "description": "Tank level above 1.8 m",
                "outcome": "fail",
                "evidence_ids": ["EV-001"],
            },
        ]
    )

    checks, feasibility = evaluate_preconditions(make_action(), request, "TK-101")

    assert feasibility == "unknown"
    assert checks[0]["outcome"] == "unknown"
    assert checks[1]["outcome"] == "unknown"


def test_multiple_target_assets_prevent_ambiguous_scoping() -> None:
    """Checks are not assigned to an asset when the request has multiple targets.

    Independent: yes, because the target scope is deliberately ambiguous.
    """
    request = make_request(
        [
            {
                "check_id": "ACT-INSP-01-TK-101-PRE-01",
                "description": "Tank level above 1.8 m",
                "outcome": "pass",
                "evidence_ids": ["EV-001"],
            },
            {
                "check_id": "ACT-INSP-01-TK-101-PRE-02",
                "description": "Authorised permit issued by the approval",
                "outcome": "pass",
                "evidence_ids": ["EV-002"],
            },
        ],
        ["TK-101", "TK-102"],
    )

    checks, feasibility = evaluate_preconditions(make_action(), request, "TK-101")

    assert feasibility == "unknown"
    assert [check["outcome"] for check in checks] == ["unknown", "unknown"]


def make_runtime_request() -> dict[str, Any]:
    """Load the repository's chained inspection-planning request fixture."""
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "agents"
        / "fixtures"
        / "chained"
        / "inspection_planning.request.json"
    )
    data: dict[str, Any] = json.loads(fixture.read_text(encoding="utf-8"))
    return data


def test_runtime_generates_contract_valid_options() -> None:
    """Runtime generates options and preserves advisory-only behavior.

    Independent: yes, because this exercises the complete agent runtime.
    """
    request = make_runtime_request()
    response = InspectionPlanningAgent().run(request)

    assert response["status"] == "degraded"
    assert len(response["result"]["options"]) == 55
    assert response["result"]["recommended_option_id"] is None
    assert response["result"]["dispatch_authorized"] is False


def test_runtime_only_matches_compatible_asset_kinds() -> None:
    """An inspection action is only offered for its required asset kind.

    Independent: yes, because compatibility is checked against the fixture catalog.
    """
    request = make_runtime_request()
    response = InspectionPlanningAgent().run(request)

    assets = {asset["asset_id"]: asset["kind"] for asset in request["input"]["assets"]}
    actions = {action["action_id"]: action for action in request["input"]["catalog"]}

    for option in response["result"]["options"]:
        action = actions[option["action_id"]]
        assert assets[option["target_asset"]] == action["target_kind"]


def test_runtime_keeps_missing_preconditions_unknown() -> None:
    """Missing constraint checks never create eligible inspection options.

    Independent: yes, because the fixture supplies no constraint checks.
    """
    request = make_runtime_request()
    response = InspectionPlanningAgent().run(request)

    assert request["input"]["constraint_checks"] == []
    assert all(option["feasibility"] == "unknown" for option in response["result"]["options"])


def test_runtime_respects_inspection_budget() -> None:
    """Actions exceeding the supplied budget are marked blocked.

    Independent: yes, because the budget is changed for this test only.
    """
    request = make_runtime_request()
    request["input"]["budget"]["max_cost_usd"] = 100.0

    response = InspectionPlanningAgent().run(request)

    expensive_options = [
        option for option in response["result"]["options"] if option["cost_usd"] > 100.0
    ]

    assert expensive_options
    assert all(option["feasibility"] == "blocked" for option in expensive_options)


def test_runtime_does_not_invent_diagnostic_hypotheses() -> None:
    """An empty diagnostic hypothesis list produces no hypothesis links.

    Independent: yes, because the fixture diagnostic report has no hypotheses.
    """
    request = make_runtime_request()
    response = InspectionPlanningAgent().run(request)

    assert request["input"]["diagnosis_report"]["result"]["hypotheses"] == []
    assert all(option["addresses_hypothesis_ids"] == [] for option in response["result"]["options"])


@pytest.mark.parametrize(
    ("cost", "duration", "fits"),
    [
        (100.0, 60.0, True),
        (101.0, 60.0, False),
        (100.0, 61.0, False),
    ],
)
def test_budget_limits_are_inclusive(cost: float, duration: float, fits: bool) -> None:
    """An action exactly at the cost and duration limits fits; one unit over does not.

    Independent: yes, because the limits are fixed numbers in the test.
    """
    action = {"cost_usd": cost, "duration_min": duration}
    budget = {"max_cost_usd": 100.0, "max_duration_min": 60.0}
    assert _within_budget(action, budget) is fits


def test_check_without_evidence_is_not_met() -> None:
    """A passing check that cites no evidence leaves the precondition unknown.

    Independent: yes, because the evidence list is empty by construction.
    """
    request = make_request(passing_checks(level_evidence=[]))
    checks, feasibility = evaluate_preconditions(make_action(), request, "TK-101")
    assert checks[0]["outcome"] == "unknown"
    assert feasibility == "unknown"


@pytest.mark.parametrize("number", [None, "", "   "])
def test_approved_permit_without_number_is_not_met(number: str | None) -> None:
    """An approved workflow with no permit number does not satisfy the permit.

    Independent: yes, because only the permit number differs from a passing request.
    """
    request = make_request(passing_checks(), permit_number=number)
    checks, _ = evaluate_preconditions(make_action(), request, "TK-101")
    assert checks[1]["outcome"] == "unknown"


@pytest.mark.parametrize(
    ("workflow_action", "workflow_target"),
    [("ACT-OTHER", "TK-101"), ("ACT-INSP-01", "TK-102")],
)
def test_permit_for_another_action_or_target_is_not_met(
    workflow_action: str, workflow_target: str
) -> None:
    """A permit approved for a different action or asset does not satisfy this one.

    Independent: yes, because only the workflow scope differs from a passing request.
    """
    request = make_request(
        passing_checks(),
        workflow_action=workflow_action,
        workflow_target=workflow_target,
    )
    checks, _ = evaluate_preconditions(make_action(), request, "TK-101")
    assert checks[1]["outcome"] == "unknown"


@pytest.mark.parametrize(
    ("index", "field", "value"),
    [
        (0, "provenance", "simulated_workflow"),
        (0, "source_ref", "features:window-001"),
        (1, "provenance", "simulated_observation"),
        (1, "source_ref", "observations:REQ-INSP-00001"),
    ],
)
def test_wrong_provenance_or_source_prefix_is_not_met(index: int, field: str, value: str) -> None:
    """Evidence with the wrong provenance or source prefix cannot support a check.

    Independent: yes, because one registered evidence field is changed per case.
    """
    request = make_request(passing_checks())
    request["evidence"][index][field] = value
    checks, _ = evaluate_preconditions(make_action(), request, "TK-101")
    assert checks[index]["outcome"] == "unknown"


def test_checks_keep_their_evidence() -> None:
    """Each check lists the evidence that supports it.

    Independent: yes, because the expected ids are the ones placed in the request.
    """
    checks, _ = evaluate_preconditions(make_action(), make_request(passing_checks()), "TK-101")
    assert [check["evidence_ids"] for check in checks] == [["EV-001"], ["EV-002"]]


def assert_validated_error(request: dict[str, Any], response: dict[str, Any], code: str) -> None:
    """Shared checks for every error response."""
    assert response["status"] == "error"
    assert response["result"] is None
    assert any(issue["code"] == code for issue in response["issues"])
    assert set(attached_report_ids(request)) <= set(response["consumed_evidence_ids"])
    check_response(request, response)


def test_duplicate_action_id_returns_a_validated_error() -> None:
    """A catalogue that repeats an action id is answered with an error, not raised.

    Independent: yes, because the duplicate is added to the fixture in the test.
    """
    request = make_runtime_request()
    request["input"]["catalog"].append(dict(request["input"]["catalog"][0]))
    response = InspectionPlanningAgent().run(request)
    assert_validated_error(request, response, "DUPLICATE_ACTION_ID")


def test_internal_failure_returns_a_validated_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An exception inside planning returns a validated error that keeps the report ids.

    Independent: yes, because the failure is injected and checked by the real validator.
    """

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("injected")

    monkeypatch.setattr(planning_agent, "evaluate_action", fail)
    request = make_runtime_request()
    response = InspectionPlanningAgent().run(request)
    assert_validated_error(request, response, "INTERNAL_ERROR")


@pytest.mark.parametrize(
    "check_id",
    ["ACT-OTHER-TK-101-PRE-01", "ACT-INSP-01-TK-102-PRE-01", "CHK-01"],
)
def test_check_for_another_action_or_asset_is_not_used(check_id: str) -> None:
    """A check scoped to a different action or asset, or not scoped, does not satisfy this one.

    Independent: yes, because only the check id differs from a passing request.
    """
    checks_in = passing_checks()
    checks_in[0]["check_id"] = check_id
    checks, _ = evaluate_preconditions(make_action(), make_request(checks_in), "TK-101")
    assert checks[0]["outcome"] == "unknown"


def test_runtime_keeps_check_evidence_and_report_ids() -> None:
    """Evidence cited by a check reaches the check, the option and the consumed list.

    Independent: yes, because the check is added to the fixture in the test.
    """
    request = make_runtime_request()
    observation = next(
        row["evidence_id"] for row in request["evidence"] if row["kind"] == "observation_window"
    )
    request["input"]["constraint_checks"] = [
        {
            "check_id": "ACT-INSP-01-TK-101-PRE-01",
            "description": "Tank level above 1.8 m",
            "outcome": "pass",
            "evidence_ids": [observation],
        }
    ]
    response = InspectionPlanningAgent().run(request)

    assert response["status"] != "error"
    option = next(
        o for o in response["result"]["options"] if o["option_id"] == "ACT-INSP-01-TK-101"
    )
    assert observation in option["precondition_checks"][0]["evidence_ids"]
    assert observation in option["evidence_ids"]
    consumed = set(response["consumed_evidence_ids"])
    assert observation in consumed
    assert set(attached_report_ids(request)) <= consumed


def test_invalid_request_returns_an_error_response() -> None:
    """A request that fails the contract is answered with an error instead of raising.

    Independent: yes, because the request is made invalid in the test.
    """
    request = make_runtime_request()
    request["input"]["constraint_checks"] = [
        {"check_id": "X", "description": "d", "outcome": "maybe", "evidence_ids": []}
    ]
    response = InspectionPlanningAgent().run(request)
    assert response["status"] == "error"
    assert any(issue["code"] == "INVALID_REQUEST" for issue in response["issues"])
    assert set(attached_report_ids(request)) <= set(response["consumed_evidence_ids"])
