"""Tests for the Anomaly Detection agent runtime."""

from __future__ import annotations

import copy
import json
import math
import pickle
import random
import struct
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import joblib  # type: ignore[import-untyped]
import pytest

from verum.agents.anomaly_detection import AnomalyDetectionAgent
from verum.agents.anomaly_detection import agent as anomaly_agent
from verum.agents.common import check_request, check_response, file_sha256
from verum.contracts.agent_interfaces import content_hash, contract_directory

pytestmark = pytest.mark.fast
AGENT = "verum.agents.anomaly_detection.agent"


@pytest.fixture(autouse=True)
def clear_artifact_cache() -> Iterator[None]:
    """Keep the cached artifact from leaking between tests."""
    anomaly_agent.load_artifact.cache_clear()
    yield
    anomaly_agent.load_artifact.cache_clear()


def example_request() -> dict[str, Any]:
    """Load the official anomaly detection request example."""
    path = contract_directory() / "examples" / "anomaly_detection.request.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def signals_of(request: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the mutable signal list inside a request."""
    signals: list[dict[str, Any]] = request["input"]["observations"]["summary"]["signals"]
    return signals


def update_observation_evidence_hash(request: dict[str, Any]) -> None:
    """Re-hash the observation summary after a test mutates it."""
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


def attach_forecast(request: dict[str, Any]) -> str:
    """Attach the official forecast example as an upstream report and return its id."""
    forecast_path = contract_directory() / "examples" / "predictive_health.response.json"
    forecast = json.loads(forecast_path.read_text(encoding="utf-8"))
    request["input"]["forecast_report"] = forecast
    request["evidence"].append(
        {
            "evidence_id": forecast["report_id"],
            "kind": "agent_report",
            "source_ref": f"report:{forecast['report_id']}",
            "available_at_s": forecast["context"]["as_of_s"],
            "content_sha256": content_hash(forecast),
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
    report_id: str = forecast["report_id"]
    return report_id


class FakeModel:
    """A model whose positive-class score is fixed and whose input is recorded."""

    def __init__(self, score: float, classes: tuple[bool, bool] = (False, True)) -> None:
        self.classes_ = list(classes)
        self.score = score
        self.received_features: Any = None

    def predict_proba(self, features: Any) -> list[list[float]]:
        """Return the fixed score in class order, recording the input."""
        self.received_features = features.copy()
        positive_first = self.classes_[0] is True
        return (
            [[self.score, 1.0 - self.score]] if positive_first else [[1.0 - self.score, self.score]]
        )


def install_fake_artifact(
    monkeypatch: pytest.MonkeyPatch,
    request: dict[str, Any],
    model: FakeModel,
    *,
    threshold: float = 0.5,
    feature_names: list[str] | None = None,
    feature_ranges: dict[str, list[float]] | None = None,
    profile_id: str | None = None,
) -> None:
    """Replace the artifact with a controlled one built from the request's own features."""
    profile = profile_id or anomaly_agent.AGGREGATE_PROFILE_ID
    names = feature_names or list(anomaly_agent.features_for(profile, signals_of(request)))
    artifact: dict[str, Any] = {"feature_names": names, "threshold": threshold, "model": model}
    if profile_id is not None:
        artifact["feature_profile_id"] = profile_id
    if feature_ranges is not None:
        artifact["feature_ranges"] = feature_ranges
    monkeypatch.setattr(anomaly_agent, "load_artifact", lambda: artifact)


def forbid_model_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if the detector is consulted."""

    def reject() -> dict[str, Any]:
        pytest.fail("model inference must not run for this window")

    monkeypatch.setattr(anomaly_agent, "load_artifact", reject)


def departures(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Model events in a response."""
    return [e for e in response["result"]["events"] if e["category"] == "reported_signal_departure"]


# Artifact loading


def test_artifact_hash_mismatch_prevents_deserialization(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mismatched artifact hash prevents unsafe deserialization.

    Independent: yes, because the test verifies the hash check blocks the deserializer directly.
    """
    monkeypatch.setattr(f"{AGENT}.file_sha256", lambda _: "0" * 64)

    def reject_deserialization(path: Any) -> None:
        pytest.fail("joblib.load must not run for an unverified artifact")

    monkeypatch.setattr(joblib, "load", reject_deserialization)

    with pytest.raises(ValueError, match="hash mismatch"):
        anomaly_agent.load_artifact()


def test_pinned_hash_matches_the_shipped_artifact() -> None:
    """The pinned constant matches the artifact in the package.

    Independent: yes, because the file is hashed directly, without loading it.
    """
    assert anomaly_agent.ARTIFACT_PATH.exists()
    actual = file_sha256(anomaly_agent.ARTIFACT_PATH)
    assert actual == anomaly_agent.EXPECTED_ARTIFACT_SHA256


@pytest.mark.parametrize(
    "failure",
    [
        OSError("io"),
        MemoryError("memory"),
        struct.error("struct"),
        EOFError("eof"),
        pickle.UnpicklingError("pickle"),
    ],
)
def test_every_load_failure_is_a_named_issue(
    monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    """Any deserialization failure after a passing hash check degrades with MODEL_UNAVAILABLE.

    Independent: yes, because the failure is injected into the deserializer itself.
    """
    monkeypatch.setattr(f"{AGENT}.file_sha256", lambda _: anomaly_agent.EXPECTED_ARTIFACT_SHA256)

    def fail(path: Any) -> None:
        raise failure

    monkeypatch.setattr(joblib, "load", fail)
    request = example_request()
    response = AnomalyDetectionAgent().run(request)

    assert response["status"] == "degraded"
    assert any(issue["code"] == "MODEL_UNAVAILABLE" for issue in response["issues"])
    assert any(event["category"] == "missing_reading" for event in response["result"]["events"])
    assert anomaly_agent.MODEL_UNAVAILABLE_TEXT in response["limitations"]
    check_response(request, response)


# Contract and evidence


def test_anomaly_detection_runtime_passes_the_contract() -> None:
    """The runtime returns a contract-valid advisory response.

    Independent: yes, because the request and response validators enforce the shared contract.
    """
    request = example_request()
    check_request(request)

    response = AnomalyDetectionAgent().run(request)

    check_response(request, response)
    assert response["agent"] == "anomaly_detection"
    assert response["request_id"] == request["request_id"]
    assert response["advisory_only"] is True
    assert response["result"]["no_event_means_healthy"] is False


def test_example_contains_every_expected_tag() -> None:
    """The official example holds all expected tags, so the detector is applicable to it.

    Independent: yes, because the fixture is compared with the unit table directly.
    """
    tags = {signal["tag_id"] for signal in signals_of(example_request())}
    assert tags == set(anomaly_agent.EXPECTED_UNITS)


def test_anomaly_detection_reports_runtime_implementation() -> None:
    """The runtime identifies its actual implementation and artifact.

    Independent: yes, because implementation metadata is checked separately from detection.
    """
    response = AnomalyDetectionAgent().run(example_request())

    assert response["implementation"]["name"] == "anomaly_detection"
    assert response["implementation"]["version"] == anomaly_agent.VERSION
    assert response["implementation"]["artifact_sha256"] == anomaly_agent.EXPECTED_ARTIFACT_SHA256


def test_consumed_evidence_matches_the_request() -> None:
    """Without attachments, consumed and cited evidence are the observation evidence ids.

    Independent: yes, because the expected ids are read from the request, not the agent.
    """
    request = example_request()
    known = {row["evidence_id"] for row in request["evidence"]}
    expected = [e for e in request["input"]["observations"]["evidence_ids"] if e in known]

    response = AnomalyDetectionAgent().run(request)

    assert response["consumed_evidence_ids"] == expected
    for event in response["result"]["events"]:
        assert set(event["evidence_ids"]) <= set(expected)
    for issue in response["issues"]:
        assert set(issue.get("evidence_ids", [])) <= set(expected)


def test_anomaly_detection_consumes_attached_forecast_report() -> None:
    """An attached upstream report is listed as consumed evidence. Independent: yes."""
    request = example_request()
    report_id = attach_forecast(request)

    response = AnomalyDetectionAgent().run(request)

    assert report_id in response["consumed_evidence_ids"]
    check_response(request, response)


# Quality rules


def run_checked(request: dict[str, Any]) -> dict[str, Any]:
    """Run the agent and fail with its issues if it returned an error response."""
    response = AnomalyDetectionAgent().run(request)
    assert response["status"] != "error", response["issues"]
    return response


def keep_clean_signals(request: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep only the example's signals that are already complete and good.

    Signals are dropped rather than edited: the request validator checks the sample
    counts against each other, so editing them makes the request invalid.
    """
    clean = [
        s
        for s in signals_of(request)
        if not s.get("missing_samples")
        and not s.get("bad_quality_samples")
        and s.get("latest_availability") != "missing_sample"
        and s.get("latest_quality") not in anomaly_agent.NON_GOOD_QUALITY
        and anomaly_agent.has_current_value(s)
    ]
    assert clean, "the example has no clean signal"
    request["input"]["observations"]["summary"]["signals"] = clean
    return clean


def test_anomaly_detection_reports_quality_issues() -> None:
    """Reported missing and bad-quality samples produce quality events.

    Independent: yes, because the assertions inspect the output against explicit conditions.
    """
    categories = {
        e["category"] for e in AnomalyDetectionAgent().run(example_request())["result"]["events"]
    }

    assert "missing_reading" in categories
    assert "non_good_quality" in categories


def test_clean_window_has_no_quality_events() -> None:
    """A fully good window produces neither quality event (control for the rule tests).

    Independent: yes, because only signals the example already reports as clean are kept.
    """
    request = example_request()
    keep_clean_signals(request)
    update_observation_evidence_hash(request)

    categories = {e["category"] for e in run_checked(request)["result"]["events"]}

    assert not categories & {"missing_reading", "non_good_quality"}


@pytest.mark.parametrize("flag", ["suspect", "bad"])
def test_suspect_or_bad_latest_quality_is_reported(flag: str) -> None:
    """A suspect or bad latest-quality flag alone produces a non_good_quality event for that tag.

    Independent: yes, because only the quality flag of one clean signal is changed.
    """
    request = example_request()
    target = keep_clean_signals(request)[0]
    target["latest_quality"] = flag
    update_observation_evidence_hash(request)

    events = run_checked(request)["result"]["events"]
    quality = [e for e in events if e["category"] == "non_good_quality"]

    assert len(quality) == 1
    assert quality[0]["tag_ids"] == [target["tag_id"]]


def test_event_tag_ids_are_sorted() -> None:
    """Tag ids in every event are sorted and unique. Independent: yes."""
    request = example_request()
    for signal in signals_of(request):
        signal["latest_quality"] = "suspect"
    signals_of(request).reverse()
    update_observation_evidence_hash(request)

    for event in AnomalyDetectionAgent().run(request)["result"]["events"]:
        assert event["tag_ids"] == sorted(set(event["tag_ids"]))


# Model event, threshold and features


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0.36, False), (0.37, True), (0.38, True)],
)
def test_threshold_is_inclusive_and_read_from_the_artifact(
    monkeypatch: pytest.MonkeyPatch, score: float, expected: bool
) -> None:
    """A window is flagged exactly when score >= the artifact threshold.

    Independent: yes, because score and threshold are controlled. The three cases catch
    the comparison flipped to > or <=, and a hard-coded 0.5.
    """
    request = example_request()
    install_fake_artifact(monkeypatch, request, FakeModel(score), threshold=0.37)

    response = AnomalyDetectionAgent().run(request)

    assert bool(departures(response)) is expected
    check_response(request, response)


