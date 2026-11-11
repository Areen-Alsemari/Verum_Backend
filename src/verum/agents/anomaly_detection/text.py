"""Texts the topology residual detector puts into its reports, with the figures it quotes.

Every figure comes from the characterisation of the detector on simulated data (out-of-fold
grouped cross-validation on the train split and a separate validation split); a test compares
each one with the written reports. No figure here comes from the test split.
"""

from __future__ import annotations

from verum.agents.anomaly_detection.parameters import METHOD_ID, Parameters
from verum.agents.anomaly_detection.residuals import (
    COMPUTED,
    NOT_APPLICABLE,
    UNKNOWN,
    ResidualResult,
)

# AP, matched-stage AUROC and recall, each with its 95% interval over episodes.
FIGURES = {
    "oof_ap": "0.586 (0.533 to 0.638)",
    "oof_matched": "0.783 (0.749 to 0.819)",
    "val_ap": "0.730 (0.649 to 0.797)",
    "val_matched": "0.852 (0.801 to 0.896)",
    "oof_recall": "0.528 (0.473 to 0.586)",
    "val_recall": "0.663 (0.573 to 0.745)",
    "restriction": "0.367 (0.281 to 0.460) and 0.564 (0.407 to 0.710)",
    "leak": "0.363 (0.215 to 0.541) and 0.614 (0.368 to 0.881)",
    "bias": "0.204 (0.061 to 0.383) and 0.493 (0.256 to 0.760)",
    "misrouting": "0.222 (0.167 to 0.333) and 0.067 (0.000 to 0.167)",
    "pump": "1.000 and 1.000",
    "drift": "0.904 (0.827 to 0.965) and 0.540 (0.267 to 0.826)",
    "stuck": "0.747 (0.567 to 0.908) and 1.000",
    "multi": "0.718 (0.588 to 0.838) and 0.886 (0.694 to 1.000)",
    "threshold": "3.03",
    "val_far": "0.080",
    "val_recall_fixed": "0.740",
    "missing_ap": "0.456, 0.338 and 0.246",
    "missing_scorable": "0.966, 0.853 and 0.691",
    "noise_ap": "0.431, 0.367 and 0.336",
    "noise_far": "0.518, 0.723 and 0.830",
    "r1_instrument": "0.69 to 1.00",
    "area_match": "0.3%",
}

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
    f = FIGURES
    return [
        f"Method {METHOD_ID}: four residuals from the declared single-line layout (mass balance "
        "with tank storage, pump head, discharge loss, receipt line), fitted on fault-free "
        "windows of the train split of one simulated terminal. It scores one 300 s summary "
        "window and keeps no state.",
        f"Out of fold on train (grouped cross-validation) the score has average precision "
        f"{f['oof_ap']} and matched-stage AUROC {f['oof_matched']}; on a separate validation "
        f"split {f['val_ap']} and {f['val_matched']}. A score with no skill has average "
        "precision about 0.13.",
        f"At a threshold set for a 5% false-alarm rate in each set, recall is {f['oof_recall']} "
        f"out of fold and {f['val_recall']} on validation. By fault type, out of fold and on "
        f"validation: pump {f['pump']}; drift {f['drift']}; stuck {f['stuck']}; "
        f"multi-component {f['multi']}.",
        f"Weak: restriction {f['restriction']}; leak {f['leak']}; bias {f['bias']}; "
        f"misrouting {f['misrouting']} (few windows). Out of fold, fewer than half of the "
        "faults of these four types are flagged.",
        f"The window threshold {f['threshold']} is the 95th percentile of out-of-fold "
        "fault-free train scores, so the false-alarm rate is 0.05 by construction on train. "
        f"On validation it is {f['val_far']} with recall {f['val_recall_fixed']}: the threshold "
        "needs to be checked on the data the agent sees.",
        f"With 1, 2 or 3 of the 12 inputs missing at random, out-of-fold average precision "
        f"falls to {f['missing_ap']} and the share of windows that can still be scored is "
        f"{f['missing_scorable']}. With noise on the ten numeric inputs at 1x, 2x and 3x the "
        f"fault-free residual scale, it falls to {f['noise_ap']} and the false-alarm rate at "
        f"the fixed threshold rises to {f['noise_far']}.",
        "Simulated data from one synthetic terminal; no field data. The score is a decision "
        "score, not a probability, and the residuals use the window mean and slope as given, "
        "including samples flagged suspect or bad.",
        "No asset, location or fault type is identified; events name only the tags a residual "
        f"reads. The mass imbalance cannot separate a leak from a flow-meter or level-sensor "
        f"fault (it exceeds in {f['r1_instrument']} of such windows out of fold).",
        "No episode-level claim is made: episode detection and delay need the scores of earlier "
        "windows, which a request does not carry.",
        "The tag-to-location mapping follows tag names; the declared reference gives no "
        "instrument locations and the pairing of pressure transmitters with pumps and headers "
        f"is unverified. Fitted tank areas match the declared geometry within {f['area_match']}.",
        "Fitted on the train split only; thresholds come from out-of-fold train scores; the "
        "validation split was used for reporting only and the test split was not used.",
    ]
