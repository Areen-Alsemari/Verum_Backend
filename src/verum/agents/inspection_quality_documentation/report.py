
"""Build conservative maintenance reports from verified agent evidence."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Protocol

import jsonschema
from referencing import Registry, Resource

from verum.contracts.agent_interfaces import content_hash
from verum.contracts.paths import repo_root

AGENT_8 = "evidence_verification_decision"
AGENT_6 = "inspection_planning"

EXPECTED_ROLES = (
    "data_preparation",
    "anomaly_detection",
    "predictive_health",
    "maintenance_recommendation",
    "diagnostic_reasoning",
    "inspection_planning",
    "inspection_quality_documentation",
    "evidence_verification_decision",
)


class VerifiedReportBundle(Protocol):
    """Expose the fields supplied by a verified analysis bundle."""

    @property
    def context(self) -> dict[str, Any]:
        """Return the analysis context."""
        ...

    @property
    def responses(self) -> dict[str, dict[str, Any]]:
        """Return validated agent responses."""
        ...

    @property
    def evidence(self) -> list[dict[str, Any]]:
        """Return registered evidence records."""
        ...

    @property
    def issues(self) -> tuple[dict[str, str], ...]:
        """Return bundle-level issues."""
        ...


def _check_finite(value: Any) -> None:
    """Reject non-finite numeric values anywhere in the supplied data."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite numeric value in verified bundle")

    if isinstance(value, dict):
        for item in value.values():
            _check_finite(item)

    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_finite(item)


def _report_validator() -> jsonschema.Draft202012Validator:
    """Load the maintenance report schema with its local common references."""
    root: Path = repo_root()

    report_path = root / "contracts" / "reports" / "maintenance_report.schema.json"
    common_path = root / "contracts" / "agents" / "v1" / "common.schema.json"

    report_schema = json.loads(report_path.read_text(encoding="utf-8"))
    common_schema = json.loads(common_path.read_text(encoding="utf-8"))

    registry: Registry[Any] = Registry().with_resource(
        common_schema["$id"],
        Resource.from_contents(common_schema),
    )

    jsonschema.Draft202012Validator.check_schema(report_schema)

    return jsonschema.Draft202012Validator(
        report_schema,
        registry=registry,
        format_checker=jsonschema.FormatChecker(),
    )