def test_model_event_on_a_flagged_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """A flagged window yields one departure that states its limits and an uncalibrated score.

    Independent: yes, because model output is explicitly controlled.
    """
    request = example_request()
    install_fake_artifact(monkeypatch, request, FakeModel(0.99))

    response = AnomalyDetectionAgent().run(request)
    events = departures(response)

    assert len(events) == 1
    event = events[0]
    assert event["score"] == {
        "value": 0.99,
        "kind": "decision_score",
        "method_id": anomaly_agent.MODEL_METHOD_ID,
        "calibration_id": None,
    }
    assert "The score is an uncalibrated decision score, not a probability." in event["limitations"]
    assert any("reading-arrival timing" in text for text in event["limitations"])
    assert any(f"F1 {anomaly_agent.TEST_F1:.2f}" in text for text in event["limitations"])
    assert set(anomaly_agent.DETECTOR_LIMITATIONS) <= set(response["limitations"])
    check_response(request, response)


def test_detection_uses_true_class_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """Detection uses the score of the True class, whatever the class order.

    Independent: yes, because class order and model scores are controlled.
    """
    request = example_request()
    install_fake_artifact(monkeypatch, request, FakeModel(0.90, classes=(True, False)))

    events = departures(AnomalyDetectionAgent().run(request))

    assert len(events) == 1
    assert events[0]["score"]["value"] == 0.90


