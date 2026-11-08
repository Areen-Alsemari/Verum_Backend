"""Check exact asset lookup, fact preservation, and history cutoffs."""

from __future__ import annotations

import json
from typing import Any

import pytest
from tools.agents.historical_asset_intelligence_role_view import build_historical_asset_input

from verum.agents.historical_asset_intelligence import agent as historical_agent
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

    report = HistoricalAssetIntelligenceAgent().run(request)
    result = report["result"]

    missing_issues = [issue for issue in report["issues"] if issue["code"] == "ASSET_NOT_FOUND"]
    assert len(missing_issues) == 1
    assert "TK-10" in missing_issues[0]["message"]
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


def _history_record(asset_id: str, cutoff: float, record_id: str) -> dict[str, Any]:
    return {
        "schema_version": "0.7.0",
        "dataset": "inspection_history",
        "record_id": record_id,
        "asset_id": asset_id,
        "kind": "work_order",
        "t_recorded_s": cutoff,
        "description": "Simulated maintenance record.",
        "work_type": "routine",
    }


def test_partial_history_names_each_matched_asset_without_records() -> None:
    """Report each missing history while keeping the available record.

    Independent: yes, because only the first of three matched tanks has history.
    """
    request = _example_request()
    ids = ["TK-101", "TK-102", "TK-103"]
    record = _history_record(ids[0], request["context"]["as_of_s"], "HIST-000001")
    request["input"].update(
        query_asset_ids=ids,
        assets=[{"asset_id": asset_id, "kind": "tank"} for asset_id in ids],
        history=[record],
    )

    report = HistoricalAssetIntelligenceAgent().run(request)

    assert report["status"] == "degraded"
    assert report["result"]["history"] == [record]
    assert report["result"]["history_status"] == "simulated_records_available"
    assert report["result"]["missing_asset_ids"] == []
    issues = report["issues"]
    assert [issue["code"] for issue in issues] == ["NO_VERIFIED_PAST_MAINTENANCE"] * 2
    assert all(
        asset_id in issue["message"] for asset_id, issue in zip(ids[1:], issues, strict=True)
    )


@pytest.mark.parametrize("asset_id", ["tk-101", " TK-101", "TK-101 "])
def test_near_miss_does_not_match(asset_id: str) -> None:
    """Keep asset lookup case and whitespace sensitive.

    Independent: yes, because the supplied asset ID is exactly TK-101.
    """
    request = _example_request()
    request["input"]["query_asset_ids"] = [asset_id]
    report = HistoricalAssetIntelligenceAgent().run(request)

    assert report["status"] == "degraded"
    assert report["result"]["asset_records"] == []
    assert report["result"]["missing_asset_ids"] == [asset_id]
    assert [issue["code"] for issue in report["issues"]] == ["ASSET_NOT_FOUND"]


def test_empty_query() -> None:
    """Report an empty query without selecting any supplied assets.

    Independent: yes, because the request explicitly selects no IDs.
    """
    request = _example_request()
    request["input"]["query_asset_ids"] = []
    report = HistoricalAssetIntelligenceAgent().run(request)

    assert report["status"] == "degraded"
    assert report["result"]["asset_records"] == []
    assert report["result"]["missing_asset_ids"] == []
    assert report["result"]["history_status"] == "unknown"
    assert [issue["code"] for issue in report["issues"]] == ["EMPTY_ASSET_QUERY"]


def test_history_for_unmatched_asset_is_excluded() -> None:
    """Exclude history for a supplied asset outside the query.

    Independent: yes, because the only record belongs to the unrequested tank.
    """
    request = _example_request()
    request["input"]["assets"] = [
        {"asset_id": "TK-101", "kind": "tank"},
        {"asset_id": "TK-102", "kind": "tank"},
    ]
    request["input"]["history"] = [
        _history_record("TK-102", request["context"]["as_of_s"], "HIST-000001")
    ]
    report = HistoricalAssetIntelligenceAgent().run(request)

    assert report["status"] == "degraded"
    assert report["result"]["history"] == []
    assert report["result"]["history_status"] == "no_verified_past_maintenance_supplied"


