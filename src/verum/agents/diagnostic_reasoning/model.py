"""Learned multi-label observation classifier and heuristic fallback for Diagnostic Reasoning.

The model predicts supported fault mechanisms and candidate component locations from observation
summaries alone. Before loading a saved artifact from disk its SHA-256 digest is verified against
the compiled-in pinned hash; deterministic observation rules supplement or serve as a fallback.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import joblib  # type: ignore[import-untyped]
import numpy as np

from verum.agents.diagnostic_reasoning.features import extract_observation_vector, feature_names
from verum.agents.diagnostic_reasoning.rules import (
    KNOWN_ASSETS,
    KNOWN_TAGS,
    LOW_SUPPORT_MECHANISMS,
    SENSOR_MECHANISMS,
    SUPPORTED_MECHANISMS,
    valid_component,
)

MODEL_METHOD_ID: Final = "ovr_selected_classifier_v1"
LOW_SUPPORT_METHOD_SUFFIX: Final = "_low_support_uncalibrated"
FALLBACK_METHOD_ID: Final = "observation_residual_rule_v1_low_support_uncalibrated"
PINNED_ARTIFACT_SHA256: Final = "b165dc823fc9d2c040a133cf9d922e7f563a446d962f66e8ebff7b9175d45aee"

# Heuristic rule constants for deterministic stuck/drift checks on 300 s observation windows:
# - STUCK_MIN_SAMPLES (50): requires >= 50 samples in the 300 s window to avoid flagging sparse tags
# - STUCK_MIN_ACTIVE_MEAN (1.0): requires mean > 1.0 (m3/h or barg) so idle zero-flow is not flagged
# - STUCK_DECISION_SCORE (0.75): uncalibrated decision score above 0.50 rule threshold
# - DRIFT_IDLE_FLOW_MAX_M3H (5.0): max flow (m3/h) to consider the terminal in static storage mode
# - DRIFT_MIN_LEVEL_SLOPE_MS (0.0005): level slope > 0.5 mm/s during static mode indicates drift
# - DRIFT_DECISION_SCORE (0.70): uncalibrated decision score for static tank level drift
STUCK_MIN_SAMPLES: Final = 50
STUCK_MIN_ACTIVE_MEAN: Final = 1.0
STUCK_DECISION_SCORE: Final = 0.75
DRIFT_IDLE_FLOW_MAX_M3H: Final = 5.0
DRIFT_MIN_LEVEL_SLOPE_MS: Final = 0.0005
DRIFT_DECISION_SCORE: Final = 0.70


def default_artifact_path() -> Path:
    """Return the path of the saved model artifact inside the role package."""
    return Path(__file__).resolve().parent / "model_artifact.joblib"


def expected_artifact_sha256(artifact_path: Path | None = None) -> str:
    """Return the authoritative compiled-in SHA-256 digest for the saved model artifact."""
    return PINNED_ARTIFACT_SHA256


@dataclass
class CandidatePrediction:
    """One predicted diagnostic component with its method-specific decision score."""

    mechanism: str
    asset_id: str | None
    tag_id: str | None
    score: float
    method_id: str


def _method_for_mechanism(base_method: str, mechanism: str) -> str:
    if mechanism in LOW_SUPPORT_MECHANISMS and not base_method.endswith(LOW_SUPPORT_METHOD_SUFFIX):
        return f"{base_method}{LOW_SUPPORT_METHOD_SUFFIX}"
    return base_method


class DiagnosticModel:
    """Wrapper around a hash-verified multi-label artifact or deterministic observation rules."""

    def __init__(
        self, artifact_path: Path | None = None, expected_sha256: str | None = None
    ) -> None:
        self.path = artifact_path if artifact_path is not None else default_artifact_path()
        self.artifact: dict[str, Any] | None = None
        self.sha256: str | None = None
        if self.path.is_file():
            actual_sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
            pinned = (
                expected_sha256
                if expected_sha256 is not None
                else expected_artifact_sha256(self.path)
            )
            if actual_sha != pinned:
                raise ValueError(f"artifact sha256 mismatch: expected {pinned}, got {actual_sha}")
            loaded: dict[str, Any] = joblib.load(self.path)
            if loaded.get("feature_names") != feature_names():
                raise ValueError("saved artifact feature_names do not match extractor order")
            self.artifact = loaded
            self.sha256 = actual_sha

    def predict_candidates(self, observations: dict[str, Any]) -> list[CandidatePrediction]:
        """Produce ranked candidate components from an observation summary."""
        vec = extract_observation_vector(observations)
        heuristics = self._predict_heuristic(observations)
        if self.artifact is None:
            return heuristics
        learned = self._predict_from_artifact(vec)
        seen = {(c.mechanism, c.asset_id, c.tag_id) for c in learned}
        merged = list(learned)
        for h in heuristics:
            if (h.mechanism, h.asset_id, h.tag_id) not in seen:
                merged.append(h)
        merged.sort(key=lambda c: (-c.score, c.mechanism, c.asset_id or "", c.tag_id or ""))
        return merged

    def _predict_from_artifact(self, vec: np.ndarray) -> list[CandidatePrediction]:
        assert self.artifact is not None
        x_scaled = self.artifact["scaler"].transform(vec.reshape(1, -1))
        mech_models: dict[str, Any] = self.artifact["mechanism_models"]
        mech_thresholds: dict[str, float] = self.artifact["mechanism_thresholds"]
        comp_models: dict[str, Any] = self.artifact.get("component_models", {})
        comp_thresholds: dict[str, float] = self.artifact.get("component_thresholds", {})
        base_method: str = self.artifact.get("method_id", MODEL_METHOD_ID)

        candidates: list[CandidatePrediction] = []
        used_mechanisms: set[str] = set()

        for key, clf in sorted(comp_models.items()):
            mech, asset = key.split("::", 1)
            if mech not in SUPPORTED_MECHANISMS or asset not in KNOWN_ASSETS or clf is None:
                continue
            score = float(clf.predict_proba(x_scaled)[0, 1])
            if score >= float(comp_thresholds.get(key, 0.45)):
                tag = asset if (mech in SENSOR_MECHANISMS and asset in KNOWN_TAGS) else None
                m_id = _method_for_mechanism(base_method, mech)
                candidates.append(CandidatePrediction(mech, asset, tag, round(score, 6), m_id))
                used_mechanisms.add(mech)

        for mech in SUPPORTED_MECHANISMS:
            if mech in used_mechanisms or mech not in mech_models or mech_models[mech] is None:
                continue
            score = float(mech_models[mech].predict_proba(x_scaled)[0, 1])
            if score >= float(mech_thresholds.get(mech, 0.5)):
                m_id = _method_for_mechanism(base_method, mech)
                candidates.append(CandidatePrediction(mech, None, None, round(score, 6), m_id))

        candidates.sort(key=lambda c: (-c.score, c.mechanism, c.asset_id or ""))
        return candidates

    def _predict_heuristic(self, observations: dict[str, Any]) -> list[CandidatePrediction]:
        """Fallback observation rules when no trained model artifact is present."""
        summary = observations.get("summary", observations)
        signals = {s["tag_id"]: s for s in summary["signals"]}
        candidates: list[CandidatePrediction] = []

        for tag in ("FT-001", "FT-201", "PT-001", "PT-201", "PT-202A", "PT-202B", "PT-203"):
            sig = signals.get(tag, {})
            std, mean = sig.get("standard_deviation"), sig.get("mean")
            count = sig.get("measured_count", 0)
            if count >= STUCK_MIN_SAMPLES and std is not None and mean is not None:
                if float(std) == 0.0 and abs(float(mean)) > STUCK_MIN_ACTIVE_MEAN:
                    asset = tag if tag in KNOWN_ASSETS else None
                    candidates.append(
                        CandidatePrediction(
                            "stuck", asset, tag, STUCK_DECISION_SCORE, FALLBACK_METHOD_ID
                        )
                    )

        for tag in ("LT-101", "LT-102", "LT-103"):
            sig = signals.get(tag, {})
            slope = sig.get("slope_per_s")
            ft001 = signals.get("FT-001", {}).get("mean") or 0.0
            ft201 = signals.get("FT-201", {}).get("mean") or 0.0
            if (
                slope is not None
                and abs(float(ft001)) < DRIFT_IDLE_FLOW_MAX_M3H
                and abs(float(ft201)) < DRIFT_IDLE_FLOW_MAX_M3H
                and abs(float(slope)) > DRIFT_MIN_LEVEL_SLOPE_MS
            ):
                candidates.append(
                    CandidatePrediction(
                        "drift", None, tag, DRIFT_DECISION_SCORE, FALLBACK_METHOD_ID
                    )
                )

        candidates.sort(key=lambda c: (-c.score, c.mechanism, c.asset_id or "", c.tag_id or ""))
        return candidates


def format_hypotheses(predictions: list[CandidatePrediction]) -> list[dict[str, Any]]:
    """Convert candidate predictions into schema-compliant hypothesis dicts."""
    hypotheses: list[dict[str, Any]] = []
    for idx, pred in enumerate(predictions, start=1):
        comp = valid_component(pred.mechanism, pred.asset_id, pred.tag_id)
        target_label = comp["asset_id"] or comp["tag_id"] or "unlocalised"
        hyp_id = f"HYP-{idx:02d}-{comp['mechanism']}-{target_label}"
        hypotheses.append(
            {
                "hypothesis_id": hyp_id,
                "components": [comp],
                "score": {
                    "value": float(pred.score),
                    "kind": "decision_score",
                    "method_id": pred.method_id,
                    "calibration_id": None,
                },
                "support_evidence_ids": [],
                "conflict_evidence_ids": [],
                "unresolved_questions": [],
            }
        )
    return hypotheses
