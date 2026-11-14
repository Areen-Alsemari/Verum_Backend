"""Tests of the runner carrying window assessments across windows to Agents 5 and 8."""

from __future__ import annotations

import copy
import json
from collections.abc import Sequence
from typing import Any

import pytest

from _runner_cases import placeholders, snapshot
from verum.agents.common import ROLES, StubAgent
from verum.agents.runner import AssessmentLog, Bundle, run_analysis, verify_bundle

pytestmark = pytest.mark.fast
RULE = {"k": 2, "n": 3, "threshold": 1.5}
IDS = ["R1_mass_balance", "R2_pump_head", "R3_discharge_loss", "R4_receipt_line"]
RECEIVERS = ("diagnostic_reasoning", "evidence_verification_decision")
FIELDS = ("recent_anomaly_assessments", "persistence")


def assessment(score: float, complete: bool = True) -> dict[str, Any]:
    """A contract-valid window assessment with the given score."""
    return {
        "score": score, "window_threshold": 3.0, "exceeded": score > 3.0, "complete": complete,
        "persistence_rule": dict(RULE),
        "residuals": [{"residual_id": i, "state": "within_normal", "reason": None} for i in IDS],
    }  # fmt: skip


class Scripted:
    """Agent 2 that answers with the placeholder response plus a given assessment, or fails."""

    def __init__(self, item: dict[str, Any] | None, *, fail: bool = False) -> None:
        self.item, self.fail = item, fail

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("model file missing")
        response = StubAgent("anomaly_detection").run(request)
        if self.item is not None:
            response["result"]["window_assessment"] = copy.deepcopy(self.item)
        return response


def window(index: int, agent: Scripted, log: AssessmentLog) -> Bundle:
    """Run the placeholders with the scripted Agent 2 on window number index of run C7."""
    agents: dict[str, Any] = {**placeholders(), "anomaly_detection": agent}
    snap = snapshot(as_of_s=300.0 * (index + 1))
    return run_analysis(snap, "runtime", agents=agents, recent=log)


def sequence(agents: Sequence[Scripted]) -> list[Bundle]:
    """Consecutive windows of one run, each given the log of the one before."""
    bundles, log = [], AssessmentLog()
    for i, agent in enumerate(agents):
        bundles.append(window(i, agent, log))
        log = bundles[-1].assessments
    return bundles


def answer(bundle: Bundle, role: str = "diagnostic_reasoning") -> bool | None:
    """The persistence answer in the request of a role."""
    value: bool | None = bundle.requests[role]["input"]["persistence"]["alarming"]
    return value


def test_the_first_window_carries_the_fields_and_no_answer() -> None:
    """The first window has one recent assessment and an unknown answer.

    Independent: yes, because the contract validator checks each request separately.
    """
    bundle = sequence([Scripted(assessment(9.0))])[0]
    for role in RECEIVERS:
        fields = bundle.requests[role]["input"]
        assert len(fields["recent_anomaly_assessments"]) == 1
        assert fields["persistence"]["alarming"] is None
    verify_bundle(bundle)


def test_only_agents_5_and_8_receive_the_fields() -> None:
    """No other role gets either field.

    Independent: yes, because the check reads the requests of all eight roles.
    """
    bundle = sequence([Scripted(assessment(9.0))])[0]
    for role in ROLES:
        has = any(name in bundle.requests[role]["input"] for name in FIELDS)
        assert has == (role in RECEIVERS), role


def test_two_of_three_exceeding_windows_alarm_in_both_receivers() -> None:
    """Scores 2.0, 0.1, 2.0 against the published threshold of 1.5 give true.

    Independent: yes, because the count follows from the scores and the threshold.
    """
    bundles = sequence([Scripted(assessment(s)) for s in (2.0, 0.1, 2.0)])
    assert [answer(b) for b in bundles] == [None, None, True]
    assert answer(bundles[-1], "evidence_verification_decision") is True
    verify_bundle(bundles[-1])


def test_one_exceeding_window_in_three_is_false() -> None:
    """Scores 2.0, 0.1, 0.2 leave the rule unmet with every window known.

    Independent: yes, because one is below k of 2.
    """
    bundles = sequence([Scripted(assessment(s)) for s in (2.0, 0.1, 0.2)])
    assert answer(bundles[-1]) is False


def test_a_failing_agent_2_leaves_the_answer_unknown() -> None:
    """A window in which Agent 2 raised counts as missing: unknown, never false.

    Independent: yes, because the missing window could have been above the threshold.
    """
    agents = [Scripted(assessment(0.1)), Scripted(None, fail=True), Scripted(assessment(0.1))]
    bundles = sequence(agents)
    assert bundles[1].reports["anomaly_detection"] is None
    assert answer(bundles[-1]) is None
    assert (
        bundles[-1].requests["diagnostic_reasoning"]["input"]["persistence"]["windows_unknown"] == 1
    )


def test_a_window_without_an_assessment_is_unknown() -> None:
    """An Agent 2 report that carries no assessment counts as missing.

    Independent: yes, because the placeholder response holds no window assessment.
    """
    bundles = sequence([Scripted(assessment(0.1)), Scripted(None), Scripted(assessment(0.1))])
    assert answer(bundles[-1]) is None


def test_the_log_keeps_only_the_windows_the_rule_needs_in_the_request() -> None:
    """The request lists the last n windows, oldest first, and not more.

    Independent: yes, because n is 3 in the published rule.
    """
    bundles = sequence([Scripted(assessment(0.1)) for _ in range(5)])
    shown = bundles[-1].requests["diagnostic_reasoning"]["input"]["recent_anomaly_assessments"]
    assert [row["as_of_s"] for row in shown] == [900.0, 1200.0, 1500.0]


def test_a_log_of_another_run_or_time_is_refused() -> None:
    """The runner refuses a log that does not belong to the snapshot's run or moves backwards.

    Independent: yes, because both refusals follow from the definition of a run.
    """
    bundle = sequence([Scripted(assessment(1.0)), Scripted(assessment(1.0))])[-1]
    with pytest.raises(ValueError, match="after the last window"):
        run_analysis(
            snapshot(as_of_s=300.0), "runtime", agents=placeholders(), recent=bundle.assessments
        )
    with pytest.raises(ValueError, match="one run"):
        run_analysis(
            snapshot(case_id="C8", as_of_s=9000.0), "runtime",
            agents=placeholders(), recent=bundle.assessments,
        )  # fmt: skip


def test_the_same_windows_give_the_same_requests() -> None:
    """Two runs of the same sequence produce identical requests for Agents 5 and 8.

    Independent: yes, because the check compares two runs of one input.
    """

    def requests() -> str:
        last = sequence([Scripted(assessment(s)) for s in (2.0, 0.1, 2.0)])[-1]
        return json.dumps([last.requests[r] for r in RECEIVERS], sort_keys=True)

    assert requests() == requests()
