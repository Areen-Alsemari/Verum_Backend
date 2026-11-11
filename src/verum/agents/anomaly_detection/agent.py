"""Runtime implementation of the Anomaly Detection role.

The agent combines deterministic signal-quality checks with a learned
detector using physical measurement features. It reports window-level
signal departures and preserves evidence provenance.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
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
AGGREGATE_PROFILE_ID = "anomaly_detection_physical_v1_28"
PER_TAG_PROFILE_ID = "anomaly_detection_physical_per_tag_measured_v1"
# Profile reported when no artifact was loaded, and assumed for artifacts that name none.
FEATURE_PROFILE_ID = AGGREGATE_PROFILE_ID
QUALITY_METHOD_ID = "quality_summary_rules_v1"
MODEL_METHOD_ID = "random_forest_v1"

NUMERIC_FIELDS = (
    "latest_value",
    "previous_measured_value",
    "minimum",
    "maximum",
    "mean",
    "slope_per_s",
    "standard_deviation",
)
# A tag counts as observed in this window only if one of these holds a value.
# previous_measured_value is left out on purpose: it can hold an old reading.
CURRENT_VALUE_FIELDS = ("latest_value", "mean", "minimum", "maximum")
BOOL_UNIT = "bool"
NON_GOOD_QUALITY = ("suspect", "bad")

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

# A window with many tags missing is not comparable with the training windows.
# Below this share of usable tags the detector is not applied.
MIN_USABLE_TAG_FRACTION = 0.9
# A feature further than this many training spans outside its training range is far
# out of range, and the detector is not applied to that window.
RANGE_MARGIN_SPANS = 1.0

ARTIFACT_PATH = Path(__file__).resolve().parent / "artifacts" / "anomaly_detection_model.joblib"


EXPECTED_ARTIFACT_SHA256 = "7edefb2121fb23f04339c8a7791de3552f14ec5d953d7e23548075ac7ef4f531"


VALIDATION_F1 = 0.241
ALWAYS_FLAG_VALIDATION_F1 = 0.222
TEST_F1 = 0.352
ALWAYS_FLAG_TEST_F1 = 0.302
TEST_FLAGGED_FRACTION = 0.81
STAGE_MATCHED_TEST_AUROC = 0.51

SKILL_SUMMARY = (
    f"Validation F1 {VALIDATION_F1:.3f} and test F1 {TEST_F1:.3f}, against "
    f"{ALWAYS_FLAG_VALIDATION_F1:.3f} and {ALWAYS_FLAG_TEST_F1:.3f} for flagging every "
    f"window; it flags about {TEST_FLAGGED_FRACTION:.0%} of test windows, its AUROC "
    f"among windows at the same episode stage is about {STAGE_MATCHED_TEST_AUROC:.2f} "
    "(chance), and it scores perfectly on its training windows (overfit)."
)

PROFILE_DESCRIPTIONS = {
    AGGREGATE_PROFILE_ID: (
        "The detector uses only physical-value features averaged across all tags (latest, "
        "previous, minimum, maximum, mean, slope and spread); it does not use "
        "reading-arrival timing or sample counts."
    ),
    PER_TAG_PROFILE_ID: (
        "The detector uses only physical-value features of each measured tag (flows, "
        "pressures, levels and temperatures: latest, previous, minimum, maximum, mean, "
        "slope and spread); it does not use reading-arrival timing, sample counts, or the "
        "on/off states of pumps, valves and alarms, which mark the operating mode rather "
        "than a physical change."
    ),
}


def detector_limitations(profile_id: str = FEATURE_PROFILE_ID) -> tuple[str, ...]:
    """Limitations stated on every response and event in which the detector ran."""
    return (
        PROFILE_DESCRIPTIONS[profile_id],
        SKILL_SUMMARY,
        "An earlier version scored higher only because a reading-arrival timing field "
        "marked injected changes in the simulator; that field is not a physical "
        "measurement and is no longer used.",
        "The score is an uncalibrated decision score, not a probability.",
        "A departure means the whole window differs from simulated normal windows; it "
        "does not identify a tag, an asset or a physical fault.",
        "Trained on injected changes in a reduced reference simulator; overlapping "
        "windows from one episode are not independent events.",
    )


DETECTOR_LIMITATIONS = detector_limitations()
MODEL_UNAVAILABLE_TEXT = (
    "The anomaly model could not be loaded or evaluated; only quality rules were applied."
)


@cache
def load_artifact() -> dict[str, Any]:
    """Load the anomaly detection artifact, verifying its hash before deserializing it."""
    actual_hash = file_sha256(ARTIFACT_PATH)

    if actual_hash != EXPECTED_ARTIFACT_SHA256:
        raise ValueError("anomaly detection artifact hash mismatch")

    artifact = joblib.load(ARTIFACT_PATH)

    if not isinstance(artifact, dict):
        raise ValueError("invalid anomaly detection artifact")

    return artifact


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool) and bool(np.isfinite(value))
    )


def _count(value: Any) -> float:
    return float(value) if _is_number(value) else 0.0


def _tag(signal: dict[str, Any]) -> str:
    return str(signal.get("tag_id"))


def find_invalid_unit_signals(signals: list[dict[str, Any]]) -> list[str]:
    """Identify signals with unknown tags or unexpected units."""
    return sorted(
        {
            _tag(signal)
            for signal in signals
            if EXPECTED_UNITS.get(_tag(signal)) != signal.get("unit")
        }
    )


def filter_valid_unit_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep signals with recognized tags and expected units."""
    return [signal for signal in signals if EXPECTED_UNITS.get(_tag(signal)) == signal.get("unit")]


