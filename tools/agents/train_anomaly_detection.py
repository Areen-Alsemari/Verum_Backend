"""Train and validate the offline Anomaly Detection model.

Training uses the official training split and selects the model and
decision threshold using validation data only. Features are shared with
runtime inference and exclude timing and sample-count metadata.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import joblib  # type: ignore[import-untyped]
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from verum.agents.anomaly_detection.agent import (
    AGGREGATE_PROFILE_ID,
    ARTIFACT_PATH,
    FEATURE_EXTRACTORS,
    PER_TAG_PROFILE_ID,
    assess_inputs,
    features_for,
)

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = (
    ROOT
    / "data"
    / "reference_release_v2"
    / "verum_reference_v2"
    / "role_views"
    / "anomaly_detection"
)
REPORT_DIR = ROOT / "tools" / "agents" / "anomaly_detection_artifacts"
SEED = 20261108
MAX_EMPTY_SIGNAL_SHARE = 0.01
# Fixed before seeing any result: per-tag wins only if its validation F1 beats the
# aggregate profile by MIN_GAIN and the always-flag baseline by MIN_GAIN.
MIN_GAIN = 0.10
PROFILE_RULE = (
    f"per-tag is chosen only if its validation F1 is at least {MIN_GAIN:.2f} above both the "
    "aggregate profile and the always-flag baseline; otherwise the aggregate profile is kept"
)
PROFILE_CHOICES = {"aggregate": AGGREGATE_PROFILE_ID, "per_tag": PER_TAG_PROFILE_ID}


def load_records(split: str) -> list[dict[str, Any]]:
    """Load one official dataset split."""
    with gzip.open(DATA_DIR / f"{split}.jsonl.gz", "rt", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def get_signals(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Observation signals, whether stored directly or under "summary" as in runtime requests."""
    observations = record["input"]["observations"]
    signals = observations.get("signals")
    if signals is None and isinstance(observations.get("summary"), dict):
        signals = observations["summary"].get("signals")
    if isinstance(signals, dict):
        signals = list(signals.values())
    if not isinstance(signals, list):
        return []
    return [signal for signal in signals if isinstance(signal, dict)]


def eligible_label(record: dict[str, Any]) -> bool | None:
    """Return the physical label only when its supervision mask permits use."""
    supervision = record["target"]["reference_supervision"]
    if supervision.get("supervised_loss_mask") is not True:
        return None
    label = supervision.get("injected_change_present")
    return label if isinstance(label, bool) else None


def mechanism_name(record: dict[str, Any]) -> str:
    """Comma-joined injected mechanisms, or "none"."""
    components = record["target"]["reference_supervision"].get("injected_components") or []
    names = sorted({str(c.get("mechanism", "unknown")) for c in components if isinstance(c, dict)})
    return ", ".join(names) if names else "none"