def _registered_evidence(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index evidence while rejecting duplicate or malformed identifiers."""
    registered: dict[str, dict[str, Any]] = {}

    for row in rows:
        identifier = row.get("evidence_id")

        if not isinstance(identifier, str) or not identifier:
            raise ValueError("Evidence record has an invalid identifier")

        if identifier in registered:
            raise ValueError(f"Duplicate evidence identifier: {identifier}")

        registered[identifier] = row

    return registered


def _checked_evidence_ids(
    identifiers: list[str],
    registered: dict[str, dict[str, Any]],
) -> list[str]:
    """Preserve cited identifiers and reject missing or repeated evidence."""
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Duplicate cited evidence identifier")

    for identifier in identifiers:
        if identifier not in registered:
            raise ValueError(f"Unknown evidence identifier: {identifier}")

    return list(identifiers)


def _source_reports(
    context: dict[str, Any],
    responses: dict[str, dict[str, Any]],
    registered: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Verify report identities, contexts, and registered content hashes."""
    sources: list[dict[str, Any]] = []
    seen_report_ids: set[str] = set()

    for role, response in sorted(responses.items()):
        if role not in EXPECTED_ROLES:
            raise ValueError(f"Unknown agent role: {role}")

        if response.get("agent") != role:
            raise ValueError(f"Agent role mismatch: {role}")

        if response.get("context") != context:
            raise ValueError(f"Mixed analysis context: {role}")

        report_id = response.get("report_id")

        if not isinstance(report_id, str) or not report_id:
            raise ValueError(f"Invalid report identifier: {role}")

        if report_id in seen_report_ids:
            raise ValueError(f"Duplicate source report: {report_id}")

        seen_report_ids.add(report_id)

        record = registered.get(report_id)

        if record is None:
            raise ValueError(f"Unregistered source report: {report_id}")

        if record.get("kind") != "agent_report":
            raise ValueError(f"Invalid source report evidence kind: {report_id}")

        expected_hash = content_hash(response)

        if record.get("content_sha256") != expected_hash:
            raise ValueError(f"Source report hash mismatch: {report_id}")

        sources.append({
            "report_id": report_id,
            "agent": role,
            "content_sha256": expected_hash,
        })

    return sources


def _inspection_options(
    responses: dict[str, dict[str, Any]],
    registered: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Copy planning options without changing feasibility or numeric values."""
    planning = responses.get(AGENT_6)

    if planning is None:
        return []

    report_id = planning["report_id"]
    options: list[dict[str, Any]] = []

    for option in planning["result"]["options"]:
        citations = _checked_evidence_ids(
            option["evidence_ids"],
            registered,
        )

        options.append({
            "action_id": option["action_id"],
            "target_asset": option["target_asset"],
            "feasibility": option["feasibility"],
            "cost_usd": option["cost_usd"],
            "duration_min": option["duration_min"],
            "source_report_id": report_id,
            "evidence_ids": citations,
        })

    return options


def build_report(bundle: VerifiedReportBundle) -> dict[str, Any]:
    """Assemble a schema-validated, advisory-only maintenance report."""
    context = bundle.context
    responses = bundle.responses

    decision = responses.get(AGENT_8)

    if decision is None:
        raise ValueError(
            "Agent 8 assessment is required before building a maintenance report"
        )

    _check_finite(context)
    _check_finite(responses)
    _check_finite(bundle.evidence)

    registered = _registered_evidence(bundle.evidence)

    sources = _source_reports(
        context,
        responses,
        registered,
    )

    decision_id = decision["report_id"]
    result = decision["result"]

    if result["human_decision_required"] is not True:
        raise ValueError("Agent 8 must require a human decision")

    if result["automatic_action_authorized"] is not False:
        raise ValueError("Automatic action cannot be authorized")

    if result["equipment_condition_confirmed"] is not False:
        raise ValueError("Equipment condition cannot be confirmed")

    summary = result["summary"]

    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Agent 8 assessment summary is required")

    assessment_citations = _checked_evidence_ids(
        decision["consumed_evidence_ids"],
        registered,
    )

    findings = [{
        "finding_id": f"assessment-{decision_id}",
        "kind": "assessment",
        "statement": summary,
        "measurement": None,
        "source_report_id": decision_id,
        "evidence_ids": assessment_citations,
    }]

    next_steps: list[dict[str, Any]] = []

    for step in result["next_steps"]:
        next_steps.append({
            "description": step["description"],
            "source_report_id": decision_id,
            "evidence_ids": _checked_evidence_ids(
                step["evidence_ids"],
                registered,
            ),
        })

    missing_information = [
        f"Missing agent report: {role}"
        for role in EXPECTED_ROLES
        if role not in responses
    ]

    for issue in bundle.issues:
        missing_information.append(
            f"Bundle issue: {issue['code']}: {issue['message']}"
        )

    limitations: list[str] = []

    for _role, response in sorted(responses.items()):
        for limitation in response["limitations"]:
            if limitation not in limitations:
                limitations.append(limitation)

    limitations.append(
        "Advisory assessment only; human review is required "
        "and equipment condition is not confirmed."
    )

    report: dict[str, Any] = {
        "report_version": "1.0.0",
        "report_id": f"maintenance-{context['analysis_id']}",
        "context": dict(context),
        "report_type": "maintenance_assessment",
        "title": "Maintenance assessment",
        "review_status": "human_review_required",
        "assessment_state": result["decision_state"],
        "source_reports": sources,
        "findings": findings,
        "inspection_options": _inspection_options(
            responses,
            registered,
        ),
        "next_steps": next_steps,
        "missing_information": missing_information,
        "limitations": limitations,
        "narrative": {
            "provider": "template",
            "model": None,
            "prompt_id": None,
            "text": summary,
            "source_report_ids": [decision_id],
        },
        "advisory_only": True,
        "human_decision_required": True,
        "automatic_action_authorized": False,
        "equipment_condition_confirmed": False,
    }

    _check_finite(report)
    _report_validator().validate(report)

    return report
