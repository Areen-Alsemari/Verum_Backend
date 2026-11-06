"""Checks of the context, registry and envelope builders against the contract validators."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from verum.agents.common import (
    ROLES,
    TAG_ORDER,
    EvidenceRegistry,
    StubAgent,
    attach_summary,
    build_request,
    build_response,
    check_request,
    check_response,
    implementation_block,
    make_context,
    make_context_from_reference,
    make_issue,
    report_id,
)
from verum.contracts.agent_interfaces import contract_directory

SNAPSHOT = "ab" * 32


def _example(role: str, kind: str) -> dict[str, Any]:
    path = contract_directory() / "examples" / f"{role}.{kind}.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _context(**changes: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "case_id": "C7", "revision": 0, "as_of_s": 300.0, "execution_mode": "runtime",
        "reference_snapshot_sha256": SNAPSHOT,
    }
    return make_context(**{**fields, **changes})


def _runtime_registry() -> tuple[EvidenceRegistry, dict[str, Any]]:
    """A runtime registry with the example summary registered through the adapter."""
    example = _example("predictive_health", "request")
    registry = EvidenceRegistry(_context())
    registry.add_source("src-obs", "observation_window", "window-300", 300.0, "cd" * 32)
    registry.add_source("src-ref", "declared_reference", "public_reference", 0.0, SNAPSHOT)
    observations = attach_summary(
        registry, example["input"]["observations"]["summary"], evidence_id="feat-summary",
        locator="summary-300", root_ids=["src-obs"], available_at_s=300.0,
    )
    return registry, observations


def test_context_has_the_contract_fields_and_derived_analysis_id() -> None:
    """A built context carries the fixed release and scope and derives the analysis identifier.

    Independent: yes, because the expected fields are literals.
    """
    context = _context(as_of_s=300.0)
    assert context["analysis_id"] == "AN-C7-r0"
    assert context["as_of_s"] == 300 and context["as_of_utc"] is None
    assert context["data_release"] == "verum_reference_v2"
    assert context["scope_id"] == "verum_supported_reference_v2"


@pytest.mark.parametrize(
    "change",
    [
        {"execution_mode": "live"}, {"reference_snapshot_sha256": "xyz"}, {"as_of_s": -1.0},
        {"as_of_s": float("nan")}, {"revision": -1},
    ],
)
def test_invalid_context_fields_are_rejected(change: dict[str, Any]) -> None:
    """A bad mode, digest, cutoff or revision is refused.

    Independent: yes, because the rejected values are literals.
    """
    with pytest.raises(ValueError):
        _context(**change)


def test_snapshot_identifier_is_the_byte_hash_of_the_reference_file(tmp_path: Path) -> None:
    """The snapshot identifier is the digest of the file bytes and changes with a single byte.

    Independent: yes, because the expected digest is computed with the standard library.
    """
    path = tmp_path / "reference"
    path.write_bytes(b"{}")
    fields: dict[str, Any] = {
        "case_id": "C7", "revision": 0, "as_of_s": 300.0, "execution_mode": "runtime",
    }
    first = make_context_from_reference(path, **fields)
    assert first["reference_snapshot_sha256"] == hashlib.sha256(b"{}").hexdigest()
    path.write_bytes(b"{} ")
    assert make_context_from_reference(path, **fields)["reference_snapshot_sha256"] != (
        first["reference_snapshot_sha256"]
    )


def test_registry_and_adapter_produce_a_request_the_contract_accepts() -> None:
    """A request built from helper output, with TAG_ORDER signals, passes the request validator.

    Independent: yes, because the contract validator is separate from the builders.
    """
    registry, observations = _runtime_registry()
    request = build_request(
        "predictive_health", "REQ-1", registry,
        {"observations": observations, "target_tag_ids": ["FT-001"], "forecast_horizon_s": 300.0},
    )
    check_request(request)
    assert [s["tag_id"] for s in request["input"]["observations"]["summary"]["signals"]] == list(
        TAG_ORDER
    )


def test_registry_rejects_duplicates_future_rows_and_report_like_ids() -> None:
    """A repeated identifier, a future representation and a role-prefixed source id are refused.

    Independent: yes, because the rejected inputs are literals.
    """
    registry, _ = _runtime_registry()
    with pytest.raises(ValueError, match="duplicate"):
        registry.add_source("src-obs", "observation_window", "w", 300.0, "cd" * 32)
    with pytest.raises(ValueError, match="role key"):
        registry.add_source("anomaly_detection-x", "declared_reference", "r", 0.0, SNAPSHOT)
    with pytest.raises(ValueError, match="future"):
        registry.add_representation("feat-late", "late", 301.0, {"a": 1}, ["src-obs"])
    with pytest.raises(ValueError, match="observation window"):
        registry.add_representation("feat-bad", "bad", 300.0, {"a": 1}, ["src-ref"])


def test_response_builder_enforces_status_rules() -> None:
    """Error and insufficient-evidence reports take no result and need an issue.

    Independent: yes, because the rejected combinations are literals.
    """
    request = _example("predictive_health", "request")
    block = implementation_block("x", "1")
    for status in ("error", "insufficient_evidence"):
        with pytest.raises(ValueError, match="no result"):
            build_response(
                request, status=status, result={"a": 1}, consumed_evidence_ids=[],
                implementation=block, issues=[make_issue("C", "m")],
            )
        with pytest.raises(ValueError, match="needs an issue"):
            build_response(
                request, status=status, result=None, consumed_evidence_ids=[], implementation=block
            )
    with pytest.raises(ValueError, match="carries a result"):
        build_response(
            request, status="degraded", result=None, consumed_evidence_ids=[], implementation=block
        )
    with pytest.raises(ValueError, match="status must be"):
        build_response(
            request, status="fine", result=None, consumed_evidence_ids=[], implementation=block
        )


def test_response_builder_copies_context_and_derives_the_report_identifier() -> None:
    """The response keeps the request context exactly and its identifier follows the id rule.

    Independent: no, because the identifier is recomputed with the same helper.
    """
    request = _example("predictive_health", "request")
    response = build_response(
        request, status="insufficient_evidence", result=None, consumed_evidence_ids=[],
        implementation=implementation_block("x", "1"), issues=[make_issue("C", "m")],
    )
    assert json.dumps(response["context"]) == json.dumps(request["context"])
    assert response["report_id"] == report_id(
        "predictive_health", request["context"]["analysis_id"], request["request_id"]
    )
    check_response(request, response)


def test_response_builder_rejects_unknown_consumed_ids_and_identifier_collisions() -> None:
    """Consumed evidence must exist in the request, and a report id cannot equal an evidence id.

    Independent: yes, because the rejected inputs are built from literals.
    """
    request = _example("predictive_health", "request")
    block = implementation_block("x", "1")
    issue = [make_issue("C", "m")]
    with pytest.raises(ValueError, match="distinct and present"):
        build_response(
            request, status="error", result=None, consumed_evidence_ids=["nope"],
            implementation=block, issues=issue,
        )
    clash = copy.deepcopy(request)
    clash["evidence"][0]["evidence_id"] = report_id(
        "predictive_health", request["context"]["analysis_id"], request["request_id"]
    )
    with pytest.raises(ValueError, match="collides"):
        build_response(
            clash, status="error", result=None, consumed_evidence_ids=[], implementation=block,
            issues=issue,
        )


def test_every_stub_report_chains_through_the_registry() -> None:
    """Stub reports, registered in workflow order, pass the contract at every downstream request.

    Independent: yes, because upstream rows, roots and hashes are validated by the contract.
    """
    requests = {role: _example(role, "request") for role in ROLES}
    reports: dict[str, dict[str, Any]] = {}
    wiring = {
        "anomaly_detection": {"forecast_report": "predictive_health"},
        "diagnostic_reasoning": {
            "forecast_report": "predictive_health", "anomaly_report": "anomaly_detection",
            "topology_report": "topology_dependency",
            "asset_report": "historical_asset_intelligence",
            "inspection_quality_report": "inspection_quality_documentation",
        },
        "inspection_planning": {"diagnosis_report": "diagnostic_reasoning"},
        "evidence_verification_decision": {
            "diagnosis_report": "diagnostic_reasoning",
            "inspection_plan_report": "inspection_planning",
            "inspection_quality_report": "inspection_quality_documentation",
        },
    }
    order = (
        "predictive_health", "topology_dependency", "historical_asset_intelligence",
        "inspection_quality_documentation", "anomaly_detection", "diagnostic_reasoning",
        "inspection_planning", "evidence_verification_decision",
    )
    for role in order:
        request = requests[role]
        registry = EvidenceRegistry.from_rows(request["context"], request["evidence"])
        for field, source in wiring.get(role, {}).items():
            request["input"][field] = registry.add_report(reports[source])
        request["evidence"] = registry.rows()
        check_request(request)
        reports[role] = StubAgent(role).run(request)
        assert reports[role]["status"] == "degraded"
        assert "stub" in reports[role]["implementation"]["name"]


def test_registry_rejects_a_report_from_another_snapshot() -> None:
    """A report with a different context cannot be registered.

    Independent: yes, because the mismatch is a literal change of the context.
    """
    request = _example("anomaly_detection", "request")
    response = _example("anomaly_detection", "response")
    registry = EvidenceRegistry.from_rows(request["context"], request["evidence"])
    response["context"]["revision"] = 1
    with pytest.raises(ValueError, match="different analysis snapshot"):
        registry.add_report(response)
    response["context"]["revision"] = 0
    response["consumed_evidence_ids"] = ["unknown"]
    with pytest.raises(ValueError, match="does not hold"):
        registry.add_report(response)
