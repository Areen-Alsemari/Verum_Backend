"""Tests for the Anomaly Detection agent runtime."""

from __future__ import annotations

import json
from typing import Any

import pytest

from verum.agents.anomaly_detection import AnomalyDetectionAgent
from verum.agents.common import check_request, check_response
from verum.contracts.agent_interfaces import contract_directory


def example_request() -> dict[str, Any]:
    """Load the official anomaly detection request example."""
    path = (
        contract_directory()
        / "examples"
        / "anomaly_detection.request.json"
    )
    loaded: dict[str, Any] = json.loads(
        path.read_text(encoding="utf-8")
    )
    return loaded


def test_anomaly_detection_runtime_passes_the_contract() -> None:
    """The runtime returns a contract-valid advisory response.

    Independent: yes, because the request and response validators
    independently enforce the shared contract.
    """
    request = example_request()
    check_request(request)

    response = AnomalyDetectionAgent().run(request)

    check_response(request, response)
    assert response["agent"] == "anomaly_detection"
    assert response["request_id"] == request["request_id"]
    assert response["advisory_only"] is True
    assert response["result"]["no_event_means_healthy"] is False


def test_anomaly_detection_reports_quality_issues() -> None:
    """Reported missing and bad-quality samples produce quality events.

    Independent: yes, because the assertions inspect the runtime
    output against explicit conditions in the request.
    """
    request = example_request()
    response = AnomalyDetectionAgent().run(request)

    categories = {
        event["category"]
        for event in response["result"]["events"]
    }

    assert "missing_reading" in categories
    assert "non_good_quality" in categories


def test_anomaly_detection_does_not_use_stub_implementation() -> None:
    """The runtime identifies its actual implementation.

    Independent: yes, because implementation metadata is checked
    separately from event detection.
    """
    response = AnomalyDetectionAgent().run(example_request())

    assert response["implementation"]["name"] == "anomaly_detection"
    assert response["implementation"]["version"] == "1.0.0"
    assert response["implementation"]["artifact_sha256"] is not None

def test_anomaly_detection_degrades_when_model_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quality rules remain available when the trained model cannot load.

    Independent: yes, because model loading is isolated from the
    quality-rule checks.
    """

    def fail_load() -> dict[str, Any]:
        raise OSError("model unavailable")

    monkeypatch.setattr(
        "verum.agents.anomaly_detection.agent.load_artifact",
        fail_load,
    )

    response = AnomalyDetectionAgent().run(example_request())

    assert response["status"] == "degraded"
    assert response["result"]["no_event_means_healthy"] is False
    assert any(
        issue["code"] == "MODEL_UNAVAILABLE"
        for issue in response["issues"]
    )
    assert any(
        event["category"] == "missing_reading"
        for event in response["result"]["events"]
    )

def test_anomaly_detection_consumes_attached_forecast_report():
    """Verify attached upstream reports are included in consumed evidence. Independent: yes."""
    request = example_request()
    forecast_path = (
        contract_directory()
        / "examples"
        / "predictive_health.response.json"
    )
    forecast = json.loads(forecast_path.read_text(encoding="utf-8"))
    request["input"]["forecast_report"] = forecast

    request["evidence"].append(
    {
        "evidence_id": forecast["report_id"],
        "kind": "agent_report",
        "source_ref": f"report:{forecast['report_id']}",
        "available_at_s": forecast["context"]["as_of_s"],
        "content_sha256": "2650cfd0ea46957f6b2bd4bcd5bff7228ff8a457e5688a2a13ec012807dac968",
        "root_evidence_ids": sorted({
         root
        for evidence_id in forecast["consumed_evidence_ids"]
        for row in request["evidence"]
        if row["evidence_id"] == evidence_id
        for root in row["root_evidence_ids"] }),
        "provenance": "derived_agent_output",
    }
)

    response = AnomalyDetectionAgent().run(request)

    assert forecast["report_id"] in response["consumed_evidence_ids"]
    check_response(request, response)