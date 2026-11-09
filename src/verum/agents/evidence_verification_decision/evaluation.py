"""Agent 8 role-view evaluation; not independent field validation."""

from __future__ import annotations

import copy
import json
from collections import Counter
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

from verum.agents.common.registry import EvidenceRegistry
from verum.agents.common.validation import check_request, check_response
from verum.agents.evidence_verification_decision.agent import (
    EvidenceVerificationDecisionAgent,
)
from verum.agents.evidence_verification_decision.evidence import check_proposal

FIXTURES = Path(__file__).resolve().parents[4] / "contracts/agents/v1/examples"

REPORT_FILES = {
    "diagnosis_report": "diagnostic_reasoning.response.json",
    "inspection_plan_report": "inspection_planning.response.json",
    "inspection_quality_report": "inspection_quality_documentation.response.json",
}

LABEL_MEANING = "Contract and rule consistency over 36,012 inputs, not accuracy."

LIMITATIONS = (
    "The 36,000 temporal labels use the same rule as Agent 8. "
    "A one-line baseline also matches all 36,000. "
    "The 12 inspection records do not establish independent accuracy. "
    "Role-view records use registered contract fixtures, not independently verified evidence. "
    "Measurement usability needs record-specific provenance, quality, and scope verification. "
    "Inspection records are retrospective reviews, not registered measurement proposals "
    "or independently verified Agent 7 reports. Their decisions test the conservative "
    "no-proposal path, not individual measurement quality. "
    "No diagnostic or equipment-condition accuracy is claimed."
)


def evaluate_reference_example(
    example_id: str,
    inputs: dict[str, Any],
) -> dict[str, bool | None]:
    """Legacy synthetic adapter; not an Agent 8 accuracy metric."""
    proposal = inputs["proposal"]
    available_at = proposal["available_relative_s"]
    cutoff = inputs["query_time_s"]
    source = f"reference:{proposal['tag_id']}"
    evidence_id = f"reference:{example_id}"

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
            proposal["quality_flag"] == "good" if proposal["quality_flag"] is not None else None
        ),
        scope_supported=True,
    )

    return {
        "time_admissible": result["time_admissible"],
        "measurement_usable": result["usable"],
        "equipment_condition_confirmed": False,
    }


@lru_cache(maxsize=1)
def _base_request() -> dict[str, Any]:
    """Load and register complete contract interface fixtures."""
    request: dict[str, Any] = json.loads(
        (FIXTURES / "evidence_verification_decision.request.json").read_text()
    )
    registry = EvidenceRegistry.from_rows(request["context"], request["evidence"])

    for field, filename in REPORT_FILES.items():
        report = json.loads((FIXTURES / filename).read_text())
        request["input"][field] = report
        registry.add_report(report)

    request["evidence"] = registry.rows()
    check_request(request)
    return request


def _new_request(example_id: str) -> dict[str, Any]:
    """Copy the registered contract request for an evaluation case."""
    request = copy.deepcopy(_base_request())
    request["request_id"] = f"evaluation-{example_id}"
    return request


def _reference_request(record: Any) -> dict[str, Any]:
    """Build a reference proposal without inventing provenance."""
    request = _new_request(record.example_id)
    proposal = record.input["proposal"]

    offset = proposal["available_relative_s"] - record.input["query_time_s"]
    claimed_at = request["context"]["as_of_s"] + offset

    request["input"]["evidence_proposals"] = [
        {
            "proposal_id": record.example_id,
            "source_ref": f"reference:{proposal['tag_id']}",
            "claimed_available_at_s": claimed_at,
            "claimed_evidence_ids": ["source-observations"],
        }
    ]
    return request


def _inspection_request(record: Any) -> dict[str, Any]:
    """Build a conservative retrospective inspection request."""
    request = _new_request(record.example_id)
    inspection = record.input

    request["request_id"] = f"evaluation-{record.example_id}-{inspection['action_id']}"

    # No independently registered measurement proposal exists.
    request["input"]["evidence_proposals"] = []
    return request


def evaluate_full_agent_request(
    request: dict[str, Any],
) -> dict[str, Any]:
    """Execute Agent 8 and validate the complete response."""
    check_request(request)
    response = EvidenceVerificationDecisionAgent().run(request)
    check_response(request, response)

    if response["status"] == "error" or response["result"] is None:
        raise ValueError(f"Agent 8 evaluation failed: {response.get('issues')}")
    return response


