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