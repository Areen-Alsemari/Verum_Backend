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

    evidence = [
        {
            "evidence_id": response["report_id"],
            "kind": "agent_report",
            "content_sha256": content_hash(response),
        }
    ]

    for identifier in response["consumed_evidence_ids"]:
        evidence.append(
            {
                "evidence_id": identifier,
                "kind": "observation_window",
                "content_sha256": "0" * 64,
            }
        )

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