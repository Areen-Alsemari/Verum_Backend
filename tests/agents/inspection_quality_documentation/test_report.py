"""Independent tests for maintenance report generation."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest

from verum.agents.common import ROLES
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

    with pytest.raises(ValueError, match="Mixed analysis context"):
        build_report(bundle)


Responses = dict[str, dict[str, Any]]


def _chained(role: str, kind: str) -> dict[str, Any]:
    """Load one chained fixture message for a role."""
    path = repo_root() / "tests" / "agents" / "fixtures" / "chained" / f"{role}.{kind}.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _full_bundle(edit: Callable[[Responses], None] | None = None) -> VerifiedBundle:
    """Create an eight-role bundle from the chained fixtures with registered hashes."""
    responses: Responses = {role: _chained(role, "response") for role in ROLES}
    if edit is not None:
        edit(responses)

    evidence: dict[str, dict[str, Any]] = {}
    for role in ROLES:
        for row in _chained(role, "request")["evidence"]:
            evidence.setdefault(row["evidence_id"], row)
    for response in responses.values():
        evidence[response["report_id"]] = {
            "evidence_id": response["report_id"],
            "kind": "agent_report",
            "content_sha256": content_hash(response),
        }

    return VerifiedBundle(
        context=copy.deepcopy(responses["evidence_verification_decision"]["context"]),
        responses=responses,
        evidence=list(evidence.values()),
        issues=(),
    )


def _fail(responses: Responses, role: str, status: str, code: str = "UPSTREAM_FAILED") -> None:
    """Turn one response into a resultless failure with a single issue."""
    responses[role]["status"] = status
    responses[role]["result"] = None
    responses[role]["issues"] = [{"code": code, "message": "Forced failure.", "evidence_ids": []}]


FIXED_FLAGS = {
    "advisory_only": True,
    "human_decision_required": True,
    "automatic_action_authorized": False,
    "equipment_condition_confirmed": False,
}


@pytest.mark.parametrize("status", ["insufficient_evidence", "error"])
def test_report_builds_when_planning_has_no_result(status: str) -> None:
    """Independent: a resultless planning report leaves the options section empty and explained.

    The planning response carries a null result, as the planner returns when no catalogue action
    matches, so the report must state that options are unavailable instead of failing.
    """
    code = "NO_COMPATIBLE_INSPECTION_OPTIONS"
    bundle = _full_bundle(lambda responses: _fail(responses, "inspection_planning", status, code))

    report = build_report(bundle)

    assert report["inspection_options"] == []
    notes = [note for note in report["missing_information"] if "options unavailable" in note]
    assert len(notes) == 1
    assert "inspection_planning" in notes[0]
    assert f"status={status}" in notes[0]
    assert code in notes[0]
    assert {key: report[key] for key in FIXED_FLAGS} == FIXED_FLAGS
    assert report["review_status"] == "human_review_required"


FAILURE_ROLES = [
    "predictive_health",
    "anomaly_detection",
    "topology_dependency",
    "historical_asset_intelligence",
    "diagnostic_reasoning",
    "inspection_planning",
    "evidence_verification_decision",
]


@pytest.mark.parametrize("role", FAILURE_ROLES)
@pytest.mark.parametrize("status", ["insufficient_evidence", "error"])
def test_failed_agent_is_listed_and_report_still_builds(role: str, status: str) -> None:
    """Independent: each failing agent appears once with its role, status and first issue code."""
    bundle = _full_bundle(lambda responses: _fail(responses, role, status, "FORCED_FAILURE"))

    report = build_report(bundle)

    listed = [note for note in report["missing_information"] if note.startswith("Failed agent")]
    assert listed == [f"Failed agent report: {role} status={status}; first issue: FORCED_FAILURE"]
    assert {key: report[key] for key in FIXED_FLAGS} == FIXED_FLAGS


def test_failed_agent_without_issues_lists_only_role_and_status() -> None:
    """Independent: a failure without an issue still names the role and status."""

    def edit(responses: Responses) -> None:
        _fail(responses, "predictive_health", "error")
        responses["predictive_health"]["issues"] = []

    report = build_report(_full_bundle(edit))

    assert "Failed agent report: predictive_health status=error" in report["missing_information"]


def test_failed_agents_are_listed_in_role_order() -> None:
    """Independent: several failures appear in the fixed role order, not the bundle order."""

    def edit(responses: Responses) -> None:
        for role in ("evidence_verification_decision", "predictive_health", "inspection_planning"):
            _fail(responses, role, "error", "FORCED_FAILURE")

    report = build_report(_full_bundle(edit))

    roles = [
        note.split()[3] for note in report["missing_information"] if note.startswith("Failed agent")
    ]
    assert roles == ["predictive_health", "inspection_planning", "evidence_verification_decision"]


def test_complete_agents_add_no_failure_notes() -> None:
    """Independent: when every agent is complete no failure or absence is listed."""

    def edit(responses: Responses) -> None:
        for response in responses.values():
            response["status"] = "complete"
            response["issues"] = []

    report = build_report(_full_bundle(edit))

    assert report["missing_information"] == []


def test_absent_agent_and_failed_agent_are_both_listed() -> None:
    """Independent: an absent role and a failed role are reported separately."""

    def edit(responses: Responses) -> None:
        del responses["anomaly_detection"]
        _fail(responses, "topology_dependency", "error", "FORCED_FAILURE")

    report = build_report(_full_bundle(edit))

    assert report["missing_information"] == [
        "Missing agent report: anomaly_detection",
        "Failed agent report: topology_dependency status=error; first issue: FORCED_FAILURE",
    ]


HUMAN_REVIEW_STATEMENT = (
    "Advisory assessment only; human review is required and equipment condition is not confirmed."
)


def test_report_keeps_the_human_review_statement() -> None:
    """Independent: the human-review limitation is always part of the report."""
    for bundle in (_bundle(), _full_bundle()):
        assert HUMAN_REVIEW_STATEMENT in build_report(bundle)["limitations"]


@pytest.mark.parametrize(
    ("status", "state"),
    [("insufficient_evidence", "more_evidence_required"), ("error", "inconclusive")],
)
def test_failed_agent_8_is_never_shown_as_available(status: str, state: str) -> None:
    """Independent: an unavailable decision is reported as unresolved, not as an assessment."""
    bundle = _full_bundle(
        lambda responses: _fail(responses, "evidence_verification_decision", status)
    )

    report = build_report(bundle)

    assert report["assessment_state"] == state
    assert report["assessment_state"] != "assessment_available"
    assert report["narrative"]["text"] == f"Assessment unavailable: Agent 8 status is {status}."


def _option(action_id: str, target: str, feasibility: str, cost: float | None) -> dict[str, Any]:
    """Build one planning option with the fields the contract requires."""
    return {
        "option_id": f"{action_id}-{target}",
        "action_id": action_id,
        "target_asset": target,
        "addresses_hypothesis_ids": [],
        "feasibility": feasibility,
        "precondition_checks": [],
        "cost_usd": cost,
        "duration_min": 60.0,
        "expected_information_gain_bits": None,
        "information_gain_method_id": None,
        "limitations": [],
        "evidence_ids": [],
    }


PLANNED_OPTIONS = [
    _option("ACT-INSP-06", "TK-101", "unknown", 160.0),
    _option("ACT-INSP-03", "P-101A", "blocked", 140.0),
    _option("ACT-INSP-05", "TK-102", "eligible_for_human_review", None),
]


def test_report_copies_each_option_with_its_own_feasibility() -> None:
    """Independent: unknown, blocked and eligible options keep their state and numbers."""

    def edit(responses: Responses) -> None:
        responses["inspection_planning"]["result"]["options"] = copy.deepcopy(PLANNED_OPTIONS)

    bundle = _full_bundle(edit)
    report = build_report(bundle)
    source_id = bundle.responses["inspection_planning"]["report_id"]

    assert [
        (row["action_id"], row["target_asset"], row["feasibility"], row["cost_usd"])
        for row in report["inspection_options"]
    ] == [
        ("ACT-INSP-06", "TK-101", "unknown", 160.0),
        ("ACT-INSP-03", "P-101A", "blocked", 140.0),
        ("ACT-INSP-05", "TK-102", "eligible_for_human_review", None),
    ]
    assert {row["source_report_id"] for row in report["inspection_options"]} == {source_id}


def test_report_lists_agent_5_hypotheses_as_unconfirmed() -> None:
    """Independent: a diagnosis hypothesis is a finding marked unconfirmed with its questions."""

    def edit(responses: Responses) -> None:
        result = responses["diagnostic_reasoning"]["result"]
        result["assessment"] = "candidates_available"
        result["hypotheses"] = [
            {
                "hypothesis_id": "HYP-01-leak-E003",
                "components": [{"mechanism": "leak", "asset_id": "E003", "tag_id": None}],
                "score": None,
                "support_evidence_ids": ["source-observations"],
                "conflict_evidence_ids": [],
                "unresolved_questions": ["Is the flow reading confirmed on site?"],
            }
        ]

    report = build_report(_full_bundle(edit))

    (finding,) = [row for row in report["findings"] if row["kind"] == "hypothesis"]
    assert finding["finding_id"] == "hypothesis-HYP-01-leak-E003"
    assert finding["statement"].startswith("Unconfirmed hypothesis: leak")
    assert finding["evidence_ids"] == ["source-observations"]
    assert "Is the flow reading confirmed on site?" in report["missing_information"]


@pytest.mark.parametrize(
    ("field", "wrong", "message"),
    [
        ("human_decision_required", False, "human decision"),
        ("automatic_action_authorized", True, "Automatic action"),
        ("equipment_condition_confirmed", True, "Equipment condition"),
    ],
)
def test_report_rejects_a_wrong_agent_8_flag(field: str, wrong: bool, message: str) -> None:
    """Independent: an Agent 8 safety flag with the wrong value stops the report."""

    def edit(responses: Responses) -> None:
        responses["evidence_verification_decision"]["result"][field] = wrong

    with pytest.raises(ValueError, match=message):
        build_report(_full_bundle(edit))
