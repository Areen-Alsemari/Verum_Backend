"""Tests for the Anomaly Detection agent runtime."""

from __future__ import annotations

import json
from typing import Any

import pytest

from verum.agents.anomaly_detection import AnomalyDetectionAgent
from verum.agents.anomaly_detection import agent as anomaly_agent
from verum.agents.common import check_request, check_response
from verum.contracts.agent_interfaces import content_hash, contract_directory


def example_request() -> dict[str, Any]:
    """Load the official anomaly detection request example."""
    path = contract_directory() / "examples" / "anomaly_detection.request.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def test_artifact_hash_mismatch_prevents_deserialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mismatched artifact hash prevents unsafe deserialization.

    Independent: yes, because the test verifies the hash check
    blocks the deserializer directly.
    """
    anomaly_agent.load_artifact.cache_clear()

    monkeypatch.setattr(
        anomaly_agent,
        "file_sha256",
        lambda _: "0" * 64,
    )

    def reject_deserialization(path: Any) -> None:
        pytest.fail("joblib.load must not run for an unverified artifact")

    monkeypatch.setattr(
        anomaly_agent.joblib,
        "load",
        reject_deserialization,
    )

    with pytest.raises(ValueError, match="hash mismatch"):
        anomaly_agent.load_artifact()


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

    categories = {event["category"] for event in response["result"]["events"]}

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
    assert any(issue["code"] == "MODEL_UNAVAILABLE" for issue in response["issues"])
    assert any(event["category"] == "missing_reading" for event in response["result"]["events"])


def test_anomaly_detection_consumes_attached_forecast_report():
    """Verify attached upstream reports are included in consumed evidence. Independent: yes."""
    request = example_request()
    forecast_path = contract_directory() / "examples" / "predictive_health.response.json"
    forecast = json.loads(forecast_path.read_text(encoding="utf-8"))
    request["input"]["forecast_report"] = forecast

    request["evidence"].append(
        {
            "evidence_id": forecast["report_id"],
            "kind": "agent_report",
            "source_ref": f"report:{forecast['report_id']}",
            "available_at_s": forecast["context"]["as_of_s"],
            "content_sha256": "2650cfd0ea46957f6b2bd4bcd5bff7228ff8a457e5688a2a13ec012807dac968",
            "root_evidence_ids": sorted(
                {
                    root
                    for evidence_id in forecast["consumed_evidence_ids"]
                    for row in request["evidence"]
                    if row["evidence_id"] == evidence_id
                    for root in row["root_evidence_ids"]
                }
            ),
            "provenance": "derived_agent_output",
        }
    )

    response = AnomalyDetectionAgent().run(request)

    assert forecast["report_id"] in response["consumed_evidence_ids"]
    check_response(request, response)


def test_anomaly_detection_degrades_on_memory_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A memory failure during model loading produces a degraded response.

    Independent: yes, because the test injects the failure and checks
    the resulting response status and issue.
    """

    def fail_load() -> dict[str, Any]:
        raise MemoryError("simulated memory failure")

    monkeypatch.setattr(
        "verum.agents.anomaly_detection.agent.load_artifact",
        fail_load,
    )

    response = AnomalyDetectionAgent().run(example_request())

    assert response["status"] == "degraded"
    assert any(issue["code"] == "MODEL_UNAVAILABLE" for issue in response["issues"])


