
"""Independent tests for maintenance report generation."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from verum.agents.inspection_quality_documentation.report import build_report
from verum.agents.runner.bundle import VerifiedBundle
from verum.contracts.agent_interfaces import content_hash
from verum.contracts.paths import repo_root


def _bundle() -> VerifiedBundle:
    """Create a fixture using the official Agent 8 contract example."""
    path = (
        repo_root()
        / "contracts"
        / "agents"
        / "v1"
        / "examples"
        / "evidence_verification_decision.response.json"
    )
    response: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    evidence = [{
        "evidence_id": response["report_id"],
        "kind": "agent_report",
        "content_sha256": content_hash(response),
    }]

    for identifier in response["consumed_evidence_ids"]:
        evidence.append({
            "evidence_id": identifier,
            "kind": "observation_window",
            "content_sha256": "0" * 64,
        })

    return VerifiedBundle(
        context=copy.deepcopy(response["context"]),
        responses={"evidence_verification_decision": response},
        evidence=evidence,
        issues=(),
    )


def test_report_preserves_agent_8_decision() -> None:
    """Independent: the final assessment matches Agent 8 exactly."""
    bundle = _bundle()
    report = build_report(bundle)
    decision = bundle.responses["evidence_verification_decision"]

    assert report["assessment_state"] == decision["result"]["decision_state"]
    assert report["findings"][0]["statement"] == decision["result"]["summary"]
    assert report["context"] == bundle.context


def test_report_preserves_source_hash() -> None:
    """Independent: source hashes match the registered response content."""
    bundle = _bundle()
    report = build_report(bundle)
    response = bundle.responses["evidence_verification_decision"]

    assert report["source_reports"][0]["report_id"] == response["report_id"]
    assert report["source_reports"][0]["content_sha256"] == content_hash(response)


def test_report_requires_agent_8() -> None:
    """Independent: final assembly fails without Agent 8."""
    bundle = _bundle()
    bundle.responses.clear()

    with pytest.raises(ValueError, match="Agent 8"):
        build_report(bundle)


def test_report_rejects_changed_hash() -> None:
    """Independent: a changed response invalidates its registered hash."""
    bundle = _bundle()
    bundle.responses["evidence_verification_decision"]["result"]["summary"] = "Changed"

    with pytest.raises(ValueError, match="hash mismatch"):
        build_report(bundle)


def test_report_rejects_mixed_revision() -> None:
    """Independent: responses from another revision are rejected."""
    bundle = _bundle()
    bundle.responses["evidence_verification_decision"]["context"]["revision"] += 1

    with pytest.raises(ValueError, match="Mixed analysis"):
        build_report(bundle)


def test_report_rejects_unknown_evidence() -> None:
    """Independent: unregistered evidence cannot appear in citations."""
    bundle = _bundle()
    bundle.responses["evidence_verification_decision"]["consumed_evidence_ids"].append(
        "unknown-evidence"
    )

    with pytest.raises(ValueError):
        build_report(bundle)


def test_report_rejects_nonfinite_values() -> None:
    """Independent: non-finite numeric values cannot enter the report."""
    bundle = _bundle()
    bundle.context["as_of_s"] = float("nan")

    with pytest.raises(ValueError, match="Non-finite"):
        build_report(bundle)


def test_report_is_deterministic() -> None:
    """Independent: identical inputs produce identical outputs."""
    bundle = _bundle()

    assert build_report(bundle) == build_report(bundle)


def test_report_never_authorizes_automatic_action() -> None:
    """Independent: the report remains advisory and requires human review."""
    report = build_report(_bundle())

    assert report["advisory_only"] is True
    assert report["human_decision_required"] is True
    assert report["automatic_action_authorized"] is False
    assert report["equipment_condition_confirmed"] is False


def test_report_records_missing_agent_sections() -> None:
    """Independent: missing upstream reports are explicitly documented."""
    report = build_report(_bundle())

    assert "Missing agent report: diagnostic_reasoning" in report["missing_information"]
    assert "Missing agent report: inspection_planning" in report["missing_information"]
    assert "Missing agent report: inspection_quality_documentation" in report[
        "missing_information"
    ]


def test_report_preserves_inspection_option_values() -> None:
    """Independent: planning values and citations are copied without alteration."""
    bundle = _bundle()
    decision = bundle.responses["evidence_verification_decision"]

    planning = {
        "agent": "inspection_planning",
        "report_id": "test-planning-report",
        "context": copy.deepcopy(bundle.context),
        "limitations": [],
        "result": {
            "options": [{
                "option_id": "option-1",
                "action_id": "ACT-INSP-01",
                "target_asset": "test-asset",
                "feasibility": "eligible_for_human_review",
                "cost_usd": 125.5,
                "duration_min": 45.0,
                "evidence_ids": ["planning-evidence"],
            }],
        },
    }

    bundle.responses["inspection_planning"] = planning
    bundle.evidence.append({
        "evidence_id": "planning-evidence",
        "kind": "inspection_request",
        "content_sha256": "0" * 64,
    })
    bundle.evidence.append({
        "evidence_id": planning["report_id"],
        "kind": "agent_report",
        "content_sha256": content_hash(planning),
    })

    report = build_report(bundle)
    option = report["inspection_options"][0]

    assert option["action_id"] == "ACT-INSP-01"
    assert option["target_asset"] == "test-asset"
    assert option["cost_usd"] == 125.5
    assert option["duration_min"] == 45.0
    assert option["feasibility"] == "eligible_for_human_review"
    assert option["source_report_id"] == planning["report_id"]
    assert option["evidence_ids"] == ["planning-evidence"]
    assert report["assessment_state"] == decision["result"]["decision_state"]


def test_report_rejects_nonfinite_planning_cost() -> None:
    """Independent: non-finite planning costs are rejected."""
    bundle = _bundle()
    response = bundle.responses["evidence_verification_decision"]
    response["result"]["summary"] = "Valid assessment"
    bundle.evidence[0]["content_sha256"] = content_hash(response)

    bundle.responses["inspection_planning"] = {
        "agent": "inspection_planning",
        "report_id": "invalid-planning",
        "context": copy.deepcopy(bundle.context),
        "limitations": [],
        "result": {
            "options": [{
                "action_id": "ACT-INSP-01",
                "target_asset": "test-asset",
                "feasibility": "unknown",
                "cost_usd": float("inf"),
                "duration_min": 20.0,
                "evidence_ids": [],
            }],
        },
    }

    with pytest.raises(ValueError, match="Non-finite"):
        build_report(bundle)


def test_report_does_not_claim_inspection_performed() -> None:
    """Independent: proposed options never authorize or confirm maintenance."""
    report = build_report(_bundle())

    assert report["report_type"] == "maintenance_assessment"
    assert report["review_status"] == "human_review_required"
    assert report["automatic_action_authorized"] is False
    assert report["equipment_condition_confirmed"] is False


def test_report_rejects_changed_planning_values() -> None:
    """Independent: altered planning values invalidate the registered source hash."""
    bundle = _bundle()

    planning = {
        "agent": "inspection_planning",
        "report_id": "planning-integrity-test",
        "context": copy.deepcopy(bundle.context),
        "limitations": [],
        "result": {
            "options": [{
                "action_id": "ACT-INSP-01",
                "target_asset": "asset-1",
                "feasibility": "unknown",
                "cost_usd": 100.0,
                "duration_min": 30.0,
                "evidence_ids": [],
            }],
        },
    }

    bundle.responses["inspection_planning"] = planning
    bundle.evidence.append({
        "evidence_id": planning["report_id"],
        "kind": "agent_report",
        "content_sha256": content_hash(planning),
    })

    bundle.responses["inspection_planning"]["result"]["options"][0]["duration_min"] = 60.0

    with pytest.raises(ValueError, match="hash mismatch"):
        build_report(bundle)


def test_report_rejects_unknown_option_evidence() -> None:
    """Independent: inspection options cannot cite unregistered evidence."""
    bundle = _bundle()

    planning = {
        "agent": "inspection_planning",
        "report_id": "planning-evidence-test",
        "context": copy.deepcopy(bundle.context),
        "limitations": [],
        "result": {
            "options": [{
                "action_id": "ACT-INSP-01",
                "target_asset": "asset-1",
                "feasibility": "unknown",
                "cost_usd": 100.0,
                "duration_min": 30.0,
                "evidence_ids": ["unknown-option-evidence"],
            }],
        },
    }

    bundle.responses["inspection_planning"] = planning
    bundle.evidence.append({
        "evidence_id": planning["report_id"],
        "kind": "agent_report",
        "content_sha256": content_hash(planning),
    })

    with pytest.raises(ValueError, match="Unknown evidence"):
        build_report(bundle)


def test_report_does_not_invent_measurements() -> None:
    """Independent: no measured values appear without a measured source."""
    report = build_report(_bundle())

    assert all(
        finding["measurement"] is None
        for finding in report["findings"]
    )


def test_report_preserves_analysis_cutoff() -> None:
    """Independent: report context preserves the exact analysis cutoff."""
    bundle = _bundle()
    report = build_report(bundle)

    assert report["context"]["as_of_s"] == bundle.context["as_of_s"]
    assert report["context"]["revision"] == bundle.context["revision"]
    assert report["context"]["analysis_id"] == bundle.context["analysis_id"]


def test_report_rejects_unknown_role() -> None:
    """Reject a registered response from an unknown role."""
    bundle = _bundle()
    response = copy.deepcopy(bundle.responses["evidence_verification_decision"])
    response["agent"] = "unknown_role"
    response["report_id"] = "unknown_role-report-001"
    bundle.responses["unknown_role"] = response
    bundle.evidence.append({
        "evidence_id": response["report_id"],
        "kind": "agent_report",
        "content_sha256": content_hash(response),
    })

    with pytest.raises(ValueError, match="Unknown agent role"):
        build_report(bundle)


def test_report_accepts_all_eight_roles() -> None:
    """Assemble the complete official eight-role bundle."""
    from verum.agents.common import ROLES

    bundle = _bundle()
    examples = repo_root() / "contracts/agents/v1/examples"

    for role in ROLES:
        if role in bundle.responses:
            continue
        response = json.loads(
            (examples / f"{role}.response.json").read_text()
        )
        response["context"] = copy.deepcopy(bundle.context)
        bundle.responses[role] = response
        bundle.evidence.append({
            "evidence_id": response["report_id"],
            "kind": "agent_report",
            "content_sha256": content_hash(response),
        })
        for identifier in response["consumed_evidence_ids"]:
            known = {row["evidence_id"] for row in bundle.evidence}
            if identifier not in known:
                bundle.evidence.append({
                    "evidence_id": identifier,
                    "kind": "observation_window",
                    "content_sha256": "0" * 64,
                })

    report = build_report(bundle)
    assert {row["agent"] for row in report["source_reports"]} == set(ROLES)
    assert not any(
        item.startswith("Missing agent report:")
        for item in report["missing_information"]
    )


def test_report_builds_from_full_runner_chain() -> None:
    """Build a report from the verified eight-role runner chain."""
    from _runner_cases import run
    from verum.agents.common import ROLES
    from verum.agents.runner import verify_bundle

    bundle = run()
    verified = verify_bundle(bundle)

    assert set(verified.responses) == set(ROLES)
    report = build_report(verified)
    assert {row["agent"] for row in report["source_reports"]} == set(ROLES)
    assert not any(
        item.startswith("Missing agent report:")
        for item in report["missing_information"]
    )
