"""Adapter for Agent 8 reference admission exercises, not production evidence."""

from __future__ import annotations

from typing import Any

from verum.agents.evidence_verification_decision.evidence import check_proposal


def evaluate_reference_example(example_id: str, inputs: dict[str, Any]) -> dict[str, bool | None]:
    """Translate one synthetic reference exercise into evidence admission checks."""
    proposal = inputs["proposal"]
    available_at = proposal["available_relative_s"]
    cutoff = inputs["query_time_s"]
    source = f"reference:{proposal['tag_id']}"
    evidence_id = f"reference:{example_id}"

    # Synthetic registry metadata is constructed only for benchmark evaluation.
    # It must never be used to establish real-world provenance or scope.
    result = check_proposal(
        {
            "proposal_id": example_id,
            "source_ref": source,
            "claimed_available_at_s": available_at,
            "claimed_evidence_ids": [evidence_id],
        },
        {
            evidence_id: {
                "evidence_id": evidence_id,
                "source_ref": source,
                "available_at_s": available_at,
            }
        },
        cutoff,
        quality_acceptable=(
            proposal["quality_flag"] == "good"
            if proposal["quality_flag"] is not None
            else None
        ),
        scope_supported=True,
    )
    return {
        "time_admissible": result["time_admissible"],
        "measurement_usable": result["usable"],
        "equipment_condition_confirmed": False,
    }
