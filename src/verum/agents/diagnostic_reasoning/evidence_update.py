"""Odds update of hypothesis scores from the anomaly window assessment.

Each family has likelihood ratios, estimated on train windows only, for the state of each of its
expected residuals: how much more (or less) often the state occurs in windows with that fault
than in fault-free windows. The ratio file is pinned by its sha256 and read only after the hash
check. A score is updated in odds, s' = LR * s / (1 - s + LR * s), and stays in 0 to 1. An
unknown residual, a family with no expected residual, a hypothesis with no family and a report
with no usable window assessment give a ratio of 1, so the score is unchanged. Identifiers and
components are never touched; the list is only sorted again by the new score.
"""

from __future__ import annotations

import hashlib
import json
import math
from functools import cache
from pathlib import Path
from typing import Any, Final

from verum.agents.diagnostic_reasoning.mechanism import (
    RESIDUAL_IDS,
    family_of,
    usable_assessment,
)

RATIOS_PATH: Final = Path(__file__).resolve().parent / "evidence_ratios.json"
EXPECTED_RATIOS_SHA256: Final = "6d7cb3595ec850044f2b2b3c3f4add0f6f35581f0e462e13a8e91f0bfcb59443"
METHOD_SUFFIX: Final = "+a2_evidence_v1"
SCORE_DECIMALS: Final = 6


def load_ratios_from(path: Path, expected_sha256: str) -> dict[str, Any]:
    """Read the ratio file, refuse it unless its bytes match the pinned hash, then parse it."""
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("evidence ratio file hash mismatch")
    loaded = json.loads(raw.decode("utf-8"))
    if not isinstance(loaded, dict) or not isinstance(loaded.get("families"), dict):
        raise ValueError("invalid evidence ratio file")
    families: dict[str, Any] = loaded["families"]
    return families


@cache
def load_ratios() -> dict[str, Any]:
    """The ratios of the shipped file, verified once per process."""
    return load_ratios_from(RATIOS_PATH, EXPECTED_RATIOS_SHA256)


def residual_ratio(entry: dict[str, Any], key: str, state: str) -> float:
    """The ratio of one expected residual in one state; 1 for an unknown state."""
    if state not in ("exceeded", "within_normal"):
        return 1.0
    return float(entry["ratios"][key][state]["ratio"])


def combined_ratio(entry: dict[str, Any], states: dict[str, str]) -> float:
    """The ratio of a family for the states of its expected residuals."""
    ratios = [residual_ratio(entry, key, states[RESIDUAL_IDS[key]]) for key in entry["expected"]]
    if entry["combine"] == "largest":
        return max(ratios, key=lambda r: abs(math.log(r)))
    return math.prod(ratios)


def odds_update(score: float, ratio: float) -> float:
    """Multiply the odds of a score by a ratio; scores of exactly 0 or 1 stay."""
    if not 0.0 < score < 1.0 or ratio == 1.0:
        return score
    odds = score / (1.0 - score) * ratio
    return min(1.0, max(0.0, round(odds / (1.0 + odds), SCORE_DECIMALS)))


def hypothesis_ratio(
    hypothesis: dict[str, Any], assessment: dict[str, Any], ratios: dict[str, Any]
) -> float:
    """The ratio for a hypothesis, 1 when it has no family or no ratios."""
    family = family_of(hypothesis)
    if family is None or not family.expected or family.name not in ratios:
        return 1.0
    states = {row["residual_id"]: row["state"] for row in assessment["residuals"]}
    return combined_ratio(ratios[family.name], states)


def update_hypothesis(
    hypothesis: dict[str, Any], assessment: dict[str, Any], ratios: dict[str, Any]
) -> dict[str, Any]:
    """A copy of the hypothesis with its score updated; unchanged when the ratio is 1."""
    ratio = hypothesis_ratio(hypothesis, assessment, ratios)
    score = hypothesis.get("score")
    if score is None or ratio == 1.0:
        return hypothesis
    value = odds_update(float(score["value"]), ratio)
    method = score["method_id"]
    method = method if method.endswith(METHOD_SUFFIX) else method + METHOD_SUFFIX
    return {**hypothesis, "score": {**score, "value": value, "method_id": method}}


def update_scores(
    hypotheses: list[dict[str, Any]],
    anomaly_report: dict[str, Any] | None,
    ratios: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Update every score from the window assessment and sort again by the new score."""
    assessment = None if anomaly_report is None else usable_assessment(anomaly_report)
    if assessment is None:
        return hypotheses
    table = load_ratios() if ratios is None else ratios
    updated = [update_hypothesis(h, assessment, table) for h in hypotheses]
    return sorted(updated, key=lambda h: -(h["score"]["value"] if h["score"] else 0.0))