class Split:
    """Eligible windows of one split, with features computed exactly as at runtime."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.rows: dict[str, list[dict[str, float]]] = {p: [] for p in FEATURE_EXTRACTORS}
        labels: list[int] = []
        self.mechanisms: list[str] = []
        self.runtime_gated = 0
        empty = 0
        for record in records:
            label = eligible_label(record)
            if label is None:
                continue
            signals = get_signals(record)
            empty += not signals
            if assess_inputs(signals).usable_fraction < 0.9:
                self.runtime_gated += 1
            for profile_id, rows in self.rows.items():
                rows.append(features_for(profile_id, signals))
            labels.append(int(label))
            self.mechanisms.append(mechanism_name(record))
        self.y = np.asarray(labels, dtype=int)
        if len(self.y) and empty / len(self.y) > MAX_EMPTY_SIGNAL_SHARE:
            raise ValueError(f"{empty} of {len(self.y)} windows have no signals: check get_signals")

    def names(self, profile_id: str) -> list[str]:
        """Feature names of one profile, sorted."""
        return sorted({name for row in self.rows[profile_id] for name in row})

    def matrix(self, profile_id: str, names: list[str]) -> np.ndarray:
        """Feature matrix in a fixed column order; missing values stay NaN."""
        rows = self.rows[profile_id]
        return np.asarray([[row.get(n, np.nan) for n in names] for row in rows], dtype=float)


def metrics(labels: np.ndarray, predictions: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    """Window-level metrics for one split."""
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    return {
        "positive_count": int(np.sum(labels == 1)),
        "negative_count": int(np.sum(labels == 0)),
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
        "f1": float(f1_score(labels, predictions, zero_division=0)),
        "average_precision": float(average_precision_score(labels, scores)),
        "confusion_matrix": {
            "true_negative": int(tn),
            "false_positive": int(fp),
            "false_negative": int(fn),
            "true_positive": int(tp),
        },
    }


def baselines(labels: np.ndarray) -> dict[str, Any]:
    """Always-negative and always-flag reference results."""
    zeros, ones = np.zeros(len(labels), dtype=int), np.ones(len(labels), dtype=int)
    return {
        "always_negative": metrics(labels, zeros, zeros.astype(float)),
        "always_flag": metrics(labels, ones, ones.astype(float)),
    }


def mechanism_metrics(
    labels: np.ndarray, predictions: np.ndarray, mechanisms: list[str]
) -> dict[str, Any]:
    """Count detections for each injected mechanism, plus false alarms on clean windows."""
    results: dict[str, Any] = {}
    names = sorted({m for value in mechanisms if value != "none" for m in value.split(", ")})
    for name in names:
        index = np.asarray(
            [i for i, v in enumerate(mechanisms) if name in v.split(", ")], dtype=int
        )
        positives = index[labels[index] == 1]
        results[name] = {
            "window_count": int(len(index)),
            "positive_count": int(len(positives)),
            "detected": int(np.sum(predictions[positives] == 1)),
            "recall": float(np.mean(predictions[positives] == 1)) if len(positives) else None,
        }
    clean = np.asarray([i for i, v in enumerate(mechanisms) if v == "none"], dtype=int)
    results["no_injected_mechanism"] = {
        "window_count": int(len(clean)),
        "false_alarms": int(np.sum(predictions[clean] == 1)),
    }
    return results


def select_threshold(labels: np.ndarray, scores: np.ndarray) -> float:
    """Threshold that maximizes validation F1; a window is flagged when score >= threshold."""
    precisions, recalls, thresholds = precision_recall_curve(labels, scores)
    if len(thresholds) == 0:
        return 0.5
    f1 = 2 * precisions[:-1] * recalls[:-1] / np.maximum(precisions[:-1] + recalls[:-1], 1e-12)
    return float(thresholds[int(np.argmax(f1))])


def candidate_models() -> dict[str, Pipeline]:
    """Learned candidates; both see identical features."""
    return {
        "logistic_regression": Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEED),
                ),
            ]
        ),
        "random_forest": Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "classifier",
                    RandomForestClassifier(
                        n_estimators=300,
                        min_samples_leaf=3,
                        class_weight="balanced",
                        random_state=SEED,
                        n_jobs=-1,
                    ),
                ),
            ]
        ),
    }


def positive_scores(model: Pipeline, x: np.ndarray) -> np.ndarray:
    """Score of the positive class."""
    index = list(model.classes_).index(1)
    return np.asarray(model.predict_proba(x)[:, index], dtype=float)


def fit_and_select(train: Split, validation: Split, profile_id: str) -> dict[str, Any]:
    """Fit every candidate on train; select model by validation AP, then the threshold."""
    names = train.names(profile_id)
    x_train, x_val = train.matrix(profile_id, names), validation.matrix(profile_id, names)
    print(f"\n{profile_id}: {len(names)} features")
    candidates: dict[str, Any] = {}
    fitted: dict[str, Pipeline] = {}
    for name, model in candidate_models().items():
        model.fit(x_train, train.y)
        fitted[name] = model
        scores = positive_scores(model, x_val)
        threshold = select_threshold(validation.y, scores)
        candidates[name] = {
            "threshold": threshold,
            "validation": metrics(validation.y, (scores >= threshold).astype(int), scores),
        }
        result = candidates[name]["validation"]
        print(f"  {name}: validation AP {result['average_precision']:.4f}, F1 {result['f1']:.4f}")
    best = max(candidates, key=lambda n: candidates[n]["validation"]["average_precision"])
    return {
        "profile_id": profile_id,
        "feature_names": names,
        "name": best,
        "model": fitted[best],
        "threshold": candidates[best]["threshold"],
        "validation_f1": candidates[best]["validation"]["f1"],
        "candidates": candidates,
    }


def choose_profile(results: dict[str, dict[str, Any]], always_flag_f1: float) -> str:
    """Apply PROFILE_RULE to the validation results."""
    aggregate = results[AGGREGATE_PROFILE_ID]["validation_f1"]
    per_tag = results[PER_TAG_PROFILE_ID]["validation_f1"]
    if per_tag >= aggregate + MIN_GAIN and per_tag >= always_flag_f1 + MIN_GAIN:
        return PER_TAG_PROFILE_ID
    return AGGREGATE_PROFILE_ID


def feature_ranges(split: Split, selection: dict[str, Any]) -> dict[str, list[float]]:
    """Per-feature training minimum and maximum (ignoring NaN), for the runtime range check."""
    names = selection["feature_names"]
    x = split.matrix(selection["profile_id"], names)
    ranges: dict[str, list[float]] = {}
    for i, name in enumerate(names):
        column = x[:, i][~np.isnan(x[:, i])]
        if len(column):
            ranges[name] = [float(column.min()), float(column.max())]
    return ranges


def save_artifact(selection: dict[str, Any], ranges: dict[str, list[float]]) -> str:
    """Write the artifact and return its sha256."""
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "model": selection["model"],
        "model_name": selection["name"],
        "feature_profile_id": selection["profile_id"],
        "threshold": selection["threshold"],
        "feature_names": selection["feature_names"],
        "feature_ranges": ranges,
        "label_description": (
            "Injected change present in the reduced reference simulator; "
            "not a verified real-world equipment fault."
        ),
    }
    joblib.dump(artifact, ARTIFACT_PATH)
    return hashlib.sha256(ARTIFACT_PATH.read_bytes()).hexdigest()


def write_json(path: Path, content: dict[str, Any]) -> None:
    """Write JSON with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")


