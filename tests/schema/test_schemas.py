"""Positive and negative cases for the five schemas other than the parameter value.

A schema verdict covers structure only, and physical plausibility is out of scope. The fault-truth
case embeds parameter records, so the reference between schemas is exercised, including the known
flaws.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from verum.contracts import SCHEMA_NAMES, load_schema, validator

Doc = dict[str, Any]

OBSERVATION: Doc = {
    "schema_version": "0.5.0",
    "dataset": "observations",
    "episode_id": "EP-EXAMPLE-0001",
    "tag_id": "LT-101",
    "t_sim_s": 600.0,
    "t_available_s": 600.2,
    "timestamp_utc": "2026-01-01T00:10:00.000Z",
    "value": 9.0012,
    "unit": "m",
    "quality_flag": "good",
    "availability_status": "measured",
}
AUDIT: Doc = {
    "schema_version": "0.5.0",
    "dataset": "observation_audit",
    "episode_id": "EP-EXAMPLE-0001",
    "tag_id": "LT-101",
    "t_sim_s": 600.0,
    "t_source_s": 599.0,
    "max_truth_time_used_s": 599.0,
    "hidden": True,
}


def _pv(value: float | None, status: str, tag: str, provenance: str | None) -> Doc:
    record: Doc = {"value": value, "unit": "m2", "status": status, "evidence_tag": tag}
    if provenance is not None:
        record["provenance_id"] = provenance
    return record


FAULT: Doc = {
    "schema_version": "0.5.0",
    "dataset": "fault_truth",
    "episode_id": "EP-EXAMPLE-0002",
    "fault_type": "PIPE_LEAK",
    "fault_instance_id": "FI-EXAMPLE-01",
    "causal_parent_fault_instance_id": None,
    "asset_id": "E-D1",
    "location": {"component": "pipe_wall", "distance_from_upstream_m": 10.0},
    "onset_t_sim_s": 300.0,
    "mechanism": "effective_leak_area_increase",
    "mechanism_status": "provisional",
    "severity_trajectory": {
        "type": "piecewise_linear",
        "time_basis": "seconds_since_onset",
        "knots": [[0, 0.0], [600, 0.5], [1200, 0.5]],
        "interpolation": "linear",
        "outside_support": "hold_last",
    },
    "physical_parameter_modified": {
        "name": "effective_leak_area",
        "unit": "m2",
        "baseline_value": _pv(0.0, "provisional", "SIM", "SIM-EXAMPLE-GT8"),
        "fault_value_at_severity_one": _pv(1e-4, "provisional", "SIM", "SIM-EXAMPLE-GT8"),
        "mapping": "A_eff = fault_value_at_severity_one * severity",
    },
    "conserved_quantity_effects": [],
    "hidden": True,
}
REQUEST: Doc = {
    "schema_version": "0.5.0",
    "dataset": "inspection_requests",
    "request_id": "REQ-INSP-00001",
    "t_requested_sim_s": 3000.0,
    "action_id": "ACT-INSP-02",
    "target_asset": "XV-PAO",
    "justification": {
        "competing_hypotheses": ["VALVE_RESTRICTION", "PUMP_HEAD_DEGRADATION"],
        "agent_reported_information_gain_bits": 0.92,
        "estimated_cost_usd": 90.0,
    },
    "human_approval": {"status": "PENDING"},
}
RESULT_APPROVED: Doc = {
    "schema_version": "0.5.0",
    "dataset": "inspection_results",
    "result_id": "RES-INSP-00001",
    "request_id": "REQ-INSP-00001",
    "action_id": "ACT-INSP-02",
    "workflow_status": "approved",
}
RESULT_PERFORMED: Doc = {
    **RESULT_APPROVED,
    "workflow_status": "performed",
    "evidence_status": "valid",
    "performed_at_t_sim_s": 3600.0,
    "technician_id": "TECH-01",
    "findings": {
        "outcome_category": "CRITICAL_DEFECT",
        "primary_metric": {
            "name": "valve_dp",
            "value": 1.45,
            "unit": "bar",
            "uncertainty_k2": 0.02,
        },
        "secondary_observations": [],
    },
    "validation_status": "PASSED_QA",
}


def _edit(base: Doc, path: str, value: Any) -> Doc:
    """Copy ``base`` and set a dotted path; the sentinel ``DROP`` deletes the key."""
    doc = copy.deepcopy(base)
    *parents, leaf = path.split(".")
    node = doc
    for key in parents:
        node = node[key]
    if value is DROP:
        del node[leaf]
    else:
        node[leaf] = value
    return doc


DROP = object()

# (schema, case name, document, expected validity)
CASES: list[tuple[str, str, Doc, bool]] = [
    ("observation", "measured", OBSERVATION, True),
    (
        "observation",
        "missing sample with null",
        {
            **OBSERVATION,
            "value": None,
            "quality_flag": "bad",
            "availability_status": "missing_sample",
        },
        True,
    ),
    (
        "observation",
        "missing sample with number",
        _edit(OBSERVATION, "availability_status", "missing_sample"),
        False,
    ),
    ("observation", "measured with null", _edit(OBSERVATION, "value", None), False),
    ("observation", "truth field fault_type", _edit(OBSERVATION, "fault_type", "PIPE_LEAK"), False),
    (
        "observation",
        "status observed_normal",
        _edit(OBSERVATION, "availability_status", "observed_normal"),
        False,
    ),
    (
        "observation",
        "status not_instrumented",
        _edit(OBSERVATION, "availability_status", "not_instrumented"),
        False,
    ),
    ("observation", "no t_available_s", _edit(OBSERVATION, "t_available_s", DROP), False),
    ("observation", "negative t_sim_s", _edit(OBSERVATION, "t_sim_s", -1.0), False),
    ("observation", "malformed tag", _edit(OBSERVATION, "tag_id", "lt-101"), False),
    ("observation", "malformed timestamp", _edit(OBSERVATION, "timestamp_utc", "yesterday"), False),
    ("observation", "empty unit", _edit(OBSERVATION, "unit", ""), False),
    ("observation", "unknown quality flag", _edit(OBSERVATION, "quality_flag", "ok"), False),
    ("observation", "wrong dataset", _edit(OBSERVATION, "dataset", "observation_audit"), False),
    ("observation", "wrong major version", _edit(OBSERVATION, "schema_version", "1.0.0"), False),
    ("observation_audit", "audit row", AUDIT, True),
    ("observation_audit", "hidden false", _edit(AUDIT, "hidden", False), False),
    ("observation_audit", "hidden absent", _edit(AUDIT, "hidden", DROP), False),
    ("observation_audit", "no t_source_s", _edit(AUDIT, "t_source_s", DROP), False),
    ("observation_audit", "extra field", _edit(AUDIT, "value", 1.0), False),
    ("fault_truth", "pipe leak", FAULT, True),
    ("fault_truth", "old fault id", _edit(FAULT, "fault_type", "F06"), False),
    (
        "fault_truth",
        "string parameter value",
        _edit(FAULT, "physical_parameter_modified.fault_value_at_severity_one.value", "OPEN"),
        False,
    ),
    (
        "fault_truth",
        "unresolved parameter",
        _edit(
            FAULT,
            "physical_parameter_modified.fault_value_at_severity_one",
            _pv(None, "unresolved", "OPEN", None),
        ),
        True,
    ),
    (
        "fault_truth",
        "provisional parameter with null provenance",
        _edit(
            FAULT,
            "physical_parameter_modified.baseline_value",
            {**_pv(0.0, "provisional", "SIM", None), "provenance_id": None},
        ),
        False,
    ),
    (
        "fault_truth",
        "unresolved parameter tagged SIM",
        _edit(
            FAULT,
            "physical_parameter_modified.baseline_value",
            _pv(None, "unresolved", "SIM", None),
        ),
        False,
    ),
    (
        "fault_truth",
        "resolved parameter tagged OPEN",
        _edit(
            FAULT, "physical_parameter_modified.baseline_value", _pv(1.0, "resolved", "OPEN", "X")
        ),
        False,
    ),
    (
        "fault_truth",
        "severity above one",
        _edit(FAULT, "severity_trajectory.knots", [[0, 1.5]]),
        False,
    ),
    (
        "fault_truth",
        "negative knot time",
        _edit(FAULT, "severity_trajectory.knots", [[-1, 0.5]]),
        False,
    ),
    ("fault_truth", "no knots", _edit(FAULT, "severity_trajectory.knots", []), False),
    ("fault_truth", "hidden absent", _edit(FAULT, "hidden", DROP), False),
    ("fault_truth", "hidden false", _edit(FAULT, "hidden", False), False),
    ("fault_truth", "unknown mechanism status", _edit(FAULT, "mechanism_status", "guess"), False),
    ("fault_truth", "negative onset", _edit(FAULT, "onset_t_sim_s", -5), False),
    ("inspection_request", "pending request", REQUEST, True),
    (
        "inspection_request",
        "one hypothesis",
        _edit(REQUEST, "justification.competing_hypotheses", ["only one"]),
        False,
    ),
    ("inspection_request", "malformed request id", _edit(REQUEST, "request_id", "REQ-1"), False),
    ("inspection_request", "unknown action", _edit(REQUEST, "action_id", "ACT-INSP-08"), False),
    (
        "inspection_request",
        "negative cost",
        _edit(REQUEST, "justification.estimated_cost_usd", -1),
        False,
    ),
    (
        "inspection_request",
        "unknown approval status",
        _edit(REQUEST, "human_approval.status", "MAYBE"),
        False,
    ),
    ("inspection_request", "no approval", _edit(REQUEST, "human_approval", DROP), False),
    ("inspection_request", "extra field", _edit(REQUEST, "findings", {}), False),
    ("inspection_result", "approved without evidence", RESULT_APPROVED, True),
    (
        "inspection_result",
        "approved with evidence",
        _edit(RESULT_APPROVED, "evidence_status", "valid"),
        False,
    ),
    ("inspection_result", "performed in full", RESULT_PERFORMED, True),
    (
        "inspection_result",
        "performed without findings",
        _edit(RESULT_PERFORMED, "findings", DROP),
        False,
    ),
    (
        "inspection_result",
        "performed without technician",
        _edit(RESULT_PERFORMED, "technician_id", DROP),
        False,
    ),
    (
        "inspection_result",
        "performed without validation status",
        _edit(RESULT_PERFORMED, "validation_status", DROP),
        False,
    ),
    (
        "inspection_result",
        "malformed result id",
        _edit(RESULT_PERFORMED, "result_id", "RES-1"),
        False,
    ),
    (
        "inspection_result",
        "unknown outcome category",
        _edit(RESULT_PERFORMED, "findings.outcome_category", "BROKEN"),
        False,
    ),
    (
        "inspection_result",
        "negative uncertainty",
        _edit(RESULT_PERFORMED, "findings.primary_metric.uncertainty_k2", -0.1),
        False,
    ),
    (
        "inspection_result",
        "malformed calibration date",
        _edit(RESULT_PERFORMED, "calibration_valid_until", "soon"),
        False,
    ),
]


@pytest.mark.parametrize(
    ("schema", "name", "document", "expected"),
    CASES,
    ids=[f"{c[0]}:{c[1]}" for c in CASES],
)
def test_schema_verdict(schema: str, name: str, document: Doc, expected: bool) -> None:
    """Each hand-built document is accepted or rejected by its schema as expected. Independent: yes,
    because the verdicts are written out per case.
    """
    assert validator(schema).is_valid(document) is expected


@pytest.mark.parametrize("schema", [n for n in SCHEMA_NAMES if n != "paramvalue"])
def test_every_schema_has_a_positive_and_a_negative_case(schema: str) -> None:
    """Every schema has at least one accepted and one rejected case. Independent: yes, because the
    check counts the cases.
    """
    verdicts = {c[3] for c in CASES if c[0] == schema}
    assert verdicts == {True, False}


@pytest.mark.parametrize("schema", SCHEMA_NAMES)
def test_schema_ids_are_versioned_urns(schema: str) -> None:
    """Every schema identifier is a versioned URN. Independent: yes, because the check reads the
    schema documents directly.
    """
    assert load_schema(schema)["$id"].startswith(f"urn:verum:{schema}:")


@pytest.mark.parametrize(
    "field",
    [
        "evidence_status",
        "findings",
        "performed_at_t_sim_s",
        "technician_id",
        "validation_status",
        "tool_serial",
    ],
)
@pytest.mark.parametrize("status", ["not_requested", "requested", "approved", "cancelled"])
def test_inspection_evidence_only_after_performed(status: str, field: str) -> None:
    """Inspection evidence fields are accepted only when the workflow status is performed.
    Independent: yes, because the expected outcome is the stated visibility rule.
    """
    document = {
        **RESULT_APPROVED,
        "workflow_status": status,
        field: RESULT_PERFORMED.get(field, "x"),
    }
    assert not validator("inspection_result").is_valid(document)
