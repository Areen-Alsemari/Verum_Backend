"""Checks that registry hashes equal the hashes the contract validators compute.

A report that carries integral floats must stay valid when it is registered, embedded in a
downstream request and sent through JSON text.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from verum.agents.common import (
    EvidenceRegistry,
    build_response,
    check_request,
    check_response,
    implementation_block,
    stable_hash,
)
from verum.contracts.agent_interfaces import content_hash, contract_directory


def _example(role: str, kind: str) -> dict[str, Any]:
    path = contract_directory() / "examples" / f"{role}.{kind}.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _forecast_report() -> dict[str, Any]:
    """An Agent 1 style response whose result holds the floats 0.0, 1.0 and 300.0."""
    request = _example("predictive_health", "request")
    forecast = {
        "tag_id": "FT-001", "unit": "m3/h", "quantity": "reported_mean", "horizon_s": 300.0,
        "value": 0.0,
        "interval": {
            "lower": 0.0, "upper": 1.0, "coverage_probability": 0.95, "calibration_id": "cal-1",
        },
        "evidence_ids": ["source-observations"], "limitations": ["Test forecast."],
    }
    result = {
        "forecasts": [forecast], "health_score": None, "remaining_useful_life": None,
        "field_qualified": False,
    }
    response = build_response(
        request, status="degraded", result=result,
        consumed_evidence_ids=["source-observations", "source-reference", "features-summary"],
        implementation=implementation_block("test-forecaster", "1"),
    )
    check_response(request, response)
    return response


def _downstream_request(report: dict[str, Any], embed: str) -> dict[str, Any]:
    request = _example("anomaly_detection", "request")
    registry = EvidenceRegistry.from_rows(request["context"], request["evidence"])
    registered = registry.add_report(report)
    request["input"]["forecast_report"] = registered if embed == "returned" else report
    request["evidence"] = registry.rows()
    return request


@pytest.mark.parametrize("embed", ["returned", "original"])
@pytest.mark.parametrize("through_json", [False, True])
def test_a_registered_report_with_integral_floats_passes_the_validator(
    embed: str, through_json: bool
) -> None:
    """The report row hash equals the validator's hash of the report as embedded and as sent.

    Independent: yes, because the contract validator recomputes every hash itself.
    """
    request = _downstream_request(_forecast_report(), embed)
    if through_json:
        request = json.loads(json.dumps(request))
    check_request(request)


def test_helper_hash_equals_the_contract_hash_for_integral_floats() -> None:
    """The helper hash of a message equals the contract hash of the same message.

    Independent: yes, because the contract hash is a separate routine.
    """
    report = _forecast_report()
    assert stable_hash(report) == content_hash(report)
    assert content_hash({"a": 300}) != content_hash({"a": 300.0})
