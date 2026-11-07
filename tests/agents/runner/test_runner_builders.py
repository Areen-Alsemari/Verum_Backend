"""Checks of the request builders: valid requests from a snapshot, nothing invented."""

from __future__ import annotations

import pytest

from _runner_cases import reference, run, snapshot
from verum.agents.common import TAG_ORDER, check_request
from verum.agents.runner.facts import reference_facts
from verum.agents.runner.wiring import UPSTREAM


def _codes(bundle_notes: list[dict[str, str]]) -> set[tuple[str, str]]:
    return {(n["role"], n["code"]) for n in bundle_notes}


def test_every_built_request_passes_the_contract() -> None:
    """All eight built requests validate and carry the runtime context of the snapshot.

    Independent: yes, because the contract validator is separate from the builders.
    """
    bundle = run()
    assert len(bundle.requests) == 8
    for request in bundle.requests.values():
        check_request(request)
        assert request["context"] == bundle.context and request["context"]["revision"] == 0


def test_forecast_request_targets_the_numeric_instruments_in_the_fixed_order() -> None:
    """Agent 1 asks for the 14 numeric instruments of the reference, in the tag order.

    Independent: yes, because the expected set is counted from the reference units.
    """
    request = run().requests["predictive_health"]
    expected = [
        t for t in TAG_ORDER
        if next(i["unit"] for i in reference()["instruments"] if i["tag_id"] == t) != "bool"
    ]
    assert request["input"]["target_tag_ids"] == expected and len(expected) == 14
    assert request["input"]["forecast_horizon_s"] == 300.0


def test_graph_and_asset_requests_come_from_the_reference() -> None:
    """The declared connections, assets and catalogue equal those of the reference.

    Independent: yes, because the reference is read separately.
    """
    bundle, ref = run(), reference()
    assert bundle.requests["topology_dependency"]["input"]["declared_connections"] == (
        ref["connections"]
    )
    assert bundle.requests["historical_asset_intelligence"]["input"]["assets"] == ref["assets"]
    planning = bundle.requests["inspection_planning"]["input"]
    assert planning["catalog"] == ref["inspection_catalog"]
    assert planning["catalog_evidence_ids"] == ["source-reference"]
    assert planning["workflow_requests"] == [] and planning["constraint_checks"] == []
    assert planning["budget"] == {"max_cost_usd": None, "max_duration_min": None}


def test_defaults_are_empty_and_noted_not_invented() -> None:
    """Absent history, results, proposals, budget and constraints stay empty and are noted.

    Independent: yes, because the expected notes are literals.
    """
    bundle = run()
    quality = bundle.requests["inspection_quality_documentation"]["input"]
    assert quality["inspection_results"] == [] and quality["inspection_requests"] == []
    assert bundle.requests["evidence_verification_decision"]["input"]["evidence_proposals"] == []
    assert bundle.requests["historical_asset_intelligence"]["input"]["history"] == []
    assert {
        ("historical_asset_intelligence", "NO_HISTORY_SUPPLIED"),
        ("historical_asset_intelligence", "UNIT_NOT_DECLARED"),
        ("inspection_planning", "NO_BUDGET"), ("inspection_planning", "NO_CONSTRAINT_CHECKS"),
        ("inspection_quality_documentation", "NO_INSPECTION_RESULTS"),
        ("evidence_verification_decision", "NO_EVIDENCE_PROPOSALS"),
        ("all", "SOURCE_ROWS_NOT_SUPPLIED"),
    } <= _codes(bundle.notes)


def test_supplied_budget_and_history_flow_through() -> None:
    """A supplied budget is passed unchanged and its note disappears.

    Independent: yes, because the budget is a literal.
    """
    budget = {"max_cost_usd": 500.0, "max_duration_min": 120.0}
    bundle = run(snapshot=snapshot(budget=budget, source_sha256="ab" * 32))
    assert bundle.requests["inspection_planning"]["input"]["budget"] == budget
    codes = _codes(bundle.notes)
    assert ("inspection_planning", "NO_BUDGET") not in codes
    assert ("all", "SOURCE_ROWS_NOT_SUPPLIED") not in codes
    assert bundle.registry.row("source-observations")["content_sha256"] == "ab" * 32


def test_a_reference_without_a_catalogue_is_noted() -> None:
    """A missing catalogue gives an empty catalogue and a note, not an invented action.

    Independent: yes, because the reference is edited by the test.
    """
    ref = reference()
    ref["inspection_catalog"] = []
    bundle = run(snapshot=snapshot(reference=ref))
    assert bundle.requests["inspection_planning"]["input"]["catalog"] == []
    assert ("inspection_planning", "NO_CATALOG") in _codes(bundle.notes)


def test_facts_keep_only_stated_units_and_statuses() -> None:
    """Each fact value occurs in the reference; units and statuses appear only where stated.

    Independent: yes, because the facts are compared with the reference records.
    """
    ref = reference()
    facts = reference_facts(ref, "source-reference")
    by_id = {f["fact_id"]: f for f in facts}
    assert by_id["E002:length_m"]["value"] == ref["asset_facts"]["E002"]["length_m"]
    length = by_id["E002:length_m"]
    assert length["unit"] is None and length["parameter_status"] is None
    leaf = by_id["TK-101:roof_geometry_parameters.shell_diameter_m"]
    assert (leaf["unit"], leaf["parameter_status"], leaf["value"]) == ("m", "provisional", 30.0)
    assert all(f["evidence_ids"] == ["source-reference"] and f["source_locator"] for f in facts)
    assert len(by_id) == len(facts)


def test_upstream_wiring_matches_the_schemas() -> None:
    """The role-to-field map equals the report fields the schemas accept.

    Independent: yes, because the schemas are read separately.
    """
    import json
    import re

    from verum.contracts.agent_interfaces import contract_directory

    for role in UPSTREAM:
        text = (contract_directory() / f"{role}.schema.json").read_text(encoding="utf-8")
        schema = json.loads(text)
        fields = {
            key: re.search(r"agents:v1:(\w+)#", json.dumps(value)).group(1)  # type: ignore[union-attr]
            for key, value in schema["$defs"]["input"]["properties"].items()
            if key.endswith("_report")
        }
        assert fields == UPSTREAM[role], role


@pytest.mark.parametrize("role", sorted(UPSTREAM))
def test_a_role_with_upstream_reports_receives_them_hashed(role: str) -> None:
    """Every accepted upstream report is attached, registered and bound to its own hash.

    Independent: yes, because the contract validator recomputes each hash.
    """
    bundle = run()
    request = bundle.requests[role]
    for field in UPSTREAM[role]:
        report = request["input"][field]
        assert report is not None
        assert any(r["evidence_id"] == report["report_id"] for r in request["evidence"])
