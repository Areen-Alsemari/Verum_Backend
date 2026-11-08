"""Tests for evidence-backed inspection precondition evaluation."""

from __future__ import annotations

from typing import Any

from verum.agents.inspection_planning.preconditions import (
    evaluate_preconditions,
)


def make_request(
    constraint_checks: list[dict[str, Any]],
    target_asset_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a minimal request for precondition tests."""
    return {
        "evidence": [
            {
                "evidence_id": "EV-001",
                "kind": "declared_reference",
                "source_ref": "reference:catalog",
                "available_at_s": 0.0,
                "content_sha256": "a" * 64,
                "root_evidence_ids": [],
                "provenance": "declared_design",
            }
        ],
        "input": {
            "constraint_checks": constraint_checks,
            "target_asset_ids": target_asset_ids or ["TK-101"],
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
    """All explicitly supported checks allow human review.

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
                "evidence_ids": ["EV-001"],
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
    """Evidence IDs absent from the request cannot establish a precondition.

    Independent: yes, because the check references an unregistered evidence ID.
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
                "evidence_ids": ["EV-001"],
            },
        ]
    )

    checks, feasibility = evaluate_preconditions(
        make_action(), request, "TK-101"
    )

    assert feasibility == "unknown"
    assert [check["outcome"] for check in checks] == ["unknown", "pass"]


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
                "evidence_ids": ["EV-001"],
            },
        ],
        ["TK-101", "TK-102"],
    )

    checks, feasibility = evaluate_preconditions(
        make_action(), request, "TK-101"
    )

    assert feasibility == "unknown"
    assert [check["outcome"] for check in checks] == ["unknown", "unknown"]
