"""Forecast five-minute sensor means with Ridge and persistence."""

from __future__ import annotations

import json
import math
from functools import cache
from pathlib import Path
from typing import Any

from verum.agents.common.envelope import (
    build_response,
    implementation_block,
    make_issue,
)
from verum.agents.common.validation import check_request, check_response

ROLE = "predictive_health"


@cache
def _ridge_artifact() -> dict[str, Any]:
    """Load the fitted Ridge coefficients bundled with the agent."""
    path = Path(__file__).with_name("ridge_models.json")
    artifact: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return artifact


def _predict(signal: dict[str, Any]) -> float | None:
    """Use Ridge for matching sensors and persistence for the others."""
    mean = signal["mean"]
    if mean is None:
        return None

    artifact = _ridge_artifact()
    model = artifact["models"].get(signal["tag_id"])
    if model is None or model["unit"] != signal["unit"]:
        return float(mean)

    contributions = [float(model["base"])]
    for name, weight, missing_offset in zip(
        artifact["features"],
        model["weights"],
        model["missing_offsets"],
        strict=True,
    ):
        value = signal.get(name)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        ):
            contributions.append(float(value) * float(weight))
        else:
            contributions.append(float(missing_offset))

    return math.fsum(contributions)


class PredictiveHealthAgent:
    """Return advisory forecasts for the requested instruments."""

    role = ROLE

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Validate the request and return a five-minute forecast report."""
        check_request(request)
        if request["agent"] != self.role:
            raise ValueError("request is addressed to a different role")

        payload = request["input"]
        observations = payload["observations"]
        evidence_ids = list(dict.fromkeys(observations["evidence_ids"]))
        limitations = [
            "Ridge forecasts use models fitted on simulated training data.",
            "Persistence assumes the next window mean equals the current window mean.",
            "The forecast does not establish equipment health or remaining useful life.",
        ]
        issues: list[dict[str, Any]] = []
        result: dict[str, Any] | None = None
        status = "insufficient_evidence"

        if observations["representation"] != "summary_v1":
            issues.append(
                make_issue(
                    "SUMMARY_REQUIRED",
                    "Forecasting requires summary_v1 observations.",
                )
            )
        else:
            signals = {
                signal["tag_id"]: signal
                for signal in observations["summary"]["signals"]
            }
            targets = payload["target_tag_ids"]
            missing = [tag for tag in targets if tag not in signals]

            if missing:
                issues.append(
                    make_issue(
                        "TARGET_SIGNAL_MISSING",
                        f"No signal summary or unit for: {', '.join(missing)}.",
                    )
                )
            elif not targets:
                issues.append(
                    make_issue("NO_FORECAST_TARGETS", "No instruments were requested.")
                )
            else:
                forecasts: list[dict[str, Any]] = []
                unavailable: list[str] = []
                for tag in targets:
                    signal = signals[tag]
                    value = _predict(signal)
                    if value is None:
                        unavailable.append(tag)

                    forecasts.append(
                        {
                            "tag_id": tag,
                            "unit": signal["unit"],
                            "quantity": "reported_mean",
                            "horizon_s": payload["forecast_horizon_s"],
                            "value": value,
                            "interval": None,
                            "evidence_ids": evidence_ids,
                            "limitations": [
                                "No current window mean is available."
                                if value is None
                                else "No prediction interval has been calibrated."
                            ],
                        }
                    )

                if unavailable:
                    issues.append(
                        make_issue(
                            "WINDOW_MEAN_UNAVAILABLE",
                            f"No current window mean for: {', '.join(unavailable)}.",
                        )
                    )

                status = "degraded" if unavailable else "complete"
                result = {
                    "forecasts": forecasts,
                    "health_score": None,
                    "remaining_useful_life": None,
                    "field_qualified": False,
                }

        response = build_response(
            request,
            status=status,
            result=result,
            consumed_evidence_ids=evidence_ids,
            implementation=implementation_block(
                "predictive_health_ridge_persistence", "1.0.0"
            ),
            issues=issues,
            limitations=limitations,
        )
        check_response(request, response)
        return response