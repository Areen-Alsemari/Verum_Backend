
"""Independent tests for the inspection quality documentation agent."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import ValidationError

from verum.agents.inspection_quality_documentation import (
    InspectionQualityDocumentationAgent,
)
from verum.contracts.agent_interfaces import content_hash

EXAMPLE_PATH = Path("contracts/agents/v1/examples/inspection_quality_documentation.request.json")


def example_request() -> dict[str, Any]:
    """Load the official Agent 7 contract request."""
    with EXAMPLE_PATH.open(encoding="utf-8") as file:
        return cast(dict[str, Any], json.load(file))


def test_example_request_returns_valid_response() -> None:
    """Independent: validate the real agent against its contract example."""
    request = example_request()
    response = InspectionQualityDocumentationAgent().run(request)

    assert response["agent"] == "inspection_quality_documentation"
    assert response["status"] in {"complete", "degraded"}
    assert response["result"] is not None
    assert response["result"]["record_checks"] == []
    assert response["result"]["retest_result_ids"] == []


def test_no_inspection_results_reports_limitation() -> None:
    """Independent: missing inspection results must not establish quality."""
    response = InspectionQualityDocumentationAgent().run(example_request())

    assert response["status"] == "degraded"
    assert any(issue["code"] == "NO_INSPECTION_RESULTS" for issue in response["issues"])


def test_observed_quality_uses_supplied_signal_counts() -> None:
    """Independent: signal quality must reflect supplied observation counts."""
    request = example_request()
    response = InspectionQualityDocumentationAgent().run(request)

    signals = request["input"]["observations"]["summary"]["signals"]
    observed = {row["tag_id"]: row for row in response["result"]["observed_quality"]}

    assert len(observed) == len(signals)

    for signal in signals:
        row = observed[signal["tag_id"]]

        assert row["missing_samples"] == signal["missing_samples"]
        assert row["non_good_samples"] == signal["bad_quality_samples"]
        assert row["latest_reading_missing"] == (signal["latest_availability"] != "measured")
        assert row["evidence_ids"] == ["features-summary"]


def test_missing_observations_produce_no_quality_rows() -> None:
    """Independent: absent observations must not produce invented readings."""
    request = deepcopy(example_request())
    request["input"]["observations"] = None

    response = InspectionQualityDocumentationAgent().run(request)

    assert response["result"]["observed_quality"] == []


def inspection_request_with_result() -> dict[str, Any]:
    """Build a contract-based request with one performed inspection."""
    request = deepcopy(example_request())

    request["input"]["inspection_requests"] = [
        {
            "schema_version": "0.5.0",
            "dataset": "inspection_requests",
            "request_id": "REQ-INSP-00001",
            "t_requested_sim_s": 100.0,
            "action_id": "ACT-INSP-01",
            "target_asset": "TANK-001",
            "justification": {
                "competing_hypotheses": ["H1", "H2"],
                "agent_reported_information_gain_bits": 1.0,
                "estimated_cost_usd": 10.0,
            },
            "human_approval": {
                "status": "APPROVED",
                "approver_id": "APPROVER-001",
            },
        }
    ]

    request["context"]["as_of_utc"] = "2026-11-08T12:00:00Z"
    request["input"]["inspection_results"] = [
        {
            "schema_version": "0.5.0",
            "dataset": "inspection_results",
            "result_id": "RES-INSP-00001",
            "request_id": "REQ-INSP-00001",
            "action_id": "ACT-INSP-01",
            "workflow_status": "performed",
            "evidence_status": "valid",
            "performed_at_t_sim_s": 120.0,
            "technician_id": "TECH-001",
            "calibration_valid_until": "2026-12-31",
            "findings": {
                "outcome_category": "NORMAL_INTACT",
                "primary_metric": {
                    "name": "maximum_rim_seal_gap",
                    "value": 2.0,
                    "unit": "mm",
                    "uncertainty_k2": 0.2,
                },
                "secondary_observations": [],
            },
            "validation_status": "PASSED_QA",
        }
    ]

    request["input"]["process_coverage"] = [
        {
            "coverage_id": "COV-001",
            "target_asset": "TANK-001",
            "start_s": 110.0,
            "end_s": 130.0,
            "evidence_ids": ["source-reference"],
        }
    ]

    evidence = deepcopy(request["evidence"][0])
    evidence["evidence_id"] = "inspection-result-evidence"
    evidence["root_evidence_ids"] = ["inspection-result-evidence"]
    evidence["kind"] = "inspection_result"
    evidence["source_ref"] = "inspection_result:RES-INSP-00001"
    evidence["available_at_s"] = 120.0
    evidence["provenance"] = "simulated_inspection"
    evidence["content_sha256"] = content_hash(request["input"]["inspection_results"][0])

    request["evidence"].append(evidence)
    request["input"]["result_evidence_ids"] = ["inspection-result-evidence"]

    return request


def run_inspection(
    request: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run Agent 7 with inspection result and workflow evidence."""
    result = request["input"]["inspection_results"][0]
    workflow = request["input"]["inspection_requests"][0]

    result_ref = "inspection_result:" + result["result_id"]
    workflow_ref = "inspection_request:" + workflow["request_id"]

    for evidence in request["evidence"]:
        if evidence["source_ref"] == result_ref:
            evidence["content_sha256"] = content_hash(result)

    workflow_evidence = deepcopy(request["evidence"][0])
    workflow_evidence["evidence_id"] = "inspection-request-evidence"
    workflow_evidence["root_evidence_ids"] = ["inspection-request-evidence"]
    workflow_evidence["kind"] = "inspection_request"
    workflow_evidence["provenance"] = "simulated_workflow"
    workflow_evidence["source_ref"] = workflow_ref
    workflow_evidence["available_at_s"] = workflow["t_requested_sim_s"]
    workflow_evidence["content_sha256"] = content_hash(workflow)

    request["evidence"].append(workflow_evidence)

    response = InspectionQualityDocumentationAgent().run(request)
    record = response["result"]["record_checks"][0]
    return response, record


