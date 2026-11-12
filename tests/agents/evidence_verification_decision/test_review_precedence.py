"""Tests of the alert precedence of Agent 8 on small synthetic requests."""

from __future__ import annotations

import copy
import itertools
import json
import re
from pathlib import Path
from typing import Any

import pytest

from verum.agents.common import EvidenceRegistry, check_request, check_response
from verum.agents.diagnostic_reasoning.rules import (
    enrich_hypothesis_with_rules,
    evaluate_upstream_checks,
)
from verum.agents.evidence_verification_decision import EvidenceVerificationDecisionAgent, alerts
from verum.agents.evidence_verification_decision.alerts import (
    ANOMALY_CHECK_ID,
    PERSISTENT_ALARM,
    RECORD_FAILED,
    RELIABLE_CONFLICT,
    RELIABLE_CONFLICT_OUTCOME,
    SUPPORTED_HYPOTHESIS,
    SUPPORTED_OUTCOME,
    detect_alerts,
    persistence_alarming,
)

pytestmark = pytest.mark.fast
ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "contracts/agents/v1/examples"
ROLES = (
    ("diagnostic_reasoning", "diagnosis_report"),
    ("inspection_planning", "inspection_plan_report"),
    ("inspection_quality_documentation", "inspection_quality_report"),
)
RULE = {"k": 2, "n": 3, "threshold": 1.5}


def persistence(alarming: bool | None) -> dict[str, Any]:
    """A persistence statement; false needs the rule and no unknown window."""
    unknown = 0 if alarming is not None else 3
    return {
        "rule": dict(RULE), "windows_held": 3, "windows_exceeding": 0,
        "windows_unknown": unknown, "alarming": alarming,
    }  # fmt: skip


def load(name: str) -> dict[str, Any]:
    """A stored contract example."""
    loaded: dict[str, Any] = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    return loaded


def reregister(request: dict[str, Any]) -> None:
    """Refresh the evidence rows of the embedded reports after a change."""
    rows = [r for r in request["evidence"] if r["kind"] != "agent_report"]
    registry = EvidenceRegistry.from_rows(request["context"], rows)
    for _, field in ROLES:
        if request["input"][field] is not None:
            registry.add_report(request["input"][field])
    request["evidence"] = registry.rows()


def build(
    anomaly: str = "unknown",
    alarming: bool | None | str = "absent",
    candidates: bool = False,
    record_fail: bool = False,
    proposals: bool = False,
    diagnosis: bool = True,
) -> dict[str, Any]:
    """An Agent 8 request with the anomaly check outcome, persistence and other inputs set."""
    request = load("evidence_verification_decision.request.json")
    registry = EvidenceRegistry.from_rows(request["context"], request["evidence"])
    for role, field in ROLES:
        request["input"][field] = registry.add_report(load(f"{role}.response.json"))
    request["evidence"] = registry.rows()
    report = request["input"]["diagnosis_report"]
    for check in report["result"]["upstream_checks"]:
        if check["check_id"] == ANOMALY_CHECK_ID:
            check["outcome"] = anomaly
    if candidates:
        report["result"]["assessment"] = "candidates_available"
        report["result"]["hypotheses"] = [hypothesis()]
    if record_fail:
        quality = request["input"]["inspection_quality_report"]
        quality["result"]["record_checks"] = [quality_record("fail")]
    if proposals:
        request["input"]["evidence_proposals"] = [proposal()]
        records = [quality_record("pass", usable=True)]
        if record_fail:
            records.append({**quality_record("fail"), "result_id": "inspection-result-2"})
        request["input"]["inspection_quality_report"]["result"]["record_checks"] = records
    if not diagnosis:
        request["input"]["diagnosis_report"] = None
    if alarming != "absent":
        request["input"]["persistence"] = persistence(
            None if alarming == "x" else bool(alarming) if alarming is not None else None
        )
    reregister(request)
    check_request(request)
    return request


def hypothesis() -> dict[str, Any]:
    """A candidate with no support or conflict beyond the observations."""
    return {
        "hypothesis_id": "hypothesis-1",
        "components": [{"mechanism": "leak", "asset_id": None, "tag_id": None}],
        "score": None, "support_evidence_ids": ["source-observations"],
        "conflict_evidence_ids": [], "unresolved_questions": [],
    }  # fmt: skip