def test_detected_event_explains_score_interpretation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detected events clarify that their score is not a probability.

    Independent: yes, because model output is explicitly controlled.
    """

    class FakeModel:
        classes_ = [False, True]

        def predict_proba(self, features: Any) -> list[list[float]]:
            return [[0.01, 0.99]]

    request = example_request()
    signals = request["input"]["observations"]["summary"]["signals"]
    valid_signals = anomaly_agent.filter_valid_unit_signals(signals)
    feature_names = list(anomaly_agent.extract_features(valid_signals))

    monkeypatch.setattr(
        anomaly_agent,
        "load_artifact",
        lambda: {
            "feature_names": feature_names,
            "threshold": 0.5,
            "model": FakeModel(),
        },
    )

    response = AnomalyDetectionAgent().run(request)

    detected_events = [
        event
        for event in response["result"]["events"]
        if event["category"] == "reported_signal_departure"
    ]

    assert len(detected_events) == 1
    assert "The score is not a calibrated probability." in detected_events[0]["limitations"]
    assert detected_events[0]["score"]["kind"] == "decision_score"
    check_response(request, response)


@pytest.mark.parametrize(
    ("score", "expected_detection"),
    [(0.49, False), (0.50, True)],
)
def test_detection_respects_inclusive_threshold(
    monkeypatch: pytest.MonkeyPatch,
    score: float,
    expected_detection: bool,
) -> None:
    """Detection occurs at or above the configured threshold.

    Independent: yes, because model scores and threshold are controlled.
    """

    class FakeModel:
        classes_ = [False, True]

        def predict_proba(self, features: Any) -> list[list[float]]:
            return [[1.0 - score, score]]

    request = example_request()
    signals = request["input"]["observations"]["summary"]["signals"]
    valid_signals = anomaly_agent.filter_valid_unit_signals(signals)
    feature_names = list(anomaly_agent.extract_features(valid_signals))

    monkeypatch.setattr(
        anomaly_agent,
        "load_artifact",
        lambda: {
            "feature_names": feature_names,
            "threshold": 0.50,
            "model": FakeModel(),
        },
    )

    response = AnomalyDetectionAgent().run(request)

    detected = any(
        event["category"] == "reported_signal_departure" for event in response["result"]["events"]
    )

    assert detected is expected_detection
    check_response(request, response)


def test_successful_model_run_omits_unavailable_limitation() -> None:
    """A successful model run does not report model unavailability.

    Independent: yes, because the response limitations are checked
    against the successful runtime result.
    """
    response = AnomalyDetectionAgent().run(example_request())

    assert not any(
        "could not be loaded or evaluated" in limitation for limitation in response["limitations"]
    )


def update_observation_evidence_hash(request: dict[str, Any]) -> None:
    observations = request["input"]["observations"]
    summary_hash = content_hash(observations["summary"])

    for evidence in request["evidence"]:
        if (
            evidence["kind"] == "observation_representation"
            and evidence["evidence_id"] in observations["evidence_ids"]
        ):
            evidence["content_sha256"] = summary_hash
            return

    raise AssertionError("Observation representation evidence was not found")


def test_empty_signals_return_insufficient_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty signal windows do not trigger model inference.

    Independent: yes, because model loading is explicitly blocked.
    """
    request = example_request()
    request["input"]["observations"]["summary"]["signals"] = []
    update_observation_evidence_hash(request)

    def reject_model_loading() -> dict[str, Any]:
        pytest.fail("Model inference must not run without signals")

    monkeypatch.setattr(anomaly_agent, "load_artifact", reject_model_loading)

    response = AnomalyDetectionAgent().run(request)

    assert response["status"] == "degraded"
    assert response["result"]["coverage"] == "unknown"
    assert any(issue["code"] == "INSUFFICIENT_EVIDENCE" for issue in response["issues"])
    check_response(request, response)


def test_all_missing_measurements_return_insufficient_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All-missing physical measurements do not trigger model inference.

    Independent: yes, because model loading is explicitly blocked.
    """
    request = example_request()
    signals = request["input"]["observations"]["summary"]["signals"]

    for signal in signals:
        for field in anomaly_agent.NUMERIC_FIELDS:
            signal[field] = None

    update_observation_evidence_hash(request)

    def reject_model_loading() -> dict[str, Any]:
        pytest.fail("Model inference must not run without physical measurements")

    monkeypatch.setattr(anomaly_agent, "load_artifact", reject_model_loading)

    response = AnomalyDetectionAgent().run(request)

    assert response["status"] == "degraded"
    assert response["result"]["coverage"] == "unknown"
    assert any(issue["code"] == "INSUFFICIENT_EVIDENCE" for issue in response["issues"])
    check_response(request, response)


def test_expected_signal_units_are_accepted() -> None:
    """Official tag-unit pairs are recognized.

    Independent: yes, because the helper is tested against the
    official request fixture without model inference.
    """
    request = example_request()
    signals = request["input"]["observations"]["summary"]["signals"]

    assert anomaly_agent.find_invalid_unit_signals(signals) == []
    assert len(anomaly_agent.filter_valid_unit_signals(signals)) == len(signals)


def test_unexpected_signal_unit_is_excluded() -> None:
    """A signal with an unexpected unit is excluded.

    Independent: yes, because the helper is tested directly using
    a controlled mutation of one fixture signal.
    """
    request = example_request()
    signals = request["input"]["observations"]["summary"]["signals"]
    signals[0]["unit"] = "C"

    invalid_tags = anomaly_agent.find_invalid_unit_signals(signals)
    valid_signals = anomaly_agent.filter_valid_unit_signals(signals)

    assert invalid_tags == ["FT-001"]
    assert all(signal["tag_id"] != "FT-001" for signal in valid_signals)


def test_unknown_signal_tag_is_excluded() -> None:
    """Signals with unknown tags are excluded from inference.

    Independent: yes, because the unit-validation helpers are tested
    directly with a controlled unknown tag.
    """
    request = example_request()
    signals = request["input"]["observations"]["summary"]["signals"]
    signals[0]["tag_id"] = "UNKNOWN-TAG"

    invalid_tags = anomaly_agent.find_invalid_unit_signals(signals)
    valid_signals = anomaly_agent.filter_valid_unit_signals(signals)

    assert invalid_tags == ["UNKNOWN-TAG"]
    assert all(signal["tag_id"] != "UNKNOWN-TAG" for signal in valid_signals)


def test_all_invalid_units_return_insufficient_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All invalid signal units prevent model inference.

    Independent: yes, because model loading is explicitly blocked.
    """
    request = example_request()
    signals = request["input"]["observations"]["summary"]["signals"]

    for signal in signals:
        signal["unit"] = "invalid-unit"

    update_observation_evidence_hash(request)

    def reject_model_loading() -> dict[str, Any]:
        pytest.fail("Model inference must not run without valid-unit signals")

    monkeypatch.setattr(anomaly_agent, "load_artifact", reject_model_loading)

    response = AnomalyDetectionAgent().run(request)

    assert response["status"] == "degraded"
    assert response["result"]["coverage"] == "unknown"
    assert any(issue["code"] == "INVALID_SIGNAL_UNIT" for issue in response["issues"])
    assert any(issue["code"] == "INSUFFICIENT_EVIDENCE" for issue in response["issues"])
    check_response(request, response)


