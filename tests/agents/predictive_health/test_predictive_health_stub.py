"""Test the Predictive Health agent's Ridge and persistence forecasts."""

from __future__ import annotations

import json
from typing import Any

from verum.agents.predictive_health import PredictiveHealthAgent
from verum.contracts.agent_interfaces import contract_directory


def _example_request() -> dict[str, Any]:
    """Load a fresh copy of the published request for each test."""
    path = contract_directory() / "examples" / "predictive_health.request.json"
    request: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return request


def test_persistence_forecasts_the_current_window_mean() -> None:
    """Use the published flow example to distinguish mean from latest reading."""
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
    assert result["health_score"] is None
    assert result["remaining_useful_life"] is None
    assert result["field_qualified"] is False


def test_persistence_reports_an_unavailable_window_mean() -> None:
    """Keep the available forecast when another requested tag has no mean."""
    request = _example_request()
    request["input"]["target_tag_ids"] = ["FT-001", "LSHH-101"]

    report = PredictiveHealthAgent().run(request)
    forecasts = {row["tag_id"]: row for row in report["result"]["forecasts"]}

    assert report["status"] == "degraded"
    assert set(forecasts) == {"FT-001", "LSHH-101"}
    assert forecasts["FT-001"]["value"] == 594.78658931006
    assert forecasts["LSHH-101"]["value"] is None
    assert forecasts["LSHH-101"]["interval"] is None


def test_agent_uses_ridge_and_persistence_in_the_same_request() -> None:
    """Keep the baseline for FT-001 while applying Ridge to LT-101."""
    request = _example_request()
    request["input"]["target_tag_ids"] = ["LT-101", "FT-001"]
    signals = {
        row["tag_id"]: row
        for row in request["input"]["observations"]["summary"]["signals"]
    }

    report = PredictiveHealthAgent().run(request)
    forecasts = {row["tag_id"]: row for row in report["result"]["forecasts"]}

    assert report["status"] == "complete"
    assert set(forecasts) == {"LT-101", "FT-001"}
    assert forecasts["LT-101"]["value"] is not None
    assert forecasts["LT-101"]["value"] != signals["LT-101"]["mean"]
    assert forecasts["FT-001"]["value"] == signals["FT-001"]["mean"]