"""Runtime implementation of the Anomaly Detection role."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import joblib  # type: ignore[import-untyped]
import numpy as np

from verum.agents.common import (
    attached_report_ids,
    build_response,
    check_request,
    check_response,
    file_sha256,
    implementation_block,
    make_issue,
)

ROLE = "anomaly_detection"
VERSION = "1.0.0"
FEATURE_PROFILE_ID = "anomaly_detection_summary_v1_66"
QUALITY_METHOD_ID = "quality_summary_rules_v1"
MODEL_METHOD_ID = "logistic_regression_v1"

NUMERIC_FIELDS = (
    "latest_value",
    "previous_measured_value",
    "minimum",
    "maximum",
    "mean",
    "slope_per_s",
    "standard_deviation",
)
EXPECTED_UNITS = {
    "FT-001": "m3/h",
    "FT-201": "m3/h",
    "LSHH-101": "bool",
    "LSHH-102": "bool",
    "LSHH-103": "bool",
    "LT-101": "m",
    "LT-102": "m",
    "LT-103": "m",
    "P-101A": "bool",
    "P-101B": "bool",
    "PT-001": "barg",
    "PT-201": "barg",
    "PT-202A": "barg",
    "PT-202B": "barg",
    "PT-203": "barg",
    "TT-001": "C",
    "TT-101": "C",
    "TT-102": "C",
    "TT-103": "C",
    "XV-PAI": "bool",
    "XV-PAO": "bool",
    "XV-PBI": "bool",
    "XV-PBO": "bool",
    "XV-R000": "bool",
    "XV-R101": "bool",
    "XV-R102": "bool",
    "XV-R103": "bool",
    "XV-S101": "bool",
    "XV-S102": "bool",
    "XV-S103": "bool",
}

ARTIFACT_PATH = (
    Path(__file__).resolve().parents[4]
    / "tools"
    / "agents"
    / "anomaly_detection_artifacts"
    / "anomaly_detection_model.joblib"
)

EXPECTED_ARTIFACT_SHA256 = "56a63c52c4781908e0e87a801449f12756508e8c20f385ff654362fc825465ea"


@cache
def load_artifact() -> dict[str, Any]:
    """Load the verified anomaly detection artifact."""
    actual_hash = file_sha256(ARTIFACT_PATH)

    if actual_hash != EXPECTED_ARTIFACT_SHA256:
        raise ValueError("anomaly detection artifact hash mismatch")

    artifact = joblib.load(ARTIFACT_PATH)

    if not isinstance(artifact, dict):
        raise ValueError("invalid anomaly detection artifact")

    return artifact


def find_invalid_unit_signals(
    signals: list[dict[str, Any]],
) -> list[str]:
    """Identify signals with unknown tags or unexpected units."""
    invalid_tags = []

    for signal in signals:
        tag_id = signal["tag_id"]
        expected_unit = EXPECTED_UNITS.get(tag_id)

        if expected_unit is None or signal["unit"] != expected_unit:
            invalid_tags.append(tag_id)

    return sorted(set(invalid_tags))


def filter_valid_unit_signals(
    signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep signals with recognized tags and expected units."""
    return [signal for signal in signals if EXPECTED_UNITS.get(signal["tag_id"]) == signal["unit"]]


def extract_features(signals: list[dict[str, Any]]) -> dict[str, float]:
    """Extract the physical measurement features used during training."""
    features: dict[str, float] = {}

    for field in NUMERIC_FIELDS:
        values = [
            float(signal[field])
            for signal in signals
            if isinstance(signal.get(field), (int, float))
            and not isinstance(signal.get(field), bool)
            and np.isfinite(signal[field])
        ]

        if values:
            array = np.asarray(values, dtype=float)
            features[f"{field}_mean"] = float(np.mean(array))
            features[f"{field}_std"] = float(np.std(array))
            features[f"{field}_min"] = float(np.min(array))
            features[f"{field}_max"] = float(np.max(array))
        else:
            features[f"{field}_mean"] = 0.0
            features[f"{field}_std"] = 0.0
            features[f"{field}_min"] = 0.0
            features[f"{field}_max"] = 0.0

    return features


class InsufficientMeasurementsError(Exception):
    """Raised when a window has no usable physical measurements."""


def has_physical_measurements(signals: list[dict[str, Any]]) -> bool:
    """Check whether any finite physical measurement is available."""
    return any(
        isinstance(signal.get(field), (int, float))
        and not isinstance(signal.get(field), bool)
        and np.isfinite(signal[field])
        for signal in signals
        for field in NUMERIC_FIELDS
    )


