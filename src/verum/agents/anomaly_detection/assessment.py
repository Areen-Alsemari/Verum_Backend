"""The window assessment of one scored window: score, thresholds, persistence rule, residuals.

Inputs: the residual results of one window and the pinned parameters. Output: the object the
response carries in its result. A residual is exceeded exactly when it has an event; a residual
that was not computed is unknown with a reason and is never reported as within normal. The
persistence rule is the one calibrated in the fit; applying it needs the scores of earlier
windows, which the caller holds. Assumption: the score is the largest computed residual.
"""

from __future__ import annotations

from typing import Any

from verum.agents.anomaly_detection.parameters import Parameters
from verum.agents.anomaly_detection.residuals import (
    COMPUTED,
    NAMES,
    NOT_APPLICABLE,
    ResidualResult,
    exceeds,
)

UNKNOWN_STATE = "unknown"
WITHIN_NORMAL = "within_normal"
EXCEEDED = "exceeded"


def residual_id(key: str) -> str:
    """The contract identifier of a residual, such as R1_mass_balance."""
    return f"{key}_{NAMES[key]}"


def unknown_reason(result: ResidualResult) -> str:
    """Why a residual has no value, in words, from the reasons recorded when it was computed."""
    why = "; ".join(result.reasons) or "no value could be computed"
    return f"not applicable: {why}" if result.state == NOT_APPLICABLE else f"not computed: {why}"


def residual_entry(result: ResidualResult, own_threshold: float) -> dict[str, Any]:
    """State of one residual: exceeded, within normal, or unknown with a reason."""
    if result.state != COMPUTED:
        state, reason = UNKNOWN_STATE, unknown_reason(result)
    else:
        state, reason = (EXCEEDED if exceeds(result, own_threshold) else WITHIN_NORMAL), None
    return {"residual_id": residual_id(result.key), "state": state, "reason": reason}


def persistence_rule(params: Parameters) -> dict[str, Any]:
    """The k of n rule and the score threshold it applies to."""
    return {
        "k": params.persistence_k,
        "n": params.persistence_n,
        "threshold": params.persistence_threshold,
    }


def window_assessment(
    results: list[ResidualResult], score: float, complete: bool, params: Parameters
) -> dict[str, Any]:
    """The assessment of a window in which at least one residual was computed."""
    return {
        "score": score,
        "window_threshold": params.window_threshold,
        "exceeded": score > params.window_threshold,
        "complete": complete,
        "persistence_rule": persistence_rule(params),
        "residuals": [residual_entry(r, params.residual_thresholds[r.key]) for r in results],
    }