def has_current_value(signal: dict[str, Any]) -> bool:
    """Whether the signal carries a reading from this window (a boolean counts for bool tags)."""
    is_bool_tag = signal.get("unit") == BOOL_UNIT
    return any(
        _is_number(signal.get(name)) or (is_bool_tag and isinstance(signal.get(name), bool))
        for name in CURRENT_VALUE_FIELDS
    )


def extract_features(signals: list[dict[str, Any]]) -> dict[str, float]:
    """Extract the physical measurement features used during training."""
    features: dict[str, float] = {}

    for name in NUMERIC_FIELDS:
        values = [float(signal[name]) for signal in signals if _is_number(signal.get(name))]

        if values:
            array = np.asarray(values, dtype=float)
            features[f"{name}_mean"] = float(np.mean(array))
            features[f"{name}_std"] = float(np.std(array))
            features[f"{name}_min"] = float(np.min(array))
            features[f"{name}_max"] = float(np.max(array))
        else:
            features[f"{name}_mean"] = 0.0
            features[f"{name}_std"] = 0.0
            features[f"{name}_min"] = 0.0
            features[f"{name}_max"] = 0.0

    return features


MEASURED_TAGS = tuple(sorted(tag for tag, unit in EXPECTED_UNITS.items() if unit != BOOL_UNIT))


def _per_tag_value(signal: dict[str, Any], name: str) -> float:
    value = signal.get(name)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return math.nan


def extract_per_tag_features(signals: list[dict[str, Any]]) -> dict[str, float]:
    """One feature per measured tag and field; on/off tags are left out.

    Pump, valve and alarm states are excluded because they mark the operating mode: a
    model trained with them learned which mode the simulator was in when changes were
    injected, not the physical change. A missing value stays NaN for the model's
    imputer and is never encoded as its own feature, so missingness cannot become a
    signal.
    """
    by_tag: dict[str, dict[str, Any]] = {}
    for signal in signals:
        by_tag.setdefault(_tag(signal), signal)
    features: dict[str, float] = {}
    for tag in MEASURED_TAGS:
        signal = by_tag.get(tag, {})
        for name in NUMERIC_FIELDS:
            features[f"{tag}__{name}"] = _per_tag_value(signal, name)
    return features


FEATURE_EXTRACTORS: dict[str, Callable[[list[dict[str, Any]]], dict[str, float]]] = {
    AGGREGATE_PROFILE_ID: extract_features,
    PER_TAG_PROFILE_ID: extract_per_tag_features,
}