def test_model_receives_features_in_artifact_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model input follows the feature order stored in the artifact.

    Independent: yes, because the model records its input.
    """
    request = example_request()
    valid = anomaly_agent.filter_valid_unit_signals(signals_of(request))
    feature_values = anomaly_agent.extract_features(valid)
    reversed_names = list(reversed(list(feature_values)))
    model = FakeModel(0.99)
    install_fake_artifact(monkeypatch, request, model, feature_names=reversed_names)

    response = AnomalyDetectionAgent().run(request)

    assert model.received_features.tolist() == [[feature_values[name] for name in reversed_names]]
    check_response(request, response)


def test_successful_model_run_omits_unavailable_limitation() -> None:
    """A successful model run does not report model unavailability. Independent: yes."""
    response = AnomalyDetectionAgent().run(example_request())

    assert anomaly_agent.MODEL_UNAVAILABLE_TEXT not in response["limitations"]
    assert not any(issue["code"] == "MODEL_UNAVAILABLE" for issue in response["issues"])


# Garbage input never yields an assessed answer


def test_empty_signals_return_insufficient_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty signal windows do not trigger model inference. Independent: yes."""
    request = example_request()
    request["input"]["observations"]["summary"]["signals"] = []
    update_observation_evidence_hash(request)
    forbid_model_loading(monkeypatch)

    response = AnomalyDetectionAgent().run(request)

    assert response["status"] == "degraded"
    assert response["result"]["coverage"] == "unknown"
    assert any(issue["code"] == "INSUFFICIENT_EVIDENCE" for issue in response["issues"])
    check_response(request, response)