def quality_record(outcome: str, usable: bool | None = None) -> dict[str, Any]:
    """An inspection quality record with one check of the given outcome."""
    check = {
        "check_id": "timing", "description": "Check timing", "outcome": outcome,
        "evidence_ids": ["source-observations"],
    }  # fmt: skip
    return {
        "result_id": "inspection-result-1", "checks": [check], "measurement_usable": usable,
        "scope_supported": usable, "equipment_condition_confirmed": False,
        "evidence_ids": ["source-observations"],
    }  # fmt: skip


def proposal() -> dict[str, Any]:
    """A proposal that points at an existing observation source."""
    return {
        "proposal_id": "proposal-1", "source_ref": "observations:training-prefix-at-300",
        "claimed_available_at_s": 300.0, "claimed_evidence_ids": ["source-observations"],
    }  # fmt: skip


def run(request: dict[str, Any]) -> dict[str, Any]:
    """Run Agent 8 and validate the response independently."""
    response = EvidenceVerificationDecisionAgent().run(request)
    check_response(request, response)
    result: dict[str, Any] = response["result"]
    return result


def kinds(result: dict[str, Any]) -> list[str]:
    """The kinds of the next steps."""
    return [step["kind"] for step in result["next_steps"]]


def test_without_an_alert_the_older_decision_stands() -> None:
    """With no persistence and no anomaly outcome, no proposal still means more evidence.

    Independent: yes, because the older agent returned this state for every such input.
    """
    for request in (build(), build(alarming=None), build(alarming=False)):
        assert run(request)["decision_state"] == "more_evidence_required"


def test_a_reliable_family_conflict_is_review_before_missing_evidence() -> None:
    """With the anomaly check failed and no proposal the decision is review, not more evidence.

    Independent: yes, because the outcome 'fail' is set directly in the diagnosis report.
    """
    result = run(build(anomaly=RELIABLE_CONFLICT_OUTCOME))
    assert result["decision_state"] == "review_required"
    assert "do not show the departure" in result["summary"]


def test_a_persistent_alarm_is_review_with_or_without_a_supported_hypothesis() -> None:
    """An alarming persistence statement gives review whatever the anomaly check says.

    Independent: yes, because the alarm is set directly in the persistence input.
    """
    for anomaly in ("unknown", SUPPORTED_OUTCOME):
        result = run(build(anomaly=anomaly, alarming=True))
        assert result["decision_state"] == "review_required"
        assert "at least 2 of the last 3 windows" in result["summary"]


def test_a_supported_hypothesis_is_review_unless_persistence_is_known_false() -> None:
    """Support gives review when persistence is unknown or absent, and not when it is false.

    Independent: yes, because the three persistence values are set directly.
    """
    for alarming in ("absent", None, "x"):
        state = run(build(anomaly=SUPPORTED_OUTCOME, alarming=alarming))["decision_state"]
        assert state == "review_required", alarming
    suppressed = run(build(anomaly=SUPPORTED_OUTCOME, alarming=False))
    assert suppressed["decision_state"] == "more_evidence_required"


def test_known_false_persistence_does_not_suppress_a_conflict_or_a_failed_record() -> None:
    """Persistence false only silences the support alert, never the conflict alerts.

    Independent: yes, because the conflict and the failed record are set in the reports.
    """
    conflict = build(anomaly=RELIABLE_CONFLICT_OUTCOME, alarming=False)
    assert run(conflict)["decision_state"] == "review_required"
    record = build(anomaly=SUPPORTED_OUTCOME, alarming=False, record_fail=True)
    assert run(record)["decision_state"] == "review_required"


def test_unknown_persistence_is_never_taken_as_false() -> None:
    """A null alarm, a missing field and a malformed field all read as unknown.

    Independent: yes, because only a boolean false may silence the support alert.
    """
    odd: list[Any] = [None, "no", 0, 1, {}, []]
    for value in odd:
        assert persistence_alarming({"alarming": value}) is None
    assert persistence_alarming(None) is None and persistence_alarming({}) is None
    assert persistence_alarming({"alarming": True}) is True
    assert persistence_alarming({"alarming": False}) is False


