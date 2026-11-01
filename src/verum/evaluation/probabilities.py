"""Probability scores for evaluator-owned diagnostic distributions.

Inputs name the same exhaustive, mutually exclusive hypotheses before and after an inspection.
Entropy reduction measures concentration, while the change in truth log score records whether
that concentration favours the correct hypothesis. Neither score uses a requested gain estimate.
"""

from __future__ import annotations

import math
from collections.abc import Mapping


def distribution(values: Mapping[str, float]) -> dict[str, float]:
    """Validate a normalised finite distribution without filling or renormalising probabilities."""
    if not values or any(not isinstance(k, str) or not k for k in values):
        raise ValueError("hypotheses must be nonempty strings")
    if any(isinstance(v, bool) or not math.isfinite(v) or not 0 <= v <= 1
           for v in values.values()):
        raise ValueError("probabilities must be finite numbers in [0, 1]")
    if not math.isclose(math.fsum(values.values()), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("probabilities must sum to one")
    return dict(values)


def entropy_bits(values: Mapping[str, float]) -> float:
    """Shannon entropy in bits, with zero-probability terms contributing zero."""
    return -math.fsum(p * math.log2(p) for p in distribution(values).values() if p > 0)


def entropy_reduction_bits(
    before: Mapping[str, float], after: Mapping[str, float]
) -> float:
    """Prior entropy minus posterior entropy in bits; increased uncertainty gives negative gain."""
    if before.keys() != after.keys():
        raise ValueError("before and after must name the same hypotheses")
    return entropy_bits(before) - entropy_bits(after)


def brier_score(values: Mapping[str, float], truth: str) -> float:
    """Unnormalised multiclass Brier score, ranging from zero to two."""
    probabilities = distribution(values)
    if truth not in probabilities:
        raise ValueError("truth must be a named hypothesis")
    return math.fsum((p - float(name == truth)) ** 2 for name, p in probabilities.items())


def truth_log_gain_bits(
    before: Mapping[str, float], after: Mapping[str, float], truth: str
) -> float | None:
    """Change in log probability of truth in bits; zero support is reported as undefined."""
    prior, posterior = distribution(before), distribution(after)
    if prior.keys() != posterior.keys() or truth not in prior:
        raise ValueError("distributions must share hypotheses and include truth")
    if prior[truth] == 0 or posterior[truth] == 0:
        return None
    return math.log2(posterior[truth]) - math.log2(prior[truth])