def inspection_check(
    record: dict[str, Any],
    check_id: str,
) -> str:
    """Return the outcome of a named inspection quality check."""
    return next(
        str(check["outcome"]) for check in record["checks"] if check["check_id"] == check_id
    )


def test_valid_inspection_measurement_is_usable() -> None:
    """Independent: a valid approved inspection must be usable."""
    response, record = run_inspection(inspection_request_with_result())

    assert record["measurement_usable"] is True
    assert record["scope_supported"] is True
    assert record["equipment_condition_confirmed"] is False
    assert record["evidence_ids"] == ["inspection-result-evidence"]
    assert inspection_check(record, "source_provenance") == "pass"
    assert inspection_check(record, "process_coverage") == "pass"
    assert response["result"]["retest_result_ids"] == []
    assert response["status"] == "complete"


def test_retest_required_result_is_unusable() -> None:
    """Independent: a result requiring retest must not be usable."""
    request = inspection_request_with_result()
    request["input"]["inspection_results"][0]["validation_status"] = "RETEST_REQUIRED"

    response, record = run_inspection(request)

    assert record["measurement_usable"] is False
    assert inspection_check(record, "validation_status") == "fail"
    assert response["result"]["retest_result_ids"] == ["RES-INSP-00001"]


def test_inconsistent_result_is_unusable() -> None:
    """Independent: inconsistent validation must trigger a retest."""
    request = inspection_request_with_result()
    request["input"]["inspection_results"][0]["validation_status"] = "FLAGGED_INCONSISTENT"

    response, record = run_inspection(request)

    assert record["measurement_usable"] is False
    assert response["result"]["retest_result_ids"] == ["RES-INSP-00001"]


def test_missing_evidence_is_unusable() -> None:
    """Independent: missing evidence must prevent measurement acceptance."""
    request = inspection_request_with_result()
    request["input"]["inspection_results"][0]["evidence_status"] = "missing"

    response, record = run_inspection(request)

    assert record["measurement_usable"] is False
    assert inspection_check(record, "evidence_availability") == "fail"
    assert response["result"]["retest_result_ids"] == ["RES-INSP-00001"]


