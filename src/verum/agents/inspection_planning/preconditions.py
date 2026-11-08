
"""Evidence-backed evaluation of inspection action preconditions."""

from __future__ import annotations

from typing import Any


def evaluate_preconditions(
    action: dict[str, Any],
    request: dict[str, Any],
    target_asset: str,
) -> tuple[list[dict[str, Any]], str]:
    """Evaluate catalog preconditions using only scoped, evidenced checks."""
    inputs = request["input"]
    known_evidence = {row["evidence_id"] for row in request["evidence"]}
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

        supported = (
            len(inputs["target_asset_ids"]) == 1
            and inputs["target_asset_ids"][0] == target_asset
            and bool(matching)
            and bool(evidence_ids)
            and evidence_ids <= known_evidence
            and len(outcomes) == 1
        )

        outcome = next(iter(outcomes)) if supported else "unknown"

        checks.append(
            {
                "check_id": f"{action['action_id']}-PRE-{index:02d}",
                "description": description,
                "outcome": outcome,
                "evidence_ids": sorted(evidence_ids & known_evidence),
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