def test_all_missing_measurements_return_insufficient_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All-missing physical measurements do not trigger model inference. Independent: yes."""
    request = example_request()
    for signal in signals_of(request):
        for name in anomaly_agent.NUMERIC_FIELDS:
            signal[name] = None
    update_observation_evidence_hash(request)
    forbid_model_loading(monkeypatch)

    response = AnomalyDetectionAgent().run(request)

    assert response["status"] == "degraded"
    assert response["result"]["coverage"] == "unknown"
    assert any(issue["code"] == "INSUFFICIENT_EVIDENCE" for issue in response["issues"])
    check_response(request, response)


def test_all_tags_reported_missing_keep_only_stale_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tags with no current reading, only a previous value, are not assessed.

    Independent: yes, because only the window's current-value fields are cleared.
    """
    request = example_request()
    for signal in signals_of(request):
        for name in anomaly_agent.CURRENT_VALUE_FIELDS:
            signal[name] = None
    update_observation_evidence_hash(request)
    forbid_model_loading(monkeypatch)

    response = run_checked(request)

    assert response["result"]["coverage"] == "unknown"
    assert response["status"] == "degraded"
    missing = [e for e in response["result"]["events"] if e["category"] == "missing_reading"]
    assert missing and set(missing[0]["tag_ids"]) == set(anomaly_agent.EXPECTED_UNITS)
    check_response(request, response)