def test_missing_result_provenance_is_unknown() -> None:
    """Independent: missing provenance must not imply a valid measurement."""
    request = inspection_request_with_result()
    request["input"]["result_evidence_ids"] = []

    response, record = run_inspection(request)

    assert record["measurement_usable"] is None
    assert inspection_check(record, "source_provenance") == "unknown"
    assert response["result"]["retest_result_ids"] == []


def test_pending_approval_is_unknown() -> None:
    """Independent: pending approval must not establish usable inspection."""
    request = inspection_request_with_result()
    request["input"]["inspection_requests"][0]["human_approval"]["status"] = "PENDING"

    _, record = run_inspection(request)

    assert inspection_check(record, "human_approval") == "unknown"
    assert record["measurement_usable"] is None


def test_rejected_approval_is_unusable() -> None:
    """Independent: rejected inspection must not be usable."""
    request = inspection_request_with_result()
    request["input"]["inspection_requests"][0]["human_approval"]["status"] = "REJECTED"

    response, record = run_inspection(request)

    assert inspection_check(record, "human_approval") == "fail"
    assert record["measurement_usable"] is False
    assert response["result"]["retest_result_ids"] == ["RES-INSP-00001"]


def test_inspection_before_request_is_unusable() -> None:
    """Independent: inspection performed before request must fail chronology."""
    request = inspection_request_with_result()
    request["input"]["inspection_results"][0]["performed_at_t_sim_s"] = 90.0

    response, record = run_inspection(request)

    assert inspection_check(record, "chronology") == "fail"
    assert record["measurement_usable"] is False
    assert response["result"]["retest_result_ids"] == ["RES-INSP-00001"]


def test_wrong_measurement_unit_is_unusable() -> None:
    """Independent: mismatched measurement units must require retest."""
    request = inspection_request_with_result()
    request["input"]["inspection_results"][0]["findings"]["primary_metric"]["unit"] = "cm"

    response, record = run_inspection(request)

    assert inspection_check(record, "measurement_unit") == "fail"
    assert record["measurement_usable"] is False
    assert record["scope_supported"] is False
    assert response["result"]["retest_result_ids"] == ["RES-INSP-00001"]


def test_uncovered_asset_is_unknown() -> None:
    """Independent: coverage for another asset cannot establish scope."""
    request = inspection_request_with_result()
    request["input"]["process_coverage"][0]["target_asset"] = "TANK-002"

    response, record = run_inspection(request)

    assert inspection_check(record, "process_coverage") == "unknown"
    assert record["scope_supported"] is None
    assert record["measurement_usable"] is None
    assert response["result"]["retest_result_ids"] == []


def test_missing_catalog_evidence_is_unknown() -> None:
    """Independent: unverified catalog metadata cannot establish scope."""
    request = inspection_request_with_result()
    request["input"]["catalog_evidence_ids"] = []

    _, record = run_inspection(request)

    assert inspection_check(record, "measurement_unit") == "unknown"
    assert record["scope_supported"] is None
    assert record["measurement_usable"] is None


def test_coverage_uses_inspection_request_target_asset() -> None:
    """Independent: coverage must use the linked request target asset."""
    request = inspection_request_with_result()

    assert "target_asset" not in request["input"]["inspection_results"][0]

    _, record = run_inspection(request)

    assert inspection_check(record, "process_coverage") == "pass"
    assert record["scope_supported"] is True


def test_missing_request_is_unknown_without_retest() -> None:
    """Missing request context must not imply a failed inspection.

    Independent: yes, because this test constructs its own missing-request case.
    """
    request = inspection_request_with_result()
    request["input"]["inspection_requests"] = []

    response = InspectionQualityDocumentationAgent().run(request)
    record = response["result"]["record_checks"][0]
    checks = {check["check_id"]: check["outcome"] for check in record["checks"]}

    assert checks["request_link"] == "unknown"
    assert checks["chronology"] == "unknown"
    assert checks["human_approval"] == "unknown"
    assert record["measurement_usable"] is None
    assert response["result"]["retest_result_ids"] == []