def _run_record(record: Any) -> tuple[str, dict[str, Any]]:
    """Run Agent 8 and enforce conservative safety invariants."""
    if record.use == "reference_input_target_pair":
        request = _reference_request(record)
        category = "reference"
    elif record.use == "inspection_record_quality":
        request = _inspection_request(record)
        category = "inspection"
    else:
        raise ValueError(f"Unsupported record use: {record.use}")

    response = evaluate_full_agent_request(request)
    result = response["result"]

    if result["equipment_condition_confirmed"] is not False:
        raise ValueError("Unsupported equipment confirmation")
    if result["automatic_action_authorized"] is not False:
        raise ValueError("Unsupported automatic action")
    if result["human_decision_required"] is not True:
        raise ValueError("Missing human review requirement")

    return category, result


def _score_reference(
    record: Any,
    result: dict[str, Any],
    scores: Counter[str],
) -> None:
    """Compare the actual time check with the synthetic time label."""
    checks = result["evidence_checks"]

    if len(checks) != 1:
        raise ValueError(f"Expected one check: {record.example_id}")

    check = checks[0]
    if check["proposal_id"] != record.example_id:
        raise ValueError(f"Incorrect proposal: {record.example_id}")

    scores["time_compared"] += 1

    if check["time_admissible"] == record.target["time_admissible"]:
        scores["time_matched"] += 1

    scores[f"usable:{check['usable']}"] += 1
    scores[f"provenance:{check['provenance_verified']}"] += 1


def _score_inspection(
    record: Any,
    result: dict[str, Any],
    scores: Counter[str],
) -> None:
    """Summarize inspection metadata without fabricating evidence."""
    if result["evidence_checks"]:
        raise ValueError(f"Unexpected inspection check: {record.example_id}")

    inspection = record.input
    target = record.target

    scores[f"workflow:{inspection['workflow_status']}"] += 1
    scores[f"evidence_status:{inspection['evidence_status']}"] += 1
    scores[f"timing_verified:{inspection['workflow_timing_verified']}"] += 1
    scores[f"record_complete:{inspection['measurement_record_complete']}"] += 1
    scores[f"target_decision:{target['decision']}"] += 1
    scores[f"condition_acceptance:{target['condition_acceptance_supported']}"] += 1


def _summary(
    counts: Counter[str],
    decisions: Counter[str],
    inspections: Counter[str],
    scores: Counter[str],
    inspection_labels: Counter[str],
) -> dict[str, Any]:
    """Separate agent outcomes from synthetic label diagnostics."""
    return {
        "agent_run_evaluation": {
            "reference_count": counts["reference"],
            "inspection_count": counts["inspection"],
            "error_count": 0,
            "decision_states": dict(sorted(decisions.items())),
            "inspection_decision_states": dict(sorted(inspections.items())),
            "admission_check_distribution": {
                key: value
                for key, value in sorted(scores.items())
                if key.startswith(("usable:", "provenance:"))
            },
        },
        "synthetic_label_diagnostics": {
            "time_rules_compared": scores["time_compared"],
            "time_rules_agreed": scores["time_matched"],
            "interpretation": (
                "Agreement with synthetic temporal rules only; "
                "not independent Agent 8 decision accuracy."
            ),
        },
        "inspection_record_descriptors": dict(sorted(inspection_labels.items())),
        "label_meaning": LABEL_MEANING,
        "evaluation_limitations": LIMITATIONS,
    }


def evaluate_reference_dataset(
    records: Iterable[Any],
) -> dict[str, Any]:
    """Evaluate role-view records through validated Agent 8 runs."""
    counts: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    inspections: Counter[str] = Counter()
    scores: Counter[str] = Counter()
    inspection_labels: Counter[str] = Counter()

    for record in records:
        if record.use not in (
            "reference_input_target_pair",
            "inspection_record_quality",
        ):
            continue

        category, result = _run_record(record)
        counts[category] += 1

        if category == "reference":
            decisions[result["decision_state"]] += 1
            _score_reference(record, result, scores)
        else:
            inspections[result["decision_state"]] += 1
            _score_inspection(record, result, inspection_labels)

    return _summary(counts, decisions, inspections, scores, inspection_labels)