def make_event(
    *,
    event_id: str,
    category: str,
    tag_ids: list[str],
    evidence_ids: list[str],
    method_id: str,
    limitations: list[str],
    score: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an event that follows the shared anomaly event contract."""
    return {
        "event_id": event_id,
        "tag_ids": tag_ids,
        "asset_ids": [],
        "category": category,
        "score": score,
        "method_id": method_id,
        "evidence_ids": evidence_ids,
        "limitations": limitations,
    }


class AnomalyDetectionAgent:
    """Detect reported data-quality issues and aggregate signal departures."""

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Validate a request, analyze its observations, and validate the response."""
        check_request(request)

        if request["agent"] != ROLE:
            raise ValueError("request is addressed to a different role")

        observations = request["input"]["observations"]
        summary = observations["summary"]
        signals = summary["signals"]

        known_evidence = {row["evidence_id"] for row in request["evidence"]}
        evidence_ids = list(
            dict.fromkeys(
                [
                    *[
                        evidence_id
                        for evidence_id in observations["evidence_ids"]
                        if evidence_id in known_evidence
                    ],
                    *attached_report_ids(request),
                ]
            )
        )

        events: list[dict[str, Any]] = []

        missing_tags = [
            signal["tag_id"]
            for signal in signals
            if signal["missing_samples"] > 0 or signal["latest_availability"] == "missing_sample"
        ]

        quality_tags = [
            signal["tag_id"]
            for signal in signals
            if signal["bad_quality_samples"] > 0 or signal["latest_quality"] in ("suspect", "bad")
        ]

        if missing_tags:
            events.append(
                make_event(
                    event_id=f"{request['request_id']}-missing-reading",
                    category="missing_reading",
                    tag_ids=missing_tags,
                    evidence_ids=evidence_ids,
                    method_id=QUALITY_METHOD_ID,
                    limitations=[
                        "Identifies reported missing readings only.",
                        "Does not establish equipment health.",
                    ],
                )
            )

        if quality_tags:
            events.append(
                make_event(
                    event_id=f"{request['request_id']}-non-good-quality",
                    category="non_good_quality",
                    tag_ids=quality_tags,
                    evidence_ids=evidence_ids,
                    method_id=QUALITY_METHOD_ID,
                    limitations=[
                        "Identifies reported signal quality conditions only.",
                        "Does not establish equipment health.",
                    ],
                )
            )

        artifact_hash: str | None = None
        issues: list[dict[str, Any]] = []
        status = "complete"
        insufficient_measurements = False

        invalid_unit_tags = find_invalid_unit_signals(signals)
        valid_signals = filter_valid_unit_signals(signals)

        if invalid_unit_tags:
            status = "degraded"
            issues.append(
                make_issue(
                    "INVALID_SIGNAL_UNIT",
                    "Signals with unknown tags or unexpected units were"
                    " excluded from model inference.",
                    evidence_ids,
                )
            )

        try:
            if not has_physical_measurements(valid_signals):
                raise InsufficientMeasurementsError("insufficient physical measurements")

            artifact = load_artifact()
            artifact_hash = file_sha256(ARTIFACT_PATH)

            feature_values = extract_features(valid_signals)
            feature_names = artifact["feature_names"]
            threshold = float(artifact["threshold"])
            model = artifact["model"]

            vector = np.asarray(
                [[feature_values[name] for name in feature_names]],
                dtype=float,
            )

            probabilities = model.predict_proba(vector)[0]
            positive_index = list(model.classes_).index(True)
            decision_score = float(probabilities[positive_index])

            if decision_score >= threshold:
                events.append(
                    make_event(
                        event_id=f"{request['request_id']}-signal-departure",
                        category="reported_signal_departure",
                        tag_ids=[],
                        evidence_ids=evidence_ids,
                        method_id=MODEL_METHOD_ID,
                        score={
                            "value": decision_score,
                            "kind": "decision_score",
                            "method_id": MODEL_METHOD_ID,
                            "calibration_id": None,
                        },
                        limitations=[
                            "Trained using injected changes in a reduced reference simulator.",
                            "A detected departure is not proof of a real equipment fault.",
                            "Aggregate features do not identify a specific tag or asset.",
                            "Overlapping observation windows are not independent fault events.",
                        ],
                    )
                )

        except InsufficientMeasurementsError:
            status = "degraded"
            insufficient_measurements = True
            issues.append(
                make_issue(
                    "INSUFFICIENT_EVIDENCE",
                    "No usable physical measurements were available for model inference.",
                    evidence_ids,
                )
            )

        except Exception:
            status = "degraded"
            issues.append(
                make_issue(
                    "MODEL_UNAVAILABLE",
                    "The anomaly model could not be loaded or evaluated; "
                    "only quality rules were applied.",
                    evidence_ids,
                )
            )

        if not evidence_ids or insufficient_measurements:
            coverage = "unknown"
        elif status == "degraded":
            coverage = "partial"
        else:
            coverage = "assessed"

        result = {
            "events": events,
            "coverage": coverage,
            "no_event_means_healthy": False,
        }

        response = build_response(
            request,
            status=status,
            result=result,
            consumed_evidence_ids=evidence_ids,
            implementation=implementation_block(
                "anomaly_detection",
                VERSION,
                artifact_sha256=artifact_hash,
                feature_profile_id=FEATURE_PROFILE_ID,
            ),
            issues=issues,
            limitations=[
                "Forecast reports are not used as model features.",
                *(
                    [
                        "The anomaly model could not be loaded or evaluated; "
                        "only quality rules were applied."
                    ]
                    if any(issue["code"] == "MODEL_UNAVAILABLE" for issue in issues)
                    else []
                ),
                "No detected event does not establish healthy equipment.",
            ],
        )

        check_response(request, response)
        return response
