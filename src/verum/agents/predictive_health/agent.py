"""Forecast five-minute sensor means with Ridge and persistence."""

from __future__ import annotations

import hashlib
import json
import math
from functools import cache
from pathlib import Path
from typing import Any, TypeGuard

from verum.agents.common.envelope import build_response, implementation_block, make_issue
from verum.agents.common.validation import check_request, check_response

ROLE = "predictive_health"
_LIMITATIONS = [
    "Ridge forecasts use models fitted on simulated training data.",
    "Persistence assumes the next window mean equals the current window mean.",
    "FT-201 was switched to persistence after reviewing the test results.",
    "The forecast does not establish equipment health or remaining useful life.",
]


def _finite(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@cache
def _ridge_artifact() -> tuple[dict[str, Any], str]:
    """Load coefficients and hash the exact artifact bytes used."""
    raw = Path(__file__).with_name("ridge_models.json").read_bytes()
    artifact: dict[str, Any] = json.loads(raw)
    features = artifact["features"]
    if artifact["horizon_s"] != 300 or not artifact["feature_profile_id"]:
        raise ValueError("Invalid Ridge artifact metadata")
    if not features or len(set(features)) != len(features):
        raise ValueError("Invalid Ridge feature list")
    for tag, model in artifact["models"].items():
        if not (len(features) == len(model["weights"]) == len(model["missing_offsets"])):
            raise ValueError(f"{tag}: Ridge coefficient length mismatch")
    return artifact, hashlib.sha256(raw).hexdigest()


def _ridge_value(signal: dict[str, Any], features: list[str], model: dict[str, Any]) -> float:
    """Apply the exported intercept, coefficients, and missing offsets."""
    contributions = [float(model["base"])]
    for name, weight, offset in zip(
        features, model["weights"], model["missing_offsets"], strict=True
    ):
        value = signal.get(name)
        contributions.append(float(value) * float(weight) if _finite(value) else float(offset))
    prediction = math.fsum(contributions)
    if not math.isfinite(prediction):
        raise ValueError("Nonfinite Ridge forecast")
    return prediction


def _predict(
    signal: dict[str, Any], artifact: dict[str, Any]
) -> tuple[float | None, str, str | None, str | None]:
    """Choose a method and explain any unavailable value or fallback."""
    mean = signal["mean"]
    if not _finite(mean):
        return None, "unavailable", "WINDOW_MEAN_UNAVAILABLE", "No current window mean."
    model = artifact["models"].get(signal["tag_id"])
    if model is None:
        return float(mean), "persistence", None, None
    if model["unit"] != signal["unit"]:
        return (
            float(mean),
            "persistence",
            "RIDGE_UNIT_MISMATCH",
            f"Expected {model['unit']}, got {signal['unit']}; used persistence.",
        )

    outside = []
    for name in artifact["features"]:
        bounds = model["training_ranges"][name]
        value = signal.get(name)
        if bounds is not None and _finite(value) and not bounds[0] <= value <= bounds[1]:
            outside.append(name)
    if outside:
        return (
            None,
            "unavailable",
            "RIDGE_INPUT_OUT_OF_RANGE",
            f"Outside the Ridge training range: {', '.join(outside)}.",
        )
    return _ridge_value(signal, artifact["features"], model), "ridge", None, None


def _collect_forecasts(
    payload: dict[str, Any], artifact: dict[str, Any], evidence_ids: list[str]
) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
    """Build forecast rows and retain issues for each affected instrument."""
    observations = payload["observations"]
    targets = payload["target_tag_ids"]
    if not targets:
        return (
            "insufficient_evidence",
            None,
            [make_issue("NO_FORECAST_TARGETS", "No instruments were requested.")],
        )
    if observations["representation"] != "summary_v1":
        return (
            "insufficient_evidence",
            None,
            [make_issue("SUMMARY_REQUIRED", "Forecasting requires summary_v1 observations.")],
        )
    signals = {signal["tag_id"]: signal for signal in observations["summary"]["signals"]}
    missing = [tag for tag in targets if tag not in signals]
    if missing:
        return (
            "insufficient_evidence",
            None,
            [
                make_issue(
                    "TARGET_SIGNAL_MISSING", f"No signal summary or unit for: {', '.join(missing)}."
                )
            ],
        )

    forecasts = []
    issues = []
    for tag in targets:
        signal = signals[tag]
        value, method, code, note = _predict(signal, artifact)
        limitations = [f"Forecast method: {method}."]
        if value is not None:
            limitations.append("No prediction interval has been calibrated.")
        if code is not None and note is not None:
            issues.append(make_issue(code, f"{tag}: {note}", evidence_ids))
            limitations.append(note)
        forecasts.append(
            {
                "tag_id": tag,
                "unit": signal["unit"],
                "quantity": "reported_mean",
                "horizon_s": payload["forecast_horizon_s"],
                "value": value,
                "interval": None,
                "evidence_ids": evidence_ids,
                "limitations": limitations,
            }
        )
    result = {
        "forecasts": forecasts,
        "health_score": None,
        "remaining_useful_life": None,
        "field_qualified": False,
    }
    return ("degraded" if issues else "complete"), result, issues


class PredictiveHealthAgent:
    """Return advisory forecasts for the requested instruments."""

    role = ROLE

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Validate the request and return forecasts or a structured error."""
        check_request(request)
        if request["agent"] != self.role:
            raise ValueError("request is addressed to a different role")

        payload = request["input"]
        evidence_ids = list(dict.fromkeys(payload["observations"]["evidence_ids"]))
        implementation = implementation_block("predictive_health_ridge_persistence", "1.0.0")
        try:
            artifact, digest = _ridge_artifact()
            implementation = implementation_block(
                "predictive_health_ridge_persistence",
                "1.0.0",
                artifact_sha256=digest,
                feature_profile_id=artifact["feature_profile_id"],
            )
            status, result, issues = _collect_forecasts(payload, artifact, evidence_ids)
        except Exception:
            status, result = "error", None
            issues = [
                make_issue(
                    "PREDICTIVE_HEALTH_FAILED",
                    "Could not load the Ridge artifact or compute the forecasts.",
                )
            ]

        response = build_response(
            request,
            status=status,
            result=result,
            consumed_evidence_ids=evidence_ids,
            implementation=implementation,
            issues=issues,
            limitations=list(_LIMITATIONS),
        )
        check_response(request, response)
        return response