def test_the_alerts_come_in_the_fixed_order() -> None:
    """With all four alerts holding, they are listed in the fixed order in code and summary.

    Independent: yes, because the order is written out here from the design.
    """
    diagnosis = {"result": {"upstream_checks": [{"check_id": ANOMALY_CHECK_ID, "outcome": "fail"}]}}
    held = detect_alerts(
        diagnosis, [{"check_id": "plan:o:c", "evidence_ids": []}], persistence(True)
    )
    assert held == [RELIABLE_CONFLICT, RECORD_FAILED, PERSISTENT_ALARM]
    supported = {"result": {"upstream_checks": [{"check_id": ANOMALY_CHECK_ID, "outcome": "pass"}]}}
    records = [{"check_id": "quality:r:c", "evidence_ids": []}]
    assert detect_alerts(supported, records, persistence(True)) == [
        RECORD_FAILED, PERSISTENT_ALARM, SUPPORTED_HYPOTHESIS,
    ]  # fmt: skip
    summary = run(build(anomaly="fail", alarming=True, record_fail=True))["summary"]
    assert summary.index("do not show") < summary.index("inspection record check failed")
    assert summary.index("inspection record check failed") < summary.index("have departed")


def test_a_failed_record_check_is_an_alert_of_its_own() -> None:
    """A failed quality check gives review with a records step, with no anomaly outcome.

    Independent: yes, because the failed check is set in the quality report.
    """
    result = run(build(record_fail=True))
    assert result["decision_state"] == "review_required"
    assert (
        "review_records" in kinds(result) and "inspection record check failed" in result["summary"]
    )


def test_assessment_is_available_only_with_candidates_and_usable_proposals() -> None:
    """Over all combinations of the inputs, 'available' needs candidates and a usable proposal.

    Independent: yes, because the condition is written from the contract rule, not the agent.
    """
    for anomaly, alarming, candidates, proposals, fail, diag in itertools.product(
        ("unknown", "pass", "fail"), ("absent", None, False, True), (False, True),
        (False, True), (False, True), (False, True),
    ):  # fmt: skip
        request = build(anomaly, alarming, candidates and diag, fail, proposals, diag)
        result = run(request)
        if result["decision_state"] == "assessment_available":
            assert candidates and diag and proposals and result["evidence_checks"]
            assert all(c["usable"] is True for c in result["evidence_checks"])
            assert anomaly != "fail" and alarming is not True and not fail


def test_the_fixed_flags_hold_and_the_response_is_valid_in_every_branch() -> None:
    """Every state keeps the three fixed flags and an advisory response.

    Independent: yes, because the flags are compared with constants.
    """
    cases = [build(), build(anomaly="fail"), build(alarming=True), build(record_fail=True),
             build(anomaly="pass", candidates=True, proposals=True, alarming=False)]  # fmt: skip
    seen = set()
    for request in cases:
        response = EvidenceVerificationDecisionAgent().run(request)
        check_response(request, response)
        result = response["result"]
        seen.add(result["decision_state"])
        assert result["human_decision_required"] is True
        assert result["automatic_action_authorized"] is False
        assert result["equipment_condition_confirmed"] is False
        assert response["advisory_only"] is True
    assert {"review_required", "more_evidence_required"} <= seen


def test_an_alert_keeps_the_evidence_gap_visible_while_evidence_is_missing() -> None:
    """With no proposal an alert still lists a step to collect evidence and says so.

    Independent: yes, because there is no proposal in the request.
    """
    result = run(build(alarming=True))
    assert "collect_evidence" in kinds(result) and "also remains unavailable" in result["summary"]
    complete = run(build(anomaly="pass", candidates=True, proposals=True, alarming=True))
    assert complete["decision_state"] == "review_required"
    assert "collect_evidence" not in kinds(complete)
    assert "also remains unavailable" not in complete["summary"]


def test_an_alert_is_shown_without_a_diagnosis_report() -> None:
    """A persistent alarm still gives review when the diagnosis report is missing.

    Independent: yes, because the alarm is set in the persistence input only.
    """
    result = run(build(alarming=True, diagnosis=False))
    assert result["decision_state"] == "review_required"
    assert result["hypothesis_report_ids"] == [] and "collect_evidence" in kinds(result)


def test_the_decision_is_deterministic_and_the_request_is_untouched() -> None:
    """The same request gives the same response bytes and is not modified.

    Independent: yes, because the check compares two runs and a deep copy.
    """
    request = build(anomaly="fail", alarming=True)
    before = copy.deepcopy(request)
    agent = EvidenceVerificationDecisionAgent()
    assert json.dumps(agent.run(request), sort_keys=True) == json.dumps(
        agent.run(request), sort_keys=True
    )
    assert request == before


