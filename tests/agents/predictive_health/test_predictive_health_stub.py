"""Test the Predictive Health agent's Ridge and persistence forecasts."""

from __future__ import annotations

import json
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError

from verum.agents.predictive_health import PredictiveHealthAgent
from verum.agents.predictive_health import agent as predictive_agent
from verum.contracts.agent_interfaces import contract_directory


def _example_request() -> dict[str, Any]:
    """Load a fresh copy of the published request for each test."""
    path = contract_directory() / "examples" / "predictive_health.request.json"
    request: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return request


def test_persistence_forecasts_the_current_window_mean() -> None:
    """Use the published flow example to distinguish mean from latest reading.

    Independent: yes, because the published request fixes the expected window mean.
    """
    report = PredictiveHealthAgent().run(_example_request())
    result = report["result"]
    (forecast,) = result["forecasts"]

    assert report["status"] == "complete"
    assert forecast["tag_id"] == "FT-001"
    assert forecast["unit"] == "m3/h"
    assert forecast["quantity"] == "reported_mean"
    assert forecast["horizon_s"] == 300
    assert forecast["value"] == 594.78658931006
    assert forecast["interval"] is None
    assert forecast["method"] == "persistence"
    assert result["health_score"] is None
    assert result["remaining_useful_life"] is None
    assert result["field_qualified"] is False


def test_persistence_reports_an_unavailable_window_mean() -> None:
    """Keep the available forecast when another requested tag has no mean.

    Independent: yes, because the request contains one measured mean and one missing mean.
    """
    request = _example_request()
    request["input"]["target_tag_ids"] = ["FT-001", "LSHH-101"]

    report = PredictiveHealthAgent().run(request)
    forecasts = {row["tag_id"]: row for row in report["result"]["forecasts"]}

    assert report["status"] == "degraded"
    assert set(forecasts) == {"FT-001", "LSHH-101"}
    assert forecasts["FT-001"]["value"] == 594.78658931006
    assert forecasts["LSHH-101"]["value"] is None
    assert forecasts["LSHH-101"]["interval"] is None


def test_agent_uses_ridge_and_persistence_in_the_same_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check both forecast methods and metadata with the original evidence.

    Independent: yes, because the injected model has a constant output.
    """
    _use_fixed_model(monkeypatch)
    artifact, _ = predictive_agent._ridge_artifact()
    model = artifact["models"]["LT-101"]
    model.update(
        base=8.75,
        weights=[0.0, 0.0, 0.0],
        missing_offsets=[0.0, 0.0, 0.0],
        training_ranges=dict.fromkeys(artifact["features"]),
    )
    request = _example_request()
    request["input"]["target_tag_ids"] = ["LT-101", "FT-001"]

    report = PredictiveHealthAgent().run(request)
    rows = {row["tag_id"]: row for row in report["result"]["forecasts"]}

    assert report["status"] == "complete"
    assert set(rows) == {"LT-101", "FT-001"}
    assert rows["LT-101"]["method"] == "ridge"
    assert rows["LT-101"]["value"] == 8.75
    assert rows["FT-001"]["method"] == "persistence"
    assert rows["FT-001"]["value"] == 594.78658931006
    assert report["implementation"]["artifact_sha256"] == "a" * 64
    assert report["implementation"]["feature_profile_id"] == "fixed-test-profile"
    assert PredictiveHealthAgent().run(request) == report


def _use_fixed_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a small artifact whose forecast can be computed by hand."""
    artifact = {
        "features": ["mean", "latest_value", "previous_measured_value"],
        "feature_profile_id": "fixed-test-profile",
        "models": {
            "LT-101": {
                "unit": "m",
                "base": 4.0,
                "weights": [2.0, -1.5, 7.0],
                "missing_offsets": [0.0, 0.0, 1.75],
                "training_ranges": {
                    "mean": [0.0, 10.0],
                    "latest_value": [0.0, 10.0],
                    "previous_measured_value": [0.0, 10.0],
                },
            }
        },
    }
    monkeypatch.setattr(predictive_agent, "_ridge_artifact", lambda: (artifact, "a" * 64))


