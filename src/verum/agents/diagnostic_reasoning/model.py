"""Learned multi-label observation classifier and heuristic fallback for Diagnostic Reasoning.

The model predicts supported fault mechanisms and candidate component locations from observation
summaries alone. When a trained artifact is present on disk it is loaded and hashed; otherwise a
deterministic observation heuristic provides candidate hypotheses without failing runtime calls.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import joblib  # type: ignore[import-untyped]
import numpy as np

from verum.agents.diagnostic_reasoning.features import (
    extract_observation_vector,
)
from verum.agents.diagnostic_reasoning.rules import (
    KNOWN_ASSETS,
    KNOWN_TAGS,
    SENSOR_MECHANISMS,
    SUPPORTED_MECHANISMS,
    valid_component,
)

MODEL_METHOD_ID: Final = "ovr_hist_gradient_boosting_v1"
FALLBACK_METHOD_ID: Final = "observation_residual_rule_v1"


def default_artifact_path() -> Path:
    """Return the path of the saved model artifact inside the role package."""
    return Path(__file__).resolve().parent / "model_artifact.joblib"


def artifact_sha256(path: Path | None = None) -> str | None:
    """Return the SHA-256 hex digest of the saved model artifact if it exists."""
    target = path if path is not None else default_artifact_path()
    if not target.is_file():
        return None
    return hashlib.sha256(target.read_bytes()).hexdigest()


@dataclass
class CandidatePrediction:
    """One predicted diagnostic component with its method-specific decision score."""

    mechanism: str
    asset_id: str | None
    tag_id: str | None
    score: float
    method_id: str


class DiagnosticModel:
    """Wrapper around a trained multi-label artifact or deterministic observation rules."""

    def __init__(self, artifact_path: Path | None = None) -> None:
        self.path = artifact_path if artifact_path is not None else default_artifact_path()
        self.artifact: dict[str, Any] | None = None
        self.sha256: str | None = None
        if self.path.is_file():
            self.artifact = joblib.load(self.path)
            self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()

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
        scaler = self.artifact["scaler"]
        x_scaled = scaler.transform(vec.reshape(1, -1))
        mech_models: dict[str, Any] = self.artifact["mechanism_models"]
        mech_thresholds: dict[str, float] = self.artifact["mechanism_thresholds"]
        comp_models: dict[str, Any] = self.artifact.get("component_models", {})
        comp_thresholds: dict[str, float] = self.artifact.get("component_thresholds", {})
        method_id: str = self.artifact.get("method_id", MODEL_METHOD_ID)

        candidates: list[CandidatePrediction] = []
        used_mechanisms: set[str] = set()

        # First evaluate specific (mechanism, asset_id) component models if trained
        for key, clf in sorted(comp_models.items()):
            mech, asset = key.split("::", 1)
            if mech not in SUPPORTED_MECHANISMS or asset not in KNOWN_ASSETS:
                continue
            prob = float(clf.predict_proba(x_scaled)[0, 1])
            thresh = float(comp_thresholds.get(key, 0.45))
            if prob >= thresh:
                tag = asset if (mech in SENSOR_MECHANISMS and asset in KNOWN_TAGS) else None
                candidates.append(
                    CandidatePrediction(mech, asset, tag, round(prob, 6), method_id)
                )
                used_mechanisms.add(mech)

        # Next evaluate mechanism-level models for any active mechanism without a specific asset
        for mech in SUPPORTED_MECHANISMS:
            if mech in used_mechanisms or mech not in mech_models:
                continue
            clf = mech_models[mech]
            if clf is None:
                continue
            prob = float(clf.predict_proba(x_scaled)[0, 1])
            thresh = float(mech_thresholds.get(mech, 0.5))
            if prob >= thresh:
                candidates.append(
                    CandidatePrediction(mech, None, None, round(prob, 6), method_id)
                )

        candidates.sort(key=lambda c: (-c.score, c.mechanism, c.asset_id or ""))
        return candidates

    def _predict_heuristic(self, observations: dict[str, Any]) -> list[CandidatePrediction]:
        """Fallback observation rules when no trained model artifact is present."""
        signals = {s["tag_id"]: s for s in observations["summary"]["signals"]}
        candidates: list[CandidatePrediction] = []

        # Check stuck sensor (zero standard deviation with sufficient samples on continuous tags)
        for tag in ("FT-001", "FT-201", "PT-001", "PT-201", "PT-202A", "PT-202B", "PT-203"):
            sig = signals.get(tag, {})
            std = sig.get("standard_deviation")
            mean = sig.get("mean")
            count = sig.get("measured_count", 0)
            if count >= 50 and std is not None and mean is not None:
                if float(std) == 0.0 and abs(float(mean)) > 1.0:
                    asset = tag if tag in KNOWN_ASSETS else None
                    candidates.append(
                        CandidatePrediction("stuck", asset, tag, 0.75, FALLBACK_METHOD_ID)
                    )

        # Check steep level or pressure drift
        for tag in ("LT-101", "LT-102", "LT-103"):
            sig = signals.get(tag, {})
            slope = sig.get("slope_per_s")
            ft001 = signals.get("FT-001", {}).get("mean") or 0.0
            ft201 = signals.get("FT-201", {}).get("mean") or 0.0
            if slope is not None and abs(float(ft001)) < 5.0 and abs(float(ft201)) < 5.0:
                if abs(float(slope)) > 0.0005:
                    candidates.append(
                        CandidatePrediction("drift", None, tag, 0.70, FALLBACK_METHOD_ID)
                    )

        candidates.sort(key=lambda c: (-c.score, c.mechanism, c.asset_id or "", c.tag_id or ""))
        return candidates


def format_hypotheses(
    predictions: list[CandidatePrediction],
) -> list[dict[str, Any]]:
    """Convert candidate predictions into schema-compliant hypothesis dicts."""
    hypotheses: list[dict[str, Any]] = []
    for idx, pred in enumerate(predictions, start=1):
        comp = valid_component(pred.mechanism, pred.asset_id, pred.tag_id)
        target_label = comp["asset_id"] or comp["tag_id"] or "unlocalised"
        hyp_id = f"HYP-{idx:02d}-{comp['mechanism']}-{target_label}"
        hypotheses.append({
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
        })
    return hypotheses
