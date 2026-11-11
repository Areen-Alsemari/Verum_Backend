"""Versioned message validation for the eight advisory agent roles.

Messages are checked for shape, causal evidence, matching analysis context and supported scope.
This module defines transport boundaries only and implements no agent or model.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

import jsonschema
from referencing import Resource
from referencing.jsonschema import DRAFT202012

from verum.contracts.paths import repo_root
from verum.contracts.schemas import schema_registry
from verum.provenance import canonical_json

FORBIDDEN = frozenset({
    "ground_truth", "fault_truth", "hydraulic_state", "solver_diagnostics", "mass_ledger",
    "observation_audit", "simulation_rejected", "validity_windows", "boundary_state",
    "target", "labels", "supervised_loss_mask", "lineage", "episode_id",
    "timestamp_utc",
})
PREFIXES = {
    "observation_window": ("observations:", "simulated_observation"),
    "observation_representation": ("features:", "derived_observation"),
    "declared_reference": ("reference:", "declared_design"),
    "inspection_result": ("inspection_result:", "simulated_inspection"),
    "inspection_request": ("inspection_request:", "simulated_workflow"),
    "history": ("history:", "synthetic_history"),
    "agent_report": ("report:", "derived_agent_output"),
}


class Agent(Protocol):
    """A synchronous advisory component with a versioned JSON message boundary."""

    def run(self, request: dict[str, Any]) -> dict[str, Any]: ...


def contract_directory() -> Path:
    return repo_root() / "contracts" / "agents" / "v1"


def content_hash(value: Any) -> str:
    """Hash canonical JSON content without relying on file formatting."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validators(directory: Path | None = None) -> dict[str, jsonschema.Draft202012Validator]:
    """Load the role schemas and resolve references from local resources only."""
    base = directory or contract_directory()
    registry = schema_registry()
    schemas = []
    for path in sorted(base.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(
            schema["$id"], Resource.from_contents(schema, DRAFT202012)
        )
        if path.name != "common.schema.json":
            schemas.append((path.name.removesuffix(".schema.json"), schema))
    return {
        key: jsonschema.Draft202012Validator(
            schema, registry=registry, format_checker=jsonschema.FormatChecker()
        )
        for key, schema in schemas
    }


def _nodes(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _nodes(child)


def _check_visible(value: Any) -> None:
    for node in _nodes(value):
        if isinstance(node, dict) and FORBIDDEN.intersection(node):
            raise ValueError("hidden supervision or feature metadata in message")
        if isinstance(node, float) and not math.isfinite(node):
            raise ValueError("non-finite numeric value in message")


def _references(value: Any) -> set[str]:
    found: set[str] = set()
    for node in _nodes(value):
        if isinstance(node, dict):
            for key, child in node.items():
                if key.endswith("evidence_ids") and key != "claimed_evidence_ids":
                    found.update(child)
    return found


def _evidence(request: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = request["evidence"]
    found = {row["evidence_id"]: row for row in rows}
    if len(found) != len(rows):
        raise ValueError("duplicate evidence identifier")
    for row in rows:
        prefix, provenance = PREFIXES[row["kind"]]
        if not row["source_ref"].startswith(prefix) or row["provenance"] != provenance:
            raise ValueError("evidence kind and source disagree")
        if row["available_at_s"] > request["context"]["as_of_s"]:
            raise ValueError("future content cannot enter an agent request")
        roots = row["root_evidence_ids"]
        derived = {"agent_report", "observation_representation"}
        if row["kind"] not in derived and roots != [row["evidence_id"]]:
            raise ValueError("source evidence must identify itself as its root")
        if row["kind"] == "observation_representation" and not roots:
            raise ValueError("observation representation needs original observation roots")
        for ident in roots:
            root = found.get(ident)
            if root is None or root["kind"] in derived:
                raise ValueError("unresolved or derived root evidence")
            if row["kind"] == "observation_representation" and (
                root["kind"] != "observation_window"
            ):
                raise ValueError("observation representation has a non-observation source")
            if root["available_at_s"] > row["available_at_s"]:
                raise ValueError("derived evidence predates its source")
    if not _references(request["input"]) <= found.keys():
        raise ValueError("input cites evidence absent from its registry")
    return found


def _upstream_reports(inputs: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for key, value in inputs.items():
        if key.endswith("_report") and value is not None:
            yield value
            yield from _upstream_reports(value["result"] or {})


def validate_request(
    request: dict[str, Any], checks: dict[str, jsonschema.Draft202012Validator] | None = None,
) -> None:
    """Validate a request including report provenance and a causal observation representation."""
    available = checks if checks is not None else validators()
    if request.get("message_type") != "request":
        raise ValueError("expected an agent request")
    available[request["agent"]].validate(request)
    _check_visible(request)
    evidence = _evidence(request)
    for report in _upstream_reports(request["input"]):
        if report["context"] != request["context"]:
            raise ValueError("upstream report belongs to a different analysis snapshot")
        row = evidence.get(report["report_id"])
        if row is None or row["kind"] != "agent_report":
            raise ValueError("upstream report is absent from evidence registry")
        if row["source_ref"] != "report:" + report["report_id"]:
            raise ValueError("upstream report source does not match its identifier")
        if row["content_sha256"] != content_hash(report):
            raise ValueError("upstream report content hash mismatch")
        if not _references(report) <= evidence.keys():
            raise ValueError("upstream report cites unavailable evidence")
        roots = {
            root for ident in report["consumed_evidence_ids"]
            for root in evidence[ident]["root_evidence_ids"]
        }
        if set(row["root_evidence_ids"]) != roots:
            raise ValueError("upstream report discarded or changed original evidence roots")
    observations = request["input"].get("observations")
    if observations is not None:
        _check_observations(observations)
        field = "summary" if observations["representation"] == "summary_v1" else "sequence"
        digest = content_hash(observations[field])
        if not any(
            evidence[ident]["kind"] == "observation_representation"
            and evidence[ident]["content_sha256"] == digest
            for ident in observations["evidence_ids"]
        ):
            raise ValueError("observation representation is not bound to its source evidence")
    for result in request["input"].get("inspection_results", []):
        if result["performed_at_t_sim_s"] > request["context"]["as_of_s"]:
            raise ValueError("inspection was performed after the request cutoff")
        ident = "inspection_result:" + result["result_id"]
        if not any(
            row["source_ref"] == ident and row["content_sha256"] == content_hash(result)
            for row in evidence.values()
        ):
            raise ValueError("inspection result has no available source evidence")
    for coverage in request["input"].get("process_coverage", []):
        if coverage["end_s"] < coverage["start_s"]:
            raise ValueError("process coverage ends before it starts")
        if coverage["end_s"] > request["context"]["as_of_s"]:
            raise ValueError("observed process coverage cannot extend beyond the cutoff")
    for key in ("workflow_requests", "inspection_requests"):
        for workflow in request["input"].get(key, []):
            if workflow["t_requested_sim_s"] > request["context"]["as_of_s"]:
                raise ValueError("inspection request was made after the cutoff")
            if not any(
                row["source_ref"] == "inspection_request:" + workflow["request_id"]
                and row["content_sha256"] == content_hash(workflow)
                for row in evidence.values()
            ):
                raise ValueError("inspection workflow is absent from available source evidence")
    for record in request["input"].get("history", []):
        if record["t_recorded_s"] > request["context"]["as_of_s"]:
            raise ValueError("history record was recorded after the cutoff")
    _check_recent_assessments(request)


def _check_recent_assessments(request: dict[str, Any]) -> None:
    """Recent window assessments are past windows: none after the cutoff, oldest first."""
    times = [row["as_of_s"] for row in request["input"].get("recent_anomaly_assessments", [])]
    if any(time > request["context"]["as_of_s"] for time in times):
        raise ValueError("a recent anomaly assessment is later than the request cutoff")
    if times != sorted(times):
        raise ValueError("recent anomaly assessments are not ordered by time")


def _check_observations(observations: dict[str, Any]) -> None:
    key = "signals" if observations["representation"] == "summary_v1" else "channels"
    field = "summary" if key == "signals" else "sequence"
    rows = observations[field][key]
    if len({row["tag_id"] for row in rows}) != len(rows):
        raise ValueError("duplicate signal channel")
    for row in rows:
        if key == "signals":
            if row["measured_count"] + row["missing_samples"] != row["rows_received"]:
                raise ValueError("summary sample counts disagree")
            if row["bad_quality_samples"] > row["rows_received"]:
                raise ValueError("quality count exceeds received samples")
        else:
            offsets = [sample["available_offset_s"] for sample in row["samples"]]
            if offsets != sorted(offsets):
                raise ValueError("sequence is not ordered by availability")
            for sample in row["samples"]:
                if sample["measured_offset_s"] > sample["available_offset_s"]:
                    raise ValueError("measurement occurs after its reported availability")


def validate_response(
    request: dict[str, Any], response: dict[str, Any],
    checks: dict[str, jsonschema.Draft202012Validator] | None = None,
) -> None:
    """Validate a response against its request without executing an agent."""
    available = checks if checks is not None else validators()
    validate_request(request, available)
    if response.get("message_type") != "response":
        raise ValueError("expected an agent response")
    available[request["agent"]].validate(response)
    if response["request_id"] != request["request_id"] or response["context"] != request["context"]:
        raise ValueError("response does not match request and analysis context")
    _check_visible(response)
    evidence = _evidence(request)
    consumed = set(response["consumed_evidence_ids"])
    if not consumed <= evidence.keys() or not _references(response) <= consumed:
        raise ValueError("response cites unconsumed or unavailable evidence")
    if response["result"] is not None:
        _check_result(request, response)


def _check_result(request: dict[str, Any], response: dict[str, Any]) -> None:
    result, inputs = response["result"], request["input"]
    agent = response["agent"]
    if agent == "predictive_health":
        observations = inputs["observations"]
        field = "summary" if observations["representation"] == "summary_v1" else "sequence"
        rows_key = "signals" if field == "summary" else "channels"
        units = {row["tag_id"]: row["unit"] for row in observations[field][rows_key]}
        for forecast in result["forecasts"]:
            if forecast["tag_id"] not in inputs["target_tag_ids"]:
                raise ValueError("forecast channel was not requested")
            if forecast["unit"] != units.get(forecast["tag_id"]):
                raise ValueError("forecast unit differs from the observation channel")
            interval = forecast["interval"]
            if interval is not None and (
                forecast["value"] is None or interval["upper"] < interval["lower"]
            ):
                raise ValueError("forecast interval lacks a mean or has inverted bounds")
    elif agent == "topology_dependency":
        if any(edge not in inputs["declared_connections"] for edge in result["direct_connections"]):
            raise ValueError("connection was not supplied by the declared graph")
    elif agent == "historical_asset_intelligence":
        for output_key, input_key in (
            ("facts", "declared_facts"), ("asset_records", "assets"), ("history", "history"),
        ):
            if any(row not in inputs[input_key] for row in result[output_key]):
                raise ValueError("retrieval invented a fact, asset or history record")
        if result["history_status"] == "simulated_records_available" and not result["history"]:
            raise ValueError("available history has no supplied records")
    elif agent == "inspection_planning":
        _check_plan(inputs, result)
    elif agent == "diagnostic_reasoning":
        expected = {key for key in inputs if key.endswith("_report")}
        checks = {row["check_id"]: row for row in result["upstream_checks"]}
        if checks.keys() != expected or len(checks) != len(result["upstream_checks"]):
            raise ValueError("diagnosis must account for each upstream evidence source")
        for key, check in checks.items():
            if inputs[key] is None and check["outcome"] != "unknown":
                raise ValueError("missing upstream evidence cannot pass or fail a comparison")
    elif agent == "inspection_quality_documentation":
        ids = {row["result_id"] for row in inputs["inspection_results"]}
        requests = {row["request_id"] for row in inputs["inspection_requests"]}
        source_results = {row["result_id"]: row for row in inputs["inspection_results"]}
        for row in result["record_checks"]:
            if row["result_id"] not in ids:
                raise ValueError("quality report refers to an unavailable result")
            if row["measurement_usable"] is True and (
                row["scope_supported"] is not True or not row["checks"]
                or any(check["outcome"] != "pass" for check in row["checks"])
                or source_results[row["result_id"]]["request_id"] not in requests
            ):
                raise ValueError("unknown or failed inspection checks cannot establish usability")
    elif agent == "evidence_verification_decision":
        _check_decision(request, result)


def _check_plan(inputs: dict[str, Any], result: dict[str, Any]) -> None:
    catalog = {action["action_id"]: action for action in inputs["catalog"]}
    assets = {row["asset_id"]: row["kind"] for row in inputs["assets"]}
    options = {option["option_id"]: option for option in result["options"]}
    if len(options) != len(result["options"]):
        raise ValueError("duplicate inspection option")
    for option in options.values():
        action = catalog.get(option["action_id"])
        if action is None or any(
            option[key] != action[key] for key in ("cost_usd", "duration_min")
        ):
            raise ValueError("inspection action or price differs from supplied catalog")
        if (
            option["target_asset"] not in inputs["target_asset_ids"]
            or assets.get(option["target_asset"]) != action["target_kind"]
        ):
            raise ValueError("inspection target is outside the requested assets or kind")
        checks = option["precondition_checks"]
        if option["feasibility"] == "eligible_for_human_review" and (
            any(check["outcome"] != "pass" or not check["evidence_ids"] for check in checks)
            or {check["description"] for check in checks} != set(action["preconditions"])
        ):
            raise ValueError("inspection eligibility needs every sourced precondition to pass")
        if option["expected_information_gain_bits"] is not None and (
            option["information_gain_method_id"] is None
        ):
            raise ValueError("numerical information gain needs an explicit method")
    recommended = result["recommended_option_id"]
    if recommended is not None and (
        recommended not in options or result["selection_policy_id"] is None
        or options[recommended]["feasibility"] != "eligible_for_human_review"
    ):
        raise ValueError("recommendation needs an eligible option and a declared policy")


def _check_decision(request: dict[str, Any], result: dict[str, Any]) -> None:
    inputs = request["input"]
    proposals = {row["proposal_id"]: row for row in inputs["evidence_proposals"]}
    reports = {row["proposal_id"]: row for row in result["evidence_checks"]}
    if len(reports) != len(result["evidence_checks"]) or reports.keys() != proposals.keys():
        raise ValueError("each evidence proposal needs exactly one assessment")
    for ident, proposal in proposals.items():
        row = reports[ident]
        time = proposal["claimed_available_at_s"]
        if time is not None and time > request["context"]["as_of_s"]:
            if row["time_admissible"] is not False or row["usable"] is not False:
                raise ValueError("future evidence must be rejected")
        if row["usable"] is True and any(
            row[key] is not True for key in (
                "time_admissible", "provenance_verified", "quality_acceptable", "scope_supported",
            )
        ):
            raise ValueError("evidence usability needs all admission checks")
        if row["provenance_verified"] is True and (
            not proposal["claimed_evidence_ids"]
            or not set(proposal["claimed_evidence_ids"]) <= _evidence(request).keys()
            or not any(
                _evidence(request)[ident]["source_ref"] == proposal["source_ref"]
                for ident in proposal["claimed_evidence_ids"]
            )
        ):
            raise ValueError("unknown source cannot establish provenance")
    diagnosis = inputs["diagnosis_report"]
    expected_reports = [] if diagnosis is None else [diagnosis["report_id"]]
    if not set(result["hypothesis_report_ids"]) <= set(expected_reports):
        raise ValueError("assessment cites an unavailable hypothesis report")
    if result["decision_state"] == "assessment_available" and (
        diagnosis is None or diagnosis["result"] is None
        or diagnosis["result"]["assessment"] != "candidates_available"
        or any(row["usable"] is not True for row in reports.values())
    ):
        raise ValueError("assessment is unavailable without supported diagnostic evidence")