@pytest.mark.parametrize(
    ("tags", "code"),
    [([], "NO_FORECAST_TARGETS"), (["UNKNOWN"], "TARGET_SIGNAL_MISSING")],
)
def test_unavailable_targets(tags: list[str], code: str) -> None:
    """Reject empty and unknown targets without producing forecast rows.

    Independent: yes, because neither query selects a known signal.
    """
    request = _example_request()
    request["input"]["target_tag_ids"] = tags
    report = PredictiveHealthAgent().run(request)
    assert report["status"] == "insufficient_evidence"
    assert report["result"] is None
    assert [issue["code"] for issue in report["issues"]] == [code]


@pytest.mark.parametrize(
    ("unit", "mean", "method", "expected", "code"),
    [
        ("cm", 3.0, "persistence", 3.0, "RIDGE_UNIT_MISMATCH"),
        ("m", -5.0, "unavailable", None, "RIDGE_INPUT_OUT_OF_RANGE"),
        ("m", 1e6, "unavailable", None, "RIDGE_INPUT_OUT_OF_RANGE"),
    ],
)
def test_ridge_guardrails(
    monkeypatch: pytest.MonkeyPatch,
    unit: str,
    mean: float,
    method: str,
    expected: float | None,
    code: str,
) -> None:
    """Check the forecast decision for mismatched units and out-of-range values.

    Independent: yes, because the unit and range are fixed in the test model.
    """
    _use_fixed_model(monkeypatch)
    artifact, _ = predictive_agent._ridge_artifact()
    signal = {"tag_id": "LT-101", "unit": unit, "mean": mean, "latest_value": 2.0}
    value, actual_method, actual_code, note = predictive_agent._predict(signal, artifact)

    assert actual_method == method
    assert value == expected
    assert actual_code == code
    assert note


def test_invalid_request_is_rejected() -> None:
    """Reject an unsupported horizon before trying to forecast.

    Independent: yes, because the request contract fixes the horizon at 300 seconds.
    """
    request = _example_request()
    request["input"]["forecast_horizon_s"] = 60
    with pytest.raises(ValidationError):
        PredictiveHealthAgent().run(request)


def test_artifact_failure_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return a report without a result when the artifact cannot be loaded.

    Independent: yes, because the artifact reader is forced to fail.
    """

    def fail() -> None:
        raise ValueError("Ridge coefficient length mismatch")

    monkeypatch.setattr(predictive_agent, "_ridge_artifact", fail)
    report = PredictiveHealthAgent().run(_example_request())
    assert report["status"] == "error"
    assert report["result"] is None
    assert [issue["code"] for issue in report["issues"]] == ["PREDICTIVE_HEALTH_FAILED"]


def test_ft201_uses_persistence() -> None:
    """Use the current window mean for FT-201 with the shipped artifact.

    Independent: yes, because persistence equals the request's current mean.
    """
    request = _example_request()
    request["input"]["target_tag_ids"] = ["FT-201"]
    signals = request["input"]["observations"]["summary"]["signals"]
    signal = next(row for row in signals if row["tag_id"] == "FT-201")
    report = PredictiveHealthAgent().run(request)
    (row,) = report["result"]["forecasts"]
    assert row["method"] == "persistence"
    assert row["value"] == signal["mean"]


def test_ridge_numeric_forecast_includes_missing_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin a Ridge forecast with distinct weights and one missing feature.

    Independent: yes, because 4 + 3 * 2 - 2 * 1.5 + 1.75 equals 8.75.
    """
    _use_fixed_model(monkeypatch)
    artifact, _ = predictive_agent._ridge_artifact()
    signal = {
        "tag_id": "LT-101",
        "unit": "m",
        "mean": 3.0,
        "latest_value": 2.0,
        "previous_measured_value": None,
    }
    value, method, code, note = predictive_agent._predict(signal, artifact)

    assert value == pytest.approx(8.75)
    assert method == "ridge"
    assert code is None
    assert note is None
