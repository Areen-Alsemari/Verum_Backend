
"""Tests for evidence-backed inspection precondition evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from verum.agents.inspection_planning.agent import InspectionPlanningAgent
from verum.agents.inspection_planning.preconditions import (
    evaluate_preconditions,
)


def make_request(
    constraint_checks: list[dict[str, Any]],
    target_asset_ids: list[str] | None = None,
    approval_status: str = "APPROVED",
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
                    "action_id": "ACT-INSP-01",
                    "target_asset": "TK-101",
                    "human_approval": {
                        "status": approval_status,
                        "work_permit_number": (
                            "PERMIT-001"
                            if approval_status == "APPROVED"
                            else None
                        ),
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


def test_all_sourced_preconditions_pass() -> None:
    """All supported checks allow human review.

    Independent: yes, because this tests the evaluator without the agent runtime.
    """
    request = make_request(
        [
            {
                "check_id": "CHK-01",
                "description": "Tank level above 1.8 m",
                "outcome": "pass",
                "evidence_ids": ["EV-001"],
            },
            {
                "check_id": "CHK-02",
                "description": "Authorised permit issued by the approval",
                "outcome": "pass",
                "evidence_ids": ["EV-002"],
            },
        ]
    )

    checks, feasibility = evaluate_preconditions(
        make_action(), request, "TK-101"
    )

    assert feasibility == "eligible_for_human_review"
    assert [check["outcome"] for check in checks] == ["pass", "pass"]


def test_missing_preconditions_remain_unknown() -> None:
    """Missing checks cannot be treated as passing.

    Independent: yes, because the request contains no constraint evidence.
    """
    checks, feasibility = evaluate_preconditions(
        make_action(), make_request([]), "TK-101"
    )

    assert feasibility == "unknown"
    assert [check["outcome"] for check in checks] == ["unknown", "unknown"]


def test_failed_precondition_blocks_the_action() -> None:
    """An evidenced failed precondition blocks human review.

    Independent: yes, because the evaluator receives an explicit failed check.
    """
    request = make_request(
        [
            {
                "check_id": "CHK-01",
                "description": "Tank level above 1.8 m",
                "outcome": "fail",
                "evidence_ids": ["EV-001"],
            }
        ]
    )

    checks, feasibility = evaluate_preconditions(
        make_action(), request, "TK-101"
    )

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
                "check_id": "CHK-01",
                "description": "Tank level above 1.8 m",
                "outcome": "pass",
                "evidence_ids": ["EV-MISSING"],
            },
            {
                "check_id": "CHK-02",
                "description": "Authorised permit issued by the approval",
                "outcome": "pass",
                "evidence_ids": ["EV-002"],
            },
        ]
    )

    checks, feasibility = evaluate_preconditions(
        make_action(), request, "TK-101"
    )

    assert feasibility == "unknown"
    assert [check["outcome"] for check in checks] == ["unknown", "pass"]


def test_pending_approval_does_not_satisfy_permit() -> None:
    """Pending approval cannot establish permit eligibility.

    Independent: yes, because the workflow has not received approval.
    """
    request = make_request(
        [
            {
                "check_id": "CHK-01",
                "description": "Tank level above 1.8 m",
                "outcome": "pass",
                "evidence_ids": ["EV-001"],
            },
            {
                "check_id": "CHK-02",
                "description": "Authorised permit issued by the approval",
                "outcome": "pass",
                "evidence_ids": ["EV-002"],
            },
        ],
        approval_status="PENDING",
    )

    checks, feasibility = evaluate_preconditions(
        make_action(), request, "TK-101"
    )

    assert feasibility == "unknown"
    assert [check["outcome"] for check in checks] == ["pass", "unknown"]


def test_rejected_approval_does_not_satisfy_permit() -> None:
    """Rejected approval cannot establish permit eligibility.

    Independent: yes, because the workflow explicitly records rejection.
    """
    request = make_request(
        [
            {
                "check_id": "CHK-01",
                "description": "Tank level above 1.8 m",
                "outcome": "pass",
                "evidence_ids": ["EV-001"],
            },
            {
                "check_id": "CHK-02",
                "description": "Authorised permit issued by the approval",
                "outcome": "pass",
                "evidence_ids": ["EV-002"],
            },
        ],
        approval_status="REJECTED",
    )

    checks, feasibility = evaluate_preconditions(
        make_action(), request, "TK-101"
    )

    assert feasibility == "unknown"
    assert [check["outcome"] for check in checks] == ["pass", "unknown"]


def test_conflicting_checks_remain_unknown() -> None:
    """Conflicting outcomes cannot establish a precondition.

    Independent: yes, because two checks disagree about the same condition.
    """
    request = make_request(
        [
            {
                "check_id": "CHK-01",
                "description": "Tank level above 1.8 m",
                "outcome": "pass",
                "evidence_ids": ["EV-001"],
            },
            {
                "check_id": "CHK-02",
                "description": "Tank level above 1.8 m",
                "outcome": "fail",
                "evidence_ids": ["EV-001"],
            },
        ]
    )

    checks, feasibility = evaluate_preconditions(
        make_action(), request, "TK-101"
    )

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
                "check_id": "CHK-01",
                "description": "Tank level above 1.8 m",
                "outcome": "pass",
                "evidence_ids": ["EV-001"],
            },
            {
                "check_id": "CHK-02",
                "description": "Authorised permit issued by the approval",
                "outcome": "pass",
                "evidence_ids": ["EV-002"],
            },
        ],
        ["TK-101", "TK-102"],
    )

    checks, feasibility = evaluate_preconditions(
        make_action(), request, "TK-101"
    )

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
    return json.loads(fixture.read_text(encoding="utf-8"))


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

    assets = {
        asset["asset_id"]: asset["kind"]
        for asset in request["input"]["assets"]
    }
    actions = {
        action["action_id"]: action
        for action in request["input"]["catalog"]
    }

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
    assert all(
        option["feasibility"] == "unknown"
        for option in response["result"]["options"]
    )


def test_runtime_respects_inspection_budget() -> None:
    """Actions exceeding the supplied budget are marked blocked.

    Independent: yes, because the budget is changed for this test only.
    """
    request = make_runtime_request()
    request["input"]["budget"]["max_cost_usd"] = 100.0

    response = InspectionPlanningAgent().run(request)

    expensive_options = [
        option
        for option in response["result"]["options"]
        if option["cost_usd"] > 100.0
    ]

    assert expensive_options
    assert all(
        option["feasibility"] == "blocked"
        for option in expensive_options
    )


def test_runtime_does_not_invent_diagnostic_hypotheses() -> None:
    """An empty diagnostic hypothesis list produces no hypothesis links.

    Independent: yes, because the fixture diagnostic report has no hypotheses.
    """
    request = make_runtime_request()
    response = InspectionPlanningAgent().run(request)

    assert request["input"]["diagnosis_report"]["result"]["hypotheses"] == []
    assert all(
        option["addresses_hypothesis_ids"] == []
        for option in response["result"]["options"]
    )