def features_for(profile_id: str, signals: list[dict[str, Any]]) -> dict[str, float]:
    """Features of one profile, computed from the valid-unit signals only."""
    return FEATURE_EXTRACTORS[profile_id](filter_valid_unit_signals(signals))


@dataclass(frozen=True)
class InputAssessment:
    """Which expected tags arrived with a valid unit and a value from this window."""

    invalid_unit_tags: list[str]
    usable_tags: list[str]
    unusable_tags: list[str]

    @property
    def usable_fraction(self) -> float:
        """Share of expected tags that are usable."""
        return len(self.usable_tags) / len(EXPECTED_UNITS)


def assess_inputs(signals: list[dict[str, Any]]) -> InputAssessment:
    """Classify the expected tags as usable or not for the detector."""
    usable = sorted(
        {_tag(signal) for signal in filter_valid_unit_signals(signals) if has_current_value(signal)}
    )
    return InputAssessment(
        invalid_unit_tags=find_invalid_unit_signals(signals),
        usable_tags=usable,
        unusable_tags=sorted(set(EXPECTED_UNITS) - set(usable)),
    )


def out_of_range_features(features: dict[str, float], ranges: Any) -> list[str]:
    """Features far outside their training range; empty when the artifact holds no ranges."""
    if not isinstance(ranges, dict):
        return []
    far: list[str] = []
    for name, bounds in ranges.items():
        value = features.get(name)
        if value is None or math.isnan(value) or not isinstance(bounds, (list, tuple)):
            continue
        if len(bounds) != 2:
            continue
        low, high = float(bounds[0]), float(bounds[1])
        margin = RANGE_MARGIN_SPANS * max(high - low, 1e-9)
        if value < low - margin or value > high + margin:
            far.append(name)
    return sorted(far)


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
        "tag_ids": sorted(set(tag_ids)),
        "asset_ids": [],
        "category": category,
        "score": score,
        "method_id": method_id,
        "evidence_ids": evidence_ids,
        "limitations": limitations,
    }