def test_calibration_validity_outcomes() -> None:
    """Calibration validity depends on both expiry and assessment date.

    Independent: yes, because this test supplies its own calibration dates.
    """
    for expiry, as_of, expected, usable in [
        ("2026-12-31", "2026-11-08T12:00:00Z", "pass", True),
        ("2026-01-01", "2026-11-08T12:00:00Z", "fail", False),
        ("2026-12-31", None, "unknown", None),
        (None, "2026-11-08T12:00:00Z", "unknown", None),
    ]:
        request = inspection_request_with_result()
        request["context"]["as_of_utc"] = as_of
        if expiry is None:
            request["input"]["inspection_results"][0].pop("calibration_valid_until", None)
        else:
            request["input"]["inspection_results"][0]["calibration_valid_until"] = expiry

        _, record = run_inspection(request)

        assert inspection_check(record, "calibration_validity") == expected
        assert record["measurement_usable"] is usable


def test_request_evidence_is_cited_and_consumed() -> None:
    """Request-dependent checks cite the originating request evidence.

    Independent: yes, because this test checks evidence citations directly.
    """
    response, record = run_inspection(inspection_request_with_result())
    for name in ("request_link", "chronology", "human_approval"):
        check = next(c for c in record["checks"] if c["check_id"] == name)
        assert "inspection-request-evidence" in check["evidence_ids"]
    assert "inspection-request-evidence" in response["consumed_evidence_ids"]


def test_coverage_outside_time_is_unknown() -> None:
    """Independent: yes, because coverage outside the inspection time window is tested directly."""
    request = inspection_request_with_result()
    request["input"]["process_coverage"][0]["end_s"] = 110.0
    _, record = run_inspection(request)
    assert inspection_check(record, "process_coverage") == "unknown"
    assert record["scope_supported"] is None
    assert record["measurement_usable"] is None


def test_coverage_without_evidence_is_unknown() -> None:
    """Independent: yes, because coverage without supporting evidence is tested directly."""
    request = inspection_request_with_result()
    request["input"]["process_coverage"][0]["evidence_ids"] = []
    _, record = run_inspection(request)
    assert inspection_check(record, "process_coverage") == "unknown"
    assert record["scope_supported"] is None


def test_invalid_numeric_measurements_are_rejected() -> None:
    """Reject invalid measurement values at the public contract boundary.

    Independent: yes, because this test checks invalid values independently.
    """
    for field, value in [("value", True), ("uncertainty_k2", -1.0)]:
        request = inspection_request_with_result()
        metric = request["input"]["inspection_results"][0]["findings"]["primary_metric"]
        metric[field] = value
        with pytest.raises(ValidationError):
            run_inspection(request)


def test_coverage_wrong_asset_is_unknown() -> None:
    """Independent: yes, because this test checks coverage for another asset."""
    request = inspection_request_with_result()
    request["input"]["process_coverage"][0]["target_asset"] = "TANK-002"
    _, record = run_inspection(request)
    assert inspection_check(record, "process_coverage") == "unknown"
    assert record["scope_supported"] is None


def test_valid_coverage_supports_scope() -> None:
    """Independent: yes, because this test checks valid coverage directly."""
    _, record = run_inspection(inspection_request_with_result())
    assert inspection_check(record, "process_coverage") == "pass"
    assert record["scope_supported"] is True


def test_mismatched_measurement_unit_rejects_scope() -> None:
    """A catalog unit mismatch must not support inspection scope.

    Independent: yes, because a catalog unit mismatch is tested directly against scope support.
    """
    request = inspection_request_with_result()
    request["input"]["inspection_results"][0]["findings"]["primary_metric"]["unit"] = "cm"
    _, record = run_inspection(request)
    assert inspection_check(record, "measurement_unit") == "fail"
    assert record["scope_supported"] is False