def test_the_agent_5_mapping_is_pinned_to_the_constants() -> None:
    """Agent 5 gives 'pass' for a supported hypothesis and 'fail' for a pump-family conflict.

    Independent: yes, because the outcomes come from the Agent 5 rules run on a synthetic report.
    """
    ids = {"R1": "R1_mass_balance", "R2": "R2_pump_head", "R3": "R3_discharge_loss",
           "R4": "R4_receipt_line"}  # fmt: skip

    def outcome(state: str) -> str:
        rows = [{"residual_id": rid, "state": state if k == "R2" else "within_normal",
                 "reason": None} for k, rid in ids.items()]  # fmt: skip
        window = {"score": 1.0, "window_threshold": 3.0, "exceeded": False, "complete": True,
                  "persistence_rule": dict(RULE), "residuals": rows}  # fmt: skip
        report = {"report_id": "A2", "status": "complete", "issues": [],
                  "result": {"events": [], "coverage": "assessed",
                             "window_assessment": window}}  # fmt: skip
        pump = {"hypothesis_id": "H1", "support_evidence_ids": [], "conflict_evidence_ids": [],
                "components": [{"mechanism": "pump", "asset_id": "P-101A", "tag_id": None}],
                "score": None, "unresolved_questions": []}  # fmt: skip
        inputs = {"anomaly_report": report}
        enriched = enrich_hypothesis_with_rules(pump, inputs, ["obs"])
        checks = evaluate_upstream_checks(inputs, [enriched])
        found: str = next(c["outcome"] for c in checks if c["check_id"] == alerts.ANOMALY_CHECK_ID)
        return found

    assert outcome("exceeded") == SUPPORTED_OUTCOME == "pass"
    assert outcome("within_normal") == RELIABLE_CONFLICT_OUTCOME == "fail"
    assert ANOMALY_CHECK_ID == "anomaly_report"


FORBIDDEN = re.compile(
    r"\b(approv\w*|authori[sz]\w*|confirm\w*|certif\w*|dispatch\w*|safe)\b", re.I
)
ALLOWED = (
    "Equipment condition is not confirmed.",
    "equipment condition is not confirmed.",
    "No equipment condition or automatic action is confirmed.",
    "Evidence identity does not establish physical truth.",
)


def texts(result: dict[str, Any], response_limits: list[str]) -> list[str]:
    """Every string of a decision that an operator reads."""
    found = [result["summary"], *response_limits]
    found += [step["description"] for step in result["next_steps"]]
    return found


def test_no_wording_implies_approval_confirmation_or_action() -> None:
    """The summary, steps and limitations of every branch avoid approval and confirmation words.

    Independent: yes, because the words are listed here and only negated sentences are allowed.
    """
    grid = [build(), build(anomaly="fail"), build(alarming=True), build(record_fail=True),
            build(anomaly="pass"), build(anomaly="pass", candidates=True, proposals=True),
            build(anomaly="pass", candidates=True, proposals=True, alarming=False)]  # fmt: skip
    for request in grid:
        response = EvidenceVerificationDecisionAgent().run(request)
        for text in texts(response["result"], response["limitations"]):
            for phrase in ALLOWED:
                text = text.replace(phrase, "")
            assert not FORBIDDEN.search(text), text
    for text in (*alerts.REASONS.values(), alerts.SIGNAL_TEXT, alerts.RECORDS_TEXT):
        assert not FORBIDDEN.search(text), text


def test_the_decision_states_and_step_kinds_of_the_contract_are_unchanged() -> None:
    """The schema still lists the same four states and the same four next-step kinds.

    Independent: yes, because the lists are read from the schema file.
    """
    path = ROOT / "contracts/agents/v1/evidence_verification_decision.schema.json"
    text = path.read_text(encoding="utf-8")
    result = json.loads(text)["$defs"]["result"]["properties"]
    assert set(result["decision_state"]["enum"]) == {
        "assessment_available", "more_evidence_required", "review_required", "inconclusive",
    }  # fmt: skip
    kinds_allowed = result["next_steps"]["items"]["properties"]["kind"]["enum"]
    assert set(kinds_allowed) == {
        "human_review", "collect_evidence", "review_records", "continue_observation",
    }  # fmt: skip
