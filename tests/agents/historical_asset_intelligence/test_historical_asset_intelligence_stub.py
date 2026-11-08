"""Check exact asset lookup, fact preservation, and history cutoffs."""

from __future__ import annotations

import json
from typing import Any

import pytest

from verum.agents.historical_asset_intelligence.agent import (
    HistoricalAssetIntelligenceAgent,
)
from verum.contracts.agent_interfaces import contract_directory


def _example_request() -> dict[str, Any]:
    path = contract_directory() / "examples" / "historical_asset_intelligence.request.json"
    request: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return request


def test_known_asset_without_history() -> None:
    """Report missing history without dropping the matched asset.

    Independent: yes, because the example provides an asset and no history.
    """
    request = _example_request()
    report = HistoricalAssetIntelligenceAgent().run(request)
    result = report["result"]

    assert report["status"] == "degraded"
    assert result["asset_records"] == [{"asset_id": "TK-101", "kind": "tank"}]
    assert result["history"] == []
    assert result["history_status"] == "no_verified_past_maintenance_supplied"
    assert result["missing_asset_ids"] == []


def test_exact_asset_match_preserves_unresolved_fact() -> None:
    """Keep the supplied fact unchanged and exclude a similarly named asset.

    Independent: yes, because the expected asset and fact are specified in the request.
    """
    request = _example_request()
    matched = {"asset_id": "TK-101", "kind": "tank"}
    similar = {"asset_id": "TK-1010", "kind": "tank"}
    fact = {
        "fact_id": "fact-tk101-roof-clearance",
        "asset_id": "TK-101",
        "field_path": "roof.clearance",
        "value": None,
        "unit": None,
        "source_locator": "Example design record",
        "parameter_status": "unresolved",
        "evidence_ids": request["input"]["reference_evidence_ids"],
    }
    request["input"].update(
        query_asset_ids=["TK-101", "TK-10"],
        assets=[matched, similar],
        declared_facts=[
            fact,
            {**fact, "fact_id": "fact-tk1010-roof-clearance", "asset_id": "TK-1010"},
        ],
    )

    result = HistoricalAssetIntelligenceAgent().run(request)["result"]

    assert result["asset_records"] == [matched]
    assert result["facts"] == [fact]
    assert result["missing_asset_ids"] == ["TK-10"]


def test_history_accepts_cutoff_and_rejects_future_records() -> None:
    """Accept history at the cutoff and reject requests containing later records.

    Independent: yes, because the fixture fixes the timestamps at and after the cutoff.
    """
    request = _example_request()
    cutoff = request["context"]["as_of_s"]
    eligible = {
        "schema_version": "0.7.0",
        "dataset": "inspection_history",
        "record_id": "HIST-000001",
        "asset_id": "TK-101",
        "kind": "work_order",
        "t_recorded_s": cutoff,
        "description": "Simulated maintenance record.",
        "work_type": "routine",
    }
    request["input"]["history"] = [eligible]

    result = HistoricalAssetIntelligenceAgent().run(request)["result"]

    assert result["history"] == [eligible]
    assert result["history_status"] == "simulated_records_available"

    future = {**eligible, "record_id": "HIST-000002", "t_recorded_s": cutoff + 1}
    request["input"]["history"] = [eligible, future]

    with pytest.raises(ValueError, match="history record was recorded after the cutoff"):
        HistoricalAssetIntelligenceAgent().run(request)