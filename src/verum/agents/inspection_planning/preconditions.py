
"""Evidence-backed evaluation of inspection action preconditions."""

from __future__ import annotations

from typing import Any

EVIDENCE_TYPES = {
    "observation_window": ("observations:", "simulated_observation"),
    "observation_representation": ("features:", "derived_observation"),
    "inspection_result": ("inspection_result:", "simulated_inspection"),
}

WORKFLOW_TYPE = ("inspection_request:", "simulated_workflow")

PERMIT_TERMS = ("permit", "approval", "access", "permitted")


def _is_permit_precondition(description: str) -> bool:
    """Identify preconditions requiring explicit authorization."""
    normalized = description.casefold()
    return any(term in normalized for term in PERMIT_TERMS)


def _valid_evidence(
    evidence_ids: set[str],
    evidence: dict[str, dict[str, Any]],
    permit_required: bool,
) -> bool:
    """Check evidence type, source prefix, and provenance."""
    if not evidence_ids:
        return False

    expected = {"inspection_request": WORKFLOW_TYPE} if permit_required else EVIDENCE_TYPES

    for evidence_id in evidence_ids:
        row = evidence.get(evidence_id)
        if row is None:
            return False

        prefix, provenance = expected.get(row["kind"], ("", ""))

        if (
            not prefix
            or not row["source_ref"].startswith(prefix)
            or row["provenance"] != provenance
        ):
            return False

    return True


def _approved_workflow_exists(
    evidence_ids: set[str],
    evidence: dict[str, dict[str, Any]],
    workflows: list[dict[str, Any]],
    action_id: str,
    target_asset: str,
) -> bool:
    """Require a matching, explicitly approved workflow request."""
    workflow_by_source = {
        "inspection_request:" + row["request_id"]: row
        for row in workflows
    }

    matched = []

    for evidence_id in evidence_ids:
        row = evidence.get(evidence_id)
        if row is None:
            return False

        workflow = workflow_by_source.get(row["source_ref"])
        if workflow is None:
            return False

        approval = workflow["human_approval"]

        if (
            workflow["action_id"] != action_id
            or workflow["target_asset"] != target_asset
            or approval["status"] != "APPROVED"
            or not approval.get("work_permit_number", "").strip()
        ):
            return False

        matched.append(workflow)

    return bool(matched)


def evaluate_preconditions(
    action: dict[str, Any],
    request: dict[str, Any],
    target_asset: str,
) -> tuple[list[dict[str, Any]], str]:
    """Evaluate catalog preconditions using scoped, registered evidence."""
    inputs = request["input"]
    evidence = {
        row["evidence_id"]: row
        for row in request["evidence"]
    }
    workflows = inputs.get("workflow_requests", [])
    target_is_unambiguous = (
        inputs["target_asset_ids"] == [target_asset]
    )

    checks: list[dict[str, Any]] = []

    for index, description in enumerate(action["preconditions"], start=1):
        matching = [
            row
            for row in inputs["constraint_checks"]
            if row["description"] == description
        ]

        evidence_ids = {
            evidence_id
            for row in matching
            for evidence_id in row["evidence_ids"]
        }
        outcomes = {row["outcome"] for row in matching}
        permit_required = _is_permit_precondition(description)

        valid = (
            target_is_unambiguous
            and bool(matching)
            and len(outcomes) == 1
            and _valid_evidence(evidence_ids, evidence, permit_required)
        )

        if valid and permit_required:
            valid = _approved_workflow_exists(
                evidence_ids,
                evidence,
                workflows,
                action["action_id"],
                target_asset,
            )

        outcome = next(iter(outcomes)) if valid else "unknown"

        checks.append(
            {
                "check_id": f"{action['action_id']}-PRE-{index:02d}",
                "description": description,
                "outcome": outcome,
                "evidence_ids": sorted(evidence_ids & evidence.keys()),
            }
        )

    outcomes = {check["outcome"] for check in checks}

    if "fail" in outcomes:
        feasibility = "blocked"
    elif checks and outcomes == {"pass"}:
        feasibility = "eligible_for_human_review"
    else:
        feasibility = "unknown"

    return checks, feasibility