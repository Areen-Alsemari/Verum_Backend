"""Analytic probability-score checks, including confidently incorrect posteriors.

Literal distributions give closed-form scores and exercise malformed probability records.
"""

from __future__ import annotations

import math

import pytest

from verum.evaluation.probabilities import (
    brier_score,
    distribution,
    entropy_bits,
    entropy_reduction_bits,
    truth_log_gain_bits,
)


def test_uniform_and_certain_distributions_have_closed_form_scores() -> None:
    """Four uniform hypotheses carry two bits and a certain correct forecast has zero Brier loss.

    Independent: yes, because the answers follow directly from the probability definitions.
    """
    uniform = dict.fromkeys(("a", "b", "c", "d"), 0.25)
    certain = {"a": 1.0, "b": 0.0, "c": 0.0, "d": 0.0}
    assert entropy_bits(uniform) == pytest.approx(2.0)
    assert entropy_reduction_bits(uniform, certain) == pytest.approx(2.0)
    assert brier_score(uniform, "a") == pytest.approx(0.75)
    assert brier_score(certain, "a") == 0.0
    assert brier_score(certain, "b") == 2.0


def test_wrong_confidence_is_distinct_from_information_about_truth() -> None:
    """Concentrating on a wrong answer lowers entropy but worsens the truth log score.

    Independent: yes, because the truth probability changes from one half to one tenth.
    """
    before, after = {"a": 0.5, "b": 0.5}, {"a": 0.1, "b": 0.9}
    assert entropy_reduction_bits(before, after) > 0
    assert truth_log_gain_bits(before, after, "a") == pytest.approx(math.log2(0.2))
    assert entropy_reduction_bits(after, before) < 0


@pytest.mark.parametrize("values", [
    {}, {"a": 0.9}, {"a": -0.1, "b": 1.1}, {"a": math.nan},
    {"a": math.inf}, {"": 1.0}, {"a": True},
])
def test_invalid_distributions_are_refused(values: dict[str, float]) -> None:
    """Missing mass, invalid names and nonfinite or out-of-range probabilities are rejected.

    Independent: yes, because each input violates an explicit probability constraint.
    """
    with pytest.raises(ValueError):
        distribution(values)


def test_hypothesis_changes_unknown_truth_and_zero_support_are_explicit() -> None:
    """Changed hypotheses and unknown truth raise; log gain with zero support is undefined.

    Independent: yes, because logarithms at zero and mismatched sample spaces are undefined.
    """
    with pytest.raises(ValueError):
        entropy_reduction_bits({"a": 1.0}, {"b": 1.0})
    with pytest.raises(ValueError):
        brier_score({"a": 1.0}, "b")
    with pytest.raises(ValueError):
        truth_log_gain_bits({"a": 1.0}, {"b": 1.0}, "a")
    assert truth_log_gain_bits({"a": 0.5, "b": 0.5}, {"a": 0.0, "b": 1.0}, "a") is None
    assert truth_log_gain_bits({"a": 0.0, "b": 1.0}, {"a": 0.5, "b": 0.5}, "a") is None