def test_only_three_tags_are_not_assessed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A window with three tags is too incomplete for the aggregate detector.

    Independent: yes, because the signal list is truncated explicitly.
    """
    request = example_request()
    request["input"]["observations"]["summary"]["signals"] = signals_of(request)[:3]
    update_observation_evidence_hash(request)
    forbid_model_loading(monkeypatch)

    response = AnomalyDetectionAgent().run(request)

    assert response["status"] == "degraded"
    assert response["result"]["coverage"] == "partial"
    assert not departures(response)
    check_response(request, response)


def test_far_out_of_range_window_is_not_assessed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Features far outside the training range stop the detector from scoring.

    Independent: yes, because the training ranges are set so the example lies outside them.
    """
    request = example_request()
    valid = anomaly_agent.filter_valid_unit_signals(signals_of(request))
    features = anomaly_agent.extract_features(valid)
    ranges = {name: [value + 100.0, value + 101.0] for name, value in features.items()}
    model = FakeModel(0.99)
    install_fake_artifact(monkeypatch, request, model, feature_ranges=ranges)

    response = AnomalyDetectionAgent().run(request)

    assert model.received_features is None
    assert response["status"] == "degraded"
    assert response["result"]["coverage"] == "partial"
    assert not departures(response)
    check_response(request, response)