def guard_test_split(force: bool) -> None:
    """Stop before any work if the test split was already used."""
    if (REPORT_DIR / "test_report.json").exists() and not force:
        raise SystemExit(
            "test_report.json exists: the test split is used once (pass --force to override)"
        )


def final_test(selection: dict[str, Any], digest: str) -> None:
    """Evaluate the frozen model on the test split once, with both baselines."""
    path = REPORT_DIR / "test_report.json"
    test = Split(load_records("test"))
    names = selection["feature_names"]
    scores = positive_scores(selection["model"], test.matrix(selection["profile_id"], names))
    predictions = (scores >= selection["threshold"]).astype(int)
    report = {
        "artifact_sha256": digest,
        "feature_profile_id": selection["profile_id"],
        "selected_model": selection["name"],
        "threshold": selection["threshold"],
        "selected": metrics(test.y, predictions, scores),
        "baselines": baselines(test.y),
        "per_mechanism": mechanism_metrics(test.y, predictions, test.mechanisms),
        "windows_the_runtime_would_not_assess": test.runtime_gated,
    }
    write_json(path, report)
    print(
        f"\nTest F1 {report['selected']['f1']:.3f}; always-flag F1 "
        f"{report['baselines']['always_flag']['f1']:.3f}. Copy both into TEST_F1 and "
        "ALWAYS_FLAG_TEST_F1 in agent.py."
    )


def train_profiles(train: Split, validation: Split, forced: str | None) -> dict[str, Any]:
    """Train each profile, apply the profile rule, and return every result plus the winner."""
    profiles = [forced] if forced else list(FEATURE_EXTRACTORS)
    results = {profile_id: fit_and_select(train, validation, profile_id) for profile_id in profiles}
    always_flag_f1 = baselines(validation.y)["always_flag"]["f1"]
    chosen = forced or choose_profile(results, always_flag_f1)
    print(f"\nValidation always-flag F1 {always_flag_f1:.4f}")
    for profile_id, result in results.items():
        print(f"  {profile_id}: {result['name']} F1 {result['validation_f1']:.4f}")
    print(f"Rule: {PROFILE_RULE}." if not forced else "Profile forced by --profile.")
    print(f"Chosen profile: {chosen}")
    return {"results": results, "chosen": chosen}


def evaluation_report(
    train: Split, validation: Split, outcome: dict[str, Any], digest: str
) -> dict[str, Any]:
    """Validation-only report; it holds no per-window labels or predictions."""
    selection = outcome["results"][outcome["chosen"]]
    return {
        "seed": SEED,
        "eligible_records": {"train": len(train.y), "validation": len(validation.y)},
        "profile_rule": PROFILE_RULE,
        "chosen_profile": outcome["chosen"],
        "validation_baselines": baselines(validation.y),
        "profiles": {
            profile_id: {
                "feature_names": result["feature_names"],
                "selected_model": result["name"],
                "candidates": result["candidates"],
            }
            for profile_id, result in outcome["results"].items()
        },
        "selected_model": selection["name"],
        "selected_threshold": selection["threshold"],
        "artifact_sha256": digest,
        "limitations": [
            "Features are physical values only; no timing, count or on/off state fields.",
            "The label is an injected change in a reduced reference simulator.",
            "Overlapping windows from one episode are not independent fault events.",
        ],
    }


def main() -> None:
    """Train both profiles, choose on validation, save the artifact, optionally test once."""
    parser = argparse.ArgumentParser(description="Train the Anomaly Detection model.")
    parser.add_argument("--final-test", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--profile", choices=sorted(PROFILE_CHOICES))
    args = parser.parse_args()
    if args.final_test:
        guard_test_split(args.force)

    train, validation = Split(load_records("train")), Split(load_records("validation"))
    for name, split in (("train", train), ("validation", validation)):
        if len(np.unique(split.y)) < 2:
            raise ValueError(f"{name} data must contain both physical classes")
    print(f"Eligible records: train {len(train.y)}, validation {len(validation.y)}")

    outcome = train_profiles(train, validation, PROFILE_CHOICES.get(args.profile or ""))
    selection = outcome["results"][outcome["chosen"]]
    digest = save_artifact(selection, feature_ranges(train, selection))
    write_json(
        REPORT_DIR / "evaluation_report.json",
        evaluation_report(train, validation, outcome, digest),
    )
    print(f"\nSelected {selection['name']}, threshold {selection['threshold']:.6f}")
    print(f'Set EXPECTED_ARTIFACT_SHA256 = "{digest}" in agent.py')
    print(f'Set MODEL_METHOD_ID = "{selection["name"]}_v1" in agent.py')
    if args.final_test:
        final_test(selection, digest)


if __name__ == "__main__":
    main()