def test_unexpected_runtime_error_returns_error_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected failures outside model inference return an error response.

    Independent: yes, because unit validation is explicitly forced to fail.
    """
    request = example_request()

    def reject_unit_validation(
        signals: list[dict[str, Any]],
    ) -> list[str]:
        raise RuntimeError("simulated internal failure")

    monkeypatch.setattr(
        anomaly_agent,
        "find_invalid_unit_signals",
        reject_unit_validation,
    )

    response = AnomalyDetectionAgent().run(request)

    assert response["status"] == "error"
    assert response["result"] is None
    assert any(issue["code"] == "INTERNAL_ERROR" for issue in response["issues"])
    check_response(request, response)


def test_detection_uses_true_class_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detection uses the score belonging to the True class.

    Independent: yes, because class order and model scores are controlled.
    """

    class FakeModel:
        classes_ = [True, False]

        def predict_proba(self, features: Any) -> list[list[float]]:
            return [[0.90, 0.10]]

    request = example_request()
    signals = request["input"]["observations"]["summary"]["signals"]
    valid_signals = anomaly_agent.filter_valid_unit_signals(signals)
    feature_names = list(anomaly_agent.extract_features(valid_signals))

    monkeypatch.setattr(
        anomaly_agent,
        "load_artifact",
        lambda: {
            "feature_names": feature_names,
            "threshold": 0.50,
            "model": FakeModel(),
        },
    )

    response = AnomalyDetectionAgent().run(request)

    detected = any(
        event["category"] == "reported_signal_departure" for event in response["result"]["events"]
    )

    assert detected
    detected_event = next(
        event
        for event in response["result"]["events"]
        if event["category"] == "reported_signal_departure"
    )
    assert detected_event["score"]["value"] == 0.90
    check_response(request, response)


def test_model_receives_features_in_artifact_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model input follows the feature order stored in the artifact.

    Independent: yes, because the model captures its controlled input.
    """

    class FakeModel:
        classes_ = [False, True]
        received_features: Any = None

        def predict_proba(self, features: Any) -> list[list[float]]:
            self.received_features = features.copy()
            return [[0.01, 0.99]]

    request = example_request()
    signals = request["input"]["observations"]["summary"]["signals"]
    valid_signals = anomaly_agent.filter_valid_unit_signals(signals)
    feature_values = anomaly_agent.extract_features(valid_signals)
    feature_names = list(reversed(list(feature_values)))
    fake_model = FakeModel()

    monkeypatch.setattr(
        anomaly_agent,
        "load_artifact",
        lambda: {
            "feature_names": feature_names,
            "threshold": 0.50,
            "model": fake_model,
        },
    )

    response = AnomalyDetectionAgent().run(request)

    expected_vector = [[feature_values[name] for name in feature_names]]

    assert fake_model.received_features.tolist() == expected_vector
    check_response(request, response)