def _fact(evidence_ids: list[str]) -> dict[str, Any]:
    return {
        "fact_id": "fact-tk101-clearance",
        "asset_id": "TK-101",
        "field_path": "roof.clearance",
        "value": None,
        "unit": None,
        "source_locator": "Example design record",
        "parameter_status": "unresolved",
        "evidence_ids": evidence_ids,
    }


def test_duplicate_asset_and_fact_ids_are_reported() -> None:
    """Report duplicates in the asset and fact lists.

    Independent: yes, because both identifiers are repeated in the input.
    """
    request = _example_request()
    payload = request["input"]
    asset = {"asset_id": "TK-101", "kind": "tank"}
    fact = _fact(payload["reference_evidence_ids"])
    payload.update(assets=[asset, dict(asset)], declared_facts=[fact, dict(fact)])

    report = HistoricalAssetIntelligenceAgent().run(request)

    assert report["status"] == "degraded"
    by_code = {issue["code"]: issue["message"] for issue in report["issues"]}
    assert "TK-101" in by_code["DUPLICATE_ASSET_ID"]
    assert fact["fact_id"] in by_code["DUPLICATE_FACT_ID"]


def test_fact_evidence_is_preserved_and_consumed() -> None:
    """Keep fact-level evidence even when it is not listed as reference evidence.

    Independent: yes, because the request gives the fact its own evidence ID.
    """
    request = _example_request()
    payload = request["input"]
    ref_ids = payload["reference_evidence_ids"]
    ref = next(row for row in request["evidence"] if row["evidence_id"] == ref_ids[0])
    fact_id = "source-extra-fact"
    request["evidence"].append({**ref, "evidence_id": fact_id, "root_evidence_ids": [fact_id]})
    fact = _fact([ref_ids[0], fact_id])
    payload["declared_facts"] = [fact]

    report = HistoricalAssetIntelligenceAgent().run(request)

    assert report["result"]["facts"] == [fact]
    assert report["result"]["evidence_ids"] == [*ref_ids, fact_id]
    assert report["consumed_evidence_ids"] == [*ref_ids, fact_id]


def test_lookup_failure_returns_error_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn a processing failure into a contract-valid error report.

    Independent: yes, because the lookup is forced to fail on a valid request.
    """

    def fail(_payload: dict[str, Any]) -> Any:
        raise RuntimeError("forced lookup failure")

    monkeypatch.setattr(historical_agent, "_collect_result", fail)
    report = HistoricalAssetIntelligenceAgent().run(_example_request())

    assert report["status"] == "error"
    assert report["result"] is None
    assert [issue["code"] for issue in report["issues"]] == ["HISTORICAL_ASSET_LOOKUP_FAILED"]


def test_role_view_adapter_builds_a_runnable_request() -> None:
    """Convert reference facts and missing history into a valid request.

    Independent: yes, because the input declares one tank and one scalar fact.
    """
    request = _example_request()
    evidence_id = request["input"]["reference_evidence_ids"][0]
    asset = {"asset_id": "TK-101", "kind": "tank"}
    role_input = {
        "query": {"asset_id": "TK-101"},
        "reference": {
            "assets": [asset],
            "asset_facts": {"TK-101": {"source": "Example design record", "diameter": 30}},
            "history": None,
        },
    }
    request["input"] = build_historical_asset_input(role_input, reference_evidence_id=evidence_id)
    report = HistoricalAssetIntelligenceAgent().run(request)

    assert report["status"] == "degraded"
    assert report["result"]["asset_records"] == [asset]
    assert report["result"]["history"] == []
    (fact,) = report["result"]["facts"]
    assert fact["field_path"] == "diameter"
    assert fact["value"] == 30
    assert fact["source_locator"] == "Example design record"
    assert fact["evidence_ids"] == [evidence_id]