def build_quality_events(
    request_id: str,
    signals: list[dict[str, Any]],
    evidence_ids: list[str],
) -> list[dict[str, Any]]:
    """Rule events for missing readings and suspect or bad quality flags."""
    events: list[dict[str, Any]] = []

    missing_tags = [
        _tag(signal)
        for signal in signals
        if _count(signal.get("missing_samples")) > 0
        or signal.get("latest_availability") == "missing_sample"
        or not has_current_value(signal)
    ]
    quality_tags = [
        _tag(signal)
        for signal in signals
        if _count(signal.get("bad_quality_samples")) > 0
        or signal.get("latest_quality") in NON_GOOD_QUALITY
    ]

    if missing_tags:
        events.append(
            make_event(
                event_id=f"{request_id}-missing-reading",
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
                event_id=f"{request_id}-non-good-quality",
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

    return events


def decision_score(model: Any, features: dict[str, float], feature_names: list[str]) -> float:
    """Score of the positive class, with features in the order stored in the artifact."""
    vector = np.asarray([[features[name] for name in feature_names]], dtype=float)
    probabilities = model.predict_proba(vector)[0]
    positive_index = list(model.classes_).index(True)
    return float(probabilities[positive_index])


@dataclass
class DetectorOutcome:
    """What the learned detector contributed to one response."""

    applied: bool = False
    event: dict[str, Any] | None = None
    artifact_sha256: str | None = None
    feature_profile_id: str = FEATURE_PROFILE_ID
    issues: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def _insufficient(message: str, evidence_ids: list[str]) -> DetectorOutcome:
    return DetectorOutcome(issues=[make_issue("INSUFFICIENT_EVIDENCE", message, evidence_ids)])


def _unavailable(evidence_ids: list[str]) -> DetectorOutcome:
    return DetectorOutcome(
        issues=[make_issue("MODEL_UNAVAILABLE", MODEL_UNAVAILABLE_TEXT, evidence_ids)],
        limitations=[MODEL_UNAVAILABLE_TEXT],
    )


def coverage_gate(assessment: InputAssessment, evidence_ids: list[str]) -> DetectorOutcome | None:
    """Return a not-applied outcome when too few tags are usable, else None."""
    if not assessment.usable_tags:
        return _insufficient(
            "No usable physical measurements were available for model inference.", evidence_ids
        )
    if assessment.usable_fraction < MIN_USABLE_TAG_FRACTION:
        return _insufficient(
            f"Only {len(assessment.usable_tags)} of {len(EXPECTED_UNITS)} expected tags had "
            "usable values; the window is not comparable with training windows, so the "
            "detector was not applied.",
            evidence_ids,
        )
    return None


def run_detector(
    request_id: str,
    signals: list[dict[str, Any]],
    assessment: InputAssessment,
    evidence_ids: list[str],
) -> DetectorOutcome:
    """Apply the learned detector only when the window is comparable with training data."""
    total = len(EXPECTED_UNITS)
    gate = coverage_gate(assessment, evidence_ids)
    if gate is not None:
        return gate

    try:
        artifact = load_artifact()
        model = artifact["model"]
        feature_names = list(artifact["feature_names"])
        threshold = float(artifact["threshold"])
        profile_id = str(artifact.get("feature_profile_id", FEATURE_PROFILE_ID))
        features = features_for(profile_id, signals)
        far = out_of_range_features(features, artifact.get("feature_ranges"))
        score = None if far else decision_score(model, features, feature_names)
    except Exception:  # noqa: BLE001 - any load or evaluation failure is a named issue
        return _unavailable(evidence_ids)

    outcome = DetectorOutcome(
        artifact_sha256=EXPECTED_ARTIFACT_SHA256, feature_profile_id=profile_id
    )
    if "feature_ranges" not in artifact:
        outcome.limitations.append(
            "The artifact holds no training ranges; no range check was made."
        )
    if score is None:
        outcome.issues.append(
            make_issue(
                "INSUFFICIENT_EVIDENCE",
                f"{len(far)} features lie far outside the training range, so the detector "
                "was not applied; the window may hold a large change or bad data.",
                evidence_ids,
            )
        )
        return outcome

    outcome.applied = True
    outcome.limitations.extend(detector_limitations(profile_id))
    if assessment.unusable_tags:
        outcome.issues.append(
            make_issue(
                "INSUFFICIENT_EVIDENCE",
                f"{len(assessment.unusable_tags)} of {total} expected tags had no usable value; "
                "the detector ran on the remaining tags.",
                evidence_ids,
            )
        )
    if score >= threshold:
        outcome.event = departure_event(request_id, score, evidence_ids, profile_id)
    return outcome


def departure_event(
    request_id: str, score: float, evidence_ids: list[str], profile_id: str
) -> dict[str, Any]:
    """Build the window-level departure event; its limitations state the detector's real skill."""
    return make_event(
        event_id=f"{request_id}-signal-departure",
        category="reported_signal_departure",
        tag_ids=[],
        evidence_ids=evidence_ids,
        method_id=MODEL_METHOD_ID,
        score={
            "value": score,
            "kind": "decision_score",
            "method_id": MODEL_METHOD_ID,
            "calibration_id": None,
        },
        limitations=list(detector_limitations(profile_id)),
    )


def status_and_coverage(
    observation_ids: list[str],
    assessment: InputAssessment,
    outcome: DetectorOutcome,
) -> tuple[str, str]:
    """Only a fully observed window that the detector assessed is complete and assessed."""
    if not observation_ids or not assessment.usable_tags:
        return "degraded", "unknown"
    if not outcome.applied or assessment.unusable_tags or assessment.invalid_unit_tags:
        return "degraded", "partial"
    return "complete", "assessed"


def observation_evidence_ids(request: dict[str, Any]) -> list[str]:
    """Observation evidence ids that the request's evidence list also contains."""
    known = {row["evidence_id"] for row in request["evidence"]}
    listed = request["input"]["observations"]["evidence_ids"]
    return list(dict.fromkeys(evidence_id for evidence_id in listed if evidence_id in known))


def safe_consumed_ids(request: Any) -> list[str]:
    """Consumed evidence for an error response, never raising, always keeping attached reports."""
    try:
        observed = observation_evidence_ids(request)
    except Exception:  # noqa: BLE001 - the error path must not fail
        observed = []
    try:
        attached = list(attached_report_ids(request))
    except Exception:  # noqa: BLE001 - fall back to the forecast report id if it is in evidence
        attached = []
        try:
            report = request["input"].get("forecast_report")
            known = {row["evidence_id"] for row in request["evidence"]}
            if isinstance(report, dict) and report.get("report_id") in known:
                attached = [report["report_id"]]
        except Exception:  # noqa: BLE001
            attached = []
    return list(dict.fromkeys([*observed, *attached]))


def response_limitations(outcome: DetectorOutcome) -> list[str]:
    """Response-level limitations; model-specific text appears only when it applies."""
    return [
        "Forecast reports are not used as model features.",
        *outcome.limitations,
        "No detected event does not establish healthy equipment.",
    ]


class AnomalyDetectionAgent:
    """Detect reported data-quality issues and window-level signal departures."""

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Validate a request, analyze its observations, and validate the response.

        Any failure, including an invalid request, returns a status="error" response.
        """
        try:
            check_request(request)
        except Exception as exc:  # noqa: BLE001
            return self.error_response(
                request, f"The request failed contract validation ({type(exc).__name__})."
            )
        try:
            return self._analyze(request)
        except Exception as exc:  # noqa: BLE001
            return self.error_response(
                request,
                f"An unexpected internal error ({type(exc).__name__}) prevented anomaly analysis.",
            )

    def _analyze(self, request: dict[str, Any]) -> dict[str, Any]:
        if request["agent"] != ROLE:
            raise ValueError("request is addressed to a different role")

        raw_signals = request["input"]["observations"]["summary"]["signals"]
        if not isinstance(raw_signals, list):
            raise ValueError("observation signals must be a list")
        signals = [signal for signal in raw_signals if isinstance(signal, dict)]

        observation_ids = observation_evidence_ids(request)
        consumed = list(dict.fromkeys([*observation_ids, *attached_report_ids(request)]))
        assessment = assess_inputs(signals)

        events = build_quality_events(request["request_id"], signals, observation_ids)
        issues: list[dict[str, Any]] = []
        if assessment.invalid_unit_tags:
            issues.append(
                make_issue(
                    "INVALID_SIGNAL_UNIT",
                    "Signals with unknown tags or unexpected units were excluded from model "
                    "inference.",
                    observation_ids,
                )
            )

        outcome = run_detector(request["request_id"], signals, assessment, observation_ids)
        if outcome.event is not None:
            events.append(outcome.event)
        issues.extend(outcome.issues)
        status, coverage = status_and_coverage(observation_ids, assessment, outcome)

        response = build_response(
            request,
            status=status,
            result={"events": events, "coverage": coverage, "no_event_means_healthy": False},
            consumed_evidence_ids=consumed,
            implementation=implementation_block(
                ROLE,
                VERSION,
                artifact_sha256=outcome.artifact_sha256,
                feature_profile_id=outcome.feature_profile_id,
            ),
            issues=issues,
            limitations=response_limitations(outcome),
        )
        check_response(request, response)
        return dict(response)

    def error_response(self, request: dict[str, Any], message: str) -> dict[str, Any]:
        """Build a result-less response that still lists the attached report ids as consumed.

        It is validated when the request itself is valid. For an invalid request no
        response can pass validation, so it is returned as built.
        """
        consumed = safe_consumed_ids(request)
        response = build_response(
            request,
            status="error",
            result=None,
            consumed_evidence_ids=consumed,
            implementation=implementation_block(
                ROLE, VERSION, feature_profile_id=FEATURE_PROFILE_ID
            ),
            issues=[make_issue("INTERNAL_ERROR", message, consumed)],
            limitations=[
                "The anomaly analysis could not be completed; no conclusion about the "
                "equipment can be drawn."
            ],
        )
        try:
            check_response(request, response)
        except Exception:  # noqa: BLE001 - an invalid request cannot yield a valid response
            pass
        return dict(response)
