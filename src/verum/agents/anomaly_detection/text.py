"""Texts the topology residual detector puts into its reports.

The texts state what the detector reads and what it does not claim. The simulated-data scope,
the unverified tag-to-location mapping and the absence of any localisation or episode claim are
stated on every response in which the detector ran.
"""

from __future__ import annotations

from verum.agents.anomaly_detection.parameters import METHOD_ID, Parameters
from verum.agents.anomaly_detection.residuals import (
    COMPUTED,
    NOT_APPLICABLE,
    UNKNOWN,
    ResidualResult,
)

EVENT_TEXT = {
    "R1": (
        "Mass imbalance: the receipt flow minus the delivery flow differs from the change of "
        "tank inventory implied by the three level slopes. Candidate explanations include a "
        "leak, a flow-meter fault or a level-sensor fault; this residual does not separate them."
    ),
    "R2": (
        "Pump head residual: the pressure rise from the suction header to the running pump "
        "discharge, at the delivery flow, differs from its fault-free value. A loss of pump head "
        "is one candidate, as is a fault of an instrument it reads."
    ),
    "R3": (
        "Discharge loss residual: the pressure drop from the running pump discharge to the "
        "discharge header, at the delivery flow, differs from its fault-free value. A change in "
        "the discharge path is one candidate, as is a fault of an instrument it reads."
    ),
    "R4": (
        "Receipt line residual: the receipt line pressure, at the receipt flow, differs from its "
        "fault-free value. A change in the receipt line is one candidate, as is a fault of an "
        "instrument it reads."
    ),
}
NO_LOCATION = "Window-level evidence: no asset, location or fault type is identified."
MODEL_UNAVAILABLE_TEXT = (
    "The topology residual parameters could not be loaded or verified; only quality rules were "
    "applied."
)


def event_limitations(
    result: ResidualResult, own_threshold: float, score: float, params: Parameters
) -> list[str]:
    """Limitations of one residual event: its physics, its size and the window score."""
    verdict = "exceeded" if score > params.window_threshold else "not exceeded"
    return [
        EVENT_TEXT[result.key],
        NO_LOCATION,
        f"The residual is {result.z:.2f} fault-free scale units against its own threshold "
        f"{own_threshold:.2f}; the window score is {score:.2f} against the window threshold "
        f"{params.window_threshold:.2f} ({verdict}).",
    ]


def computability(results: list[ResidualResult]) -> str:
    """Which residuals were computed, unknown or not applicable, with the reasons."""
    parts = []
    labels = ((COMPUTED, "computed"), (UNKNOWN, "unknown"), (NOT_APPLICABLE, "not applicable"))
    for state, label in labels:
        keys = [r.key for r in results if r.state == state]
        if keys:
            parts.append(f"{label}: {', '.join(keys)}")
    grouped: dict[str, list[str]] = {}
    for r in results:
        if r.state != COMPUTED:
            grouped.setdefault("; ".join(r.reasons), []).append(r.key)
    reasons = [f"{', '.join(keys)}: {why}" for why, keys in grouped.items()]
    tail = f" ({'. '.join(reasons)})" if reasons else ""
    return "Residuals " + "; ".join(parts) + tail + "."


def window_line(score: float, params: Parameters) -> str:
    """The overall score and whether it exceeds the window threshold."""
    verdict = "exceeded" if score > params.window_threshold else "not exceeded"
    return (
        f"Window score {score:.2f} (the largest computed residual, in fault-free scale units) "
        f"against the window threshold {params.window_threshold:.2f}: {verdict}."
    )


def method_limitations(params: Parameters) -> list[str]:
    """Limitations stated on every response in which the detector ran."""
    return [
        f"Method {METHOD_ID}: four residuals from the declared single-line layout (mass balance "
        "with tank storage, pump head, discharge loss, receipt line), fitted on fault-free "
        "windows of the train split of one simulated terminal. It scores one 300 s summary "
        "window and keeps no state.",
        "Simulated data from one synthetic terminal; no field data. The score is a decision "
        "score, not a probability, and the residuals use the window mean and slope as given, "
        "including samples flagged suspect or bad.",
        "No asset, location or fault type is identified; events name only the tags a residual "
        "reads. The mass imbalance cannot separate a leak from a flow-meter or level-sensor "
        "fault.",
        "No episode-level claim is made: episode detection and delay need the scores of earlier "
        "windows, which a request does not carry.",
        "The tag-to-location mapping follows tag names; the declared reference gives no "
        "instrument locations and the pairing of pressure transmitters with pumps and headers "
        "is unverified.",
        "Fitted on the train split only; thresholds come from out-of-fold train scores; the "
        "validation split was used for reporting only and the test split was not used.",
    ]
