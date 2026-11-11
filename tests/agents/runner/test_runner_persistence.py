"""Tests for the persistence of window assessments, on small synthetic assessments."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from verum.agents.runner.persistence import AssessmentLog, attach_fields, persistence_of

pytestmark = pytest.mark.fast
RULE = {"k": 2, "n": 3, "threshold": 1.5}


def assessment(
    score: float, *, complete: bool = True, rule: dict[str, Any] = RULE
) -> dict[str, Any]:
    """A window assessment holding only what the runner reads."""
    return {"score": score, "complete": complete, "persistence_rule": dict(rule)}


def report_of(item: dict[str, Any]) -> dict[str, Any]:
    """A report whose result holds the given window assessment."""
    return {"result": {"window_assessment": item}}


def log_of(*items: dict[str, Any] | None) -> AssessmentLog:
    """A log with one window per item, 300 s apart; None is a window without an assessment."""
    log = AssessmentLog()
    for i, item in enumerate(items):
        log = log.extended("C1", 300.0 * (i + 1), item)
    return log


def alarming(*items: dict[str, Any] | None) -> bool | None:
    """The persistence answer after the given windows."""
    return persistence_of(log_of(*items).entries)["alarming"]


def test_the_first_window_gives_no_answer() -> None:
    """One window cannot settle a 2 of 3 rule, even when it exceeds.

    Independent: yes, because the rule needs three windows by definition.
    """
    result = persistence_of(log_of(assessment(9.0)).entries)
    assert result["alarming"] is None and result["windows_held"] == 1


def test_fewer_than_n_windows_is_null_even_when_all_exceed() -> None:
    """Two windows above the threshold are still not an answer for a 2 of 3 rule.

    Independent: yes, because the answer is defined only once n windows are held.
    """
    assert alarming(assessment(9.0), assessment(9.0)) is None


def test_two_of_three_exceeding_is_true() -> None:
    """Two of the last three scores above the threshold alarm, wherever they sit.

    Independent: yes, because the count follows from the scores and the threshold of 1.5.
    """
    assert alarming(assessment(2.0), assessment(0.1), assessment(2.0)) is True
    assert alarming(assessment(0.1), assessment(2.0), assessment(2.0)) is True


def test_one_of_three_exceeding_with_all_windows_known_is_false() -> None:
    """With every window known and one above the threshold, the answer is false.

    Independent: yes, because one is less than k of 2.
    """
    result = persistence_of(log_of(assessment(2.0), assessment(0.1), assessment(0.2)).entries)
    assert result["alarming"] is False and result["windows_unknown"] == 0


def test_only_the_last_n_windows_count() -> None:
    """An old exceedance outside the last three windows does not count.

    Independent: yes, because the first window is outside the last three.
    """
    assert alarming(assessment(2.0), assessment(2.0), assessment(0.1), assessment(0.1)) is False


def test_a_score_equal_to_the_threshold_does_not_exceed() -> None:
    """The comparison is strict, as in the registered rule.

    Independent: yes, because 1.5 is not above 1.5.
    """
    assert alarming(assessment(1.5), assessment(1.5), assessment(1.5)) is False


def test_a_missing_assessment_gives_unknown_not_false() -> None:
    """A window without an assessment leaves the answer unknown unless k are already above.

    Independent: yes, because the missing window could have been above the threshold.
    """
    assert alarming(assessment(2.0), None, assessment(0.1)) is None
    assert alarming(assessment(0.1), None, assessment(0.1)) is None
    assert alarming(assessment(2.0), assessment(2.0), None) is True


def test_a_window_that_is_within_but_incomplete_is_not_settled() -> None:
    """A low score with an unknown residual cannot show that the window was normal.

    Independent: yes, because the unknown residual could have exceeded.
    """
    assert alarming(assessment(0.1, complete=False), assessment(0.1), assessment(0.1)) is None
    assert alarming(assessment(2.0, complete=False), assessment(2.0), assessment(0.1)) is True


def test_an_assessment_under_another_rule_is_not_settled() -> None:
    """A window assessed under a different rule cannot be counted under the newest one.

    Independent: yes, because the thresholds are not comparable.
    """
    other = {"k": 2, "n": 3, "threshold": 0.5}
    assert alarming(assessment(2.0, rule=other), assessment(0.1), assessment(0.1)) is None


def test_no_rule_at_all_is_unknown_with_the_windows_counted() -> None:
    """If no window carries an assessment there is no rule and no answer.

    Independent: yes, because the rule is published only inside an assessment.
    """
    result = persistence_of(log_of(None, None, None).entries)
    assert result["rule"] is None and result["alarming"] is None and result["windows_held"] == 3


def test_a_malformed_assessment_leaves_persistence_unknown() -> None:
    """Whatever fails while the rule is applied, the answer is unknown and never false.

    Independent: yes, because the check compares the outcome with null, not with the rule.
    """
    broken = log_of(assessment(0.1), assessment(0.1), {"score": "high"})
    fields = attach_fields(broken, "C1", 1200.0, report_of({"score": "high"}))
    assert fields["persistence"]["alarming"] is None


def test_the_log_refuses_another_run_and_a_window_out_of_order() -> None:
    """A log belongs to one run and only moves forward in time.

    Independent: yes, because both refusals follow from the definition of a run.
    """
    log = log_of(assessment(1.0))
    with pytest.raises(ValueError, match="one run"):
        log.extended("C2", 900.0, None)
    with pytest.raises(ValueError, match="after the last window"):
        log.extended("C1", 300.0, None)


def test_the_log_is_not_changed_by_use_and_is_deterministic() -> None:
    """Attaching fields leaves the log as it was and gives the same answer twice.

    Independent: yes, because the check compares copies taken before and after.
    """
    log = log_of(assessment(2.0), assessment(0.1))
    before = copy.deepcopy(log)
    first = attach_fields(log, "C1", 900.0, report_of(assessment(2.0)))
    second = attach_fields(log, "C1", 900.0, report_of(assessment(2.0)))
    assert log == before and first == second
    assert first["persistence"]["alarming"] is True
    assert [e["as_of_s"] for e in first["recent_anomaly_assessments"]] == [300.0, 600.0, 900.0]