def test_one_unit_swap_is_partial_not_assessed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A unit swap excludes that tag; the result is degraded and partial.

    Independent: yes, because one unit is changed and the model is controlled.
    """
    request = example_request()
    signals_of(request)[0]["unit"] = "C" if signals_of(request)[0]["unit"] != "C" else "barg"
    update_observation_evidence_hash(request)
    install_fake_artifact(monkeypatch, request, FakeModel(0.1))

    response = AnomalyDetectionAgent().run(request)

    assert response["status"] == "degraded"
    assert response["result"]["coverage"] == "partial"
    assert any(issue["code"] == "INVALID_SIGNAL_UNIT" for issue in response["issues"])
    check_response(request, response)


def test_all_invalid_units_return_insufficient_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """All invalid signal units prevent model inference. Independent: yes."""
    request = example_request()
    for signal in signals_of(request):
        signal["unit"] = "invalid-unit"
    update_observation_evidence_hash(request)
    forbid_model_loading(monkeypatch)

    response = AnomalyDetectionAgent().run(request)

    assert response["status"] == "degraded"
    assert response["result"]["coverage"] == "unknown"
    assert any(issue["code"] == "INVALID_SIGNAL_UNIT" for issue in response["issues"])
    assert any(issue["code"] == "INSUFFICIENT_EVIDENCE" for issue in response["issues"])
    check_response(request, response)


def test_expected_signal_units_are_accepted() -> None:
    """Official tag-unit pairs are recognized. Independent: yes."""
    signals = signals_of(example_request())

    assert anomaly_agent.find_invalid_unit_signals(signals) == []
    assert len(anomaly_agent.filter_valid_unit_signals(signals)) == len(signals)


def test_unexpected_signal_unit_is_excluded() -> None:
    """A signal with an unexpected unit is excluded. Independent: yes."""
    signals = signals_of(example_request())
    tag = signals[0]["tag_id"]
    signals[0]["unit"] = "not-a-unit"

    assert anomaly_agent.find_invalid_unit_signals(signals) == [tag]
    assert all(s["tag_id"] != tag for s in anomaly_agent.filter_valid_unit_signals(signals))


def test_unknown_signal_tag_is_excluded() -> None:
    """Signals with unknown tags are excluded from inference. Independent: yes."""
    signals = signals_of(example_request())
    signals[0]["tag_id"] = "UNKNOWN-TAG"

    assert anomaly_agent.find_invalid_unit_signals(signals) == ["UNKNOWN-TAG"]
    assert all(
        s["tag_id"] != "UNKNOWN-TAG" for s in anomaly_agent.filter_valid_unit_signals(signals)
    )


# run() never lets an exception escape


def raise_runtime_error(*args: Any, **kwargs: Any) -> Any:
    """Stand-in for a failing dependency."""
    raise RuntimeError("simulated failure")


def fail_unless_error(real: Callable[..., Any]) -> Callable[..., Any]:
    """build_response that fails for every normal response but builds error responses."""

    def wrapper(request: dict[str, Any], **kwargs: Any) -> Any:
        if kwargs.get("status") != "error":
            raise RuntimeError("simulated failure")
        return real(request, **kwargs)

    return wrapper


def fail_first_call(real: Callable[..., Any]) -> Callable[..., Any]:
    """check_response that rejects the first (normal) response and validates the rest."""
    calls = {"count": 0}

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated failure")
        return real(*args, **kwargs)

    return wrapper


@pytest.mark.parametrize(
    "target",
    [
        "make_event",
        "build_response",
        "check_response",
        "check_request",
        "attached_report_ids",
        "find_invalid_unit_signals",
    ],
)
def test_internal_failures_return_a_validated_error(
    monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    """A failure in any dependency returns a validated error that still consumes the forecast id.

    Independent: yes, because each failure is injected and the error is checked by the
    real validator.
    """
    request = example_request()
    report_id = attach_forecast(request)
    real = getattr(anomaly_agent, target)
    replacement: Callable[..., Any] = raise_runtime_error
    if target == "build_response":
        replacement = fail_unless_error(real)
    elif target == "check_response":
        replacement = fail_first_call(real)
    monkeypatch.setattr(anomaly_agent, target, replacement)

    response = AnomalyDetectionAgent().run(request)

    assert response["status"] == "error"
    assert response["result"] is None
    assert any(issue["code"] == "INTERNAL_ERROR" for issue in response["issues"])
    assert report_id in response["consumed_evidence_ids"]
    check_response(request, response)


def test_invalid_request_returns_an_error_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """A request that fails validation gets an error response instead of an exception.

    Independent: yes, because the request validator is forced to reject the request.
    """
    request = example_request()
    monkeypatch.setattr(anomaly_agent, "check_request", raise_runtime_error)

    response = AnomalyDetectionAgent().run(request)

    assert response["status"] == "error"
    assert response["result"] is None
    assert any("contract validation" in json.dumps(issue) for issue in response["issues"])


def test_request_for_another_role_returns_an_error_response() -> None:
    """A request addressed to another role is answered with an error. Independent: yes."""
    request = copy.deepcopy(example_request())
    request["agent"] = "predictive_health"

    response = AnomalyDetectionAgent().run(request)

    assert response["status"] == "error"
    assert response["result"] is None


# Per-tag feature profile


def test_per_tag_features_cover_measured_tags_only() -> None:
    """Per-tag features cover every measured tag and no on/off, count or timing field.

    Independent: yes, because the names are compared with the unit table directly.
    """
    features = anomaly_agent.extract_per_tag_features(signals_of(example_request()))
    tags = {name.split("__")[0] for name in features}
    measured = {t for t, unit in anomaly_agent.EXPECTED_UNITS.items() if unit != "bool"}

    assert tags == measured
    assert {name.split("__")[1] for name in features} <= set(anomaly_agent.NUMERIC_FIELDS)
    assert not any(word in name for name in features for word in ("age", "count", "samples"))


def test_per_tag_features_keep_missing_as_nan_and_ignore_states() -> None:
    """A missing tag gives NaN (never 0.0), and pump or valve states give no feature.

    Independent: yes, because the inputs are built explicitly.
    """
    signals = [
        {"tag_id": "P-101A", "unit": "bool", "latest_value": True},
        {"tag_id": "PT-001", "unit": "barg", "mean": 3.5},
    ]
    features = anomaly_agent.extract_per_tag_features(signals)

    assert not any(name.startswith("P-101A") for name in features)
    assert features["PT-001__mean"] == 3.5
    assert math.isnan(features["PT-001__slope_per_s"])
    assert math.isnan(features["FT-001__mean"])


def test_per_tag_artifact_is_scored_with_per_tag_features(monkeypatch: pytest.MonkeyPatch) -> None:
    """An artifact naming the per-tag profile gets per-tag features and reports that profile.

    Independent: yes, because the model records its input and the expected vector is
    built separately.
    """
    request = example_request()
    profile = anomaly_agent.PER_TAG_PROFILE_ID
    expected = anomaly_agent.features_for(profile, signals_of(request))
    model = FakeModel(0.99)
    install_fake_artifact(monkeypatch, request, model, profile_id=profile)

    response = AnomalyDetectionAgent().run(request)

    received = model.received_features.tolist()[0]
    assert len(received) == len(expected)
    for got, want in zip(received, expected.values(), strict=True):
        assert (math.isnan(got) and math.isnan(want)) or got == want
    assert response["implementation"]["feature_profile_id"] == profile
    assert any("each measured tag" in text for text in departures(response)[0]["limitations"])
    check_response(request, response)


def test_unknown_feature_profile_is_model_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """An artifact naming an unknown profile is reported as an unavailable model.

    Independent: yes, because the profile id is set explicitly.
    """
    request = example_request()
    install_fake_artifact(monkeypatch, request, FakeModel(0.99))
    artifact = anomaly_agent.load_artifact()
    artifact["feature_profile_id"] = "not_a_profile"

    response = AnomalyDetectionAgent().run(request)

    assert any(issue["code"] == "MODEL_UNAVAILABLE" for issue in response["issues"])
    assert not departures(response)


def test_skill_constants_match_the_reports() -> None:
    """The stated F1 values and flagged share equal the shipped evaluation and test reports.

    Independent: yes, because the reports are written by the training run and read from disk.
    """
    folder = Path(__file__).parents[3] / "tools" / "agents" / "anomaly_detection_artifacts"
    evaluation = json.loads((folder / "evaluation_report.json").read_text(encoding="utf-8"))
    test = json.loads((folder / "test_report.json").read_text(encoding="utf-8"))

    chosen = evaluation["profiles"][evaluation["chosen_profile"]]
    validation = chosen["candidates"][evaluation["selected_model"]]["validation"]
    assert anomaly_agent.VALIDATION_F1 == pytest.approx(validation["f1"], abs=5e-4)
    assert anomaly_agent.ALWAYS_FLAG_VALIDATION_F1 == pytest.approx(
        evaluation["validation_baselines"]["always_flag"]["f1"], abs=5e-4
    )

    assert anomaly_agent.TEST_F1 == pytest.approx(test["selected"]["f1"], abs=5e-4)
    assert anomaly_agent.ALWAYS_FLAG_TEST_F1 == pytest.approx(
        test["baselines"]["always_flag"]["f1"], abs=5e-4
    )
    matrix = test["selected"]["confusion_matrix"]
    flagged = (matrix["true_positive"] + matrix["false_positive"]) / sum(matrix.values())
    assert anomaly_agent.TEST_FLAGGED_FRACTION == pytest.approx(flagged, abs=5e-3)


def test_loaded_model_runs_single_threaded() -> None:
    """After loading, every n_jobs parameter of the shipped model is 1.

    Independent: yes, because the shipped artifact is loaded and its estimator parameters are read.
    """
    model = anomaly_agent.load_artifact()["model"]
    jobs = {k: v for k, v in model.get_params().items() if k == "n_jobs" or k.endswith("__n_jobs")}

    assert jobs
    assert set(jobs.values()) == {1}


def test_repeated_scoring_gives_identical_floats() -> None:
    """Scoring each of 40 varied feature vectors 25 times gives one value, to the last digit.

    Independent: yes, because the vectors are the example window varied with a fixed seed.
    """
    artifact = anomaly_agent.load_artifact()
    base = anomaly_agent.extract_features(signals_of(example_request()))
    rng = random.Random(20261108)

    for _ in range(40):
        features = {
            name: value * (1 + 0.3 * rng.gauss(0, 1)) + 0.01 * rng.gauss(0, 1)
            for name, value in base.items()
        }
        scores = {
            anomaly_agent.decision_score(artifact["model"], features, artifact["feature_names"])
            for _ in range(25)
        }
        assert len(scores) == 1


def test_repeated_runs_give_identical_responses() -> None:
    """Twenty runs on one request give one response, including the score of the model event.

    Independent: yes, because the threshold is lowered in the loaded artifact to force an event.
    """
    anomaly_agent.load_artifact()["threshold"] = 0.0
    request = example_request()
    runs = {json.dumps(AnomalyDetectionAgent().run(copy.deepcopy(request))) for _ in range(20)}
    event = next(
        e
        for e in json.loads(next(iter(runs)))["result"]["events"]
        if e["category"] == "reported_signal_departure"
    )

    assert len(runs) == 1
    assert event["score"]["value"] >= 0.0
