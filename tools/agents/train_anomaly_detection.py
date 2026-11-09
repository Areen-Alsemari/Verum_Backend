"""Train and evaluate the offline Anomaly Detection model."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    precision_recall_curve,
    precision_score,
    recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = (
    ROOT
    / "data"
    / "reference_release_v2"
    / "verum_reference_v2"
    / "role_views"
    / "anomaly_detection"
)
MODEL_DIR = ROOT / "src" / "verum" / "agents" / "anomaly_detection" / "artifacts"

REPORT_DIR = ROOT / "tools" / "agents" / "anomaly_detection_artifacts"

NUMERIC_FIELDS = (
    "latest_value",
    "previous_measured_value",
    "minimum",
    "maximum",
    "mean",
    "slope_per_s",
    "standard_deviation",
)
SEED = 20261108


def load_records(split: str) -> list[dict[str, Any]]:
    """Load one official dataset split."""
    path = DATA_DIR / f"{split}.jsonl.gz"

    records: list[dict[str, Any]] = []

    with gzip.open(path, "rt", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                records.append(json.loads(line))

    return records


def get_signals(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the observation signals as a list of dictionaries."""
    observations = record["input"]["observations"]
    signals = observations.get("signals", [])

    if isinstance(signals, dict):
        return [value for value in signals.values() if isinstance(value, dict)]

    if isinstance(signals, list):
        return [value for value in signals if isinstance(value, dict)]

    return []


def extract_features(record: dict[str, Any]) -> dict[str, float]:
    """Extract aggregate physical measurement features."""
    signals = get_signals(record)
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


def eligible_label(record: dict[str, Any]) -> bool | None:
    """Return the physical label only when its supervision mask permits use."""
    supervision = record["target"]["reference_supervision"]

    if supervision.get("supervised_loss_mask") is not True:
        return None

    label = supervision.get("injected_change_present")

    if isinstance(label, bool):
        return label

    return None


def prepare_split(
    records: list[dict[str, Any]],
) -> tuple[
    list[dict[str, float]],
    np.ndarray,
    list[str],
    list[str],
]:
    """Prepare eligible features, labels, episode IDs, and mechanisms."""
    features: list[dict[str, float]] = []
    labels: list[bool] = []
    sample_ids: list[str] = []
    mechanisms: list[str] = []

    for record in records:
        label = eligible_label(record)

        if label is None:
            continue

        supervision = record["target"]["reference_supervision"]

        features.append(extract_features(record))
        labels.append(label)
        sample_ids.append(str(record.get("example_id", "unknown")))

        components = supervision.get("injected_components", [])
        mechanism_names = sorted(
            {
                str(component.get("mechanism", "unknown"))
                for component in components
                if isinstance(component, dict)
            }
        )

        mechanisms.append(", ".join(mechanism_names) if mechanism_names else "none")

    return (
        features,
        np.asarray(labels, dtype=int),
        sample_ids,
        mechanisms,
    )


def feature_matrix(
    rows: list[dict[str, float]],
    feature_names: list[str],
) -> np.ndarray:
    """Build a matrix with a consistent feature order."""
    return np.asarray(
        [[row.get(name, 0.0) for name in feature_names] for row in rows],
        dtype=float,
    )


def classification_metrics(
    labels: np.ndarray,
    predictions: np.ndarray,
    scores: np.ndarray,
) -> dict[str, Any]:
    """Calculate classification metrics for one evaluation split."""
    tn, fp, fn, tp = confusion_matrix(
        labels,
        predictions,
        labels=[0, 1],
    ).ravel()

    return {
        "positive_count": int(np.sum(labels == 1)),
        "negative_count": int(np.sum(labels == 0)),
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
        "average_precision": float(average_precision_score(labels, scores)),
        "confusion_matrix": {
            "true_negative": int(tn),
            "false_positive": int(fp),
            "false_negative": int(fn),
            "true_positive": int(tp),
        },
        "false_alarms": int(fp),
        "misses": int(fn),
    }


def mechanism_metrics(
    labels: np.ndarray,
    predictions: np.ndarray,
    mechanisms: list[str],
) -> dict[str, Any]:
    """Calculate detection results for each individual injected mechanism."""
    results: dict[str, Any] = {}

    individual_mechanisms = sorted(
        {mechanism for value in mechanisms if value != "none" for mechanism in value.split(", ")}
    )

    for mechanism in individual_mechanisms:
        indices = np.asarray(
            [index for index, value in enumerate(mechanisms) if mechanism in value.split(", ")],
            dtype=int,
        )

        mechanism_labels = labels[indices]
        mechanism_predictions = predictions[indices]

        tn, fp, fn, tp = confusion_matrix(
            mechanism_labels,
            mechanism_predictions,
            labels=[0, 1],
        ).ravel()

        results[mechanism] = {
            "sample_count": int(len(indices)),
            "positive_count": int(np.sum(mechanism_labels == 1)),
            "negative_count": int(np.sum(mechanism_labels == 0)),
            "false_alarms": int(fp),
            "misses": int(fn),
            "true_positives": int(tp),
            "true_negatives": int(tn),
            "recall": float(
                recall_score(
                    mechanism_labels,
                    mechanism_predictions,
                    zero_division=0,
                )
            ),
        }

    negative_indices = np.asarray(
        [index for index, value in enumerate(mechanisms) if value == "none"],
        dtype=int,
    )

    results["no_injected_mechanism"] = {
        "sample_count": int(len(negative_indices)),
        "false_alarms": int(np.sum(predictions[negative_indices] == 1)),
        "true_negatives": int(np.sum(predictions[negative_indices] == 0)),
    }

    return results


def select_threshold(
    labels: np.ndarray,
    scores: np.ndarray,
) -> float:
    """Select the threshold that maximizes validation F1."""
    precisions, recalls, thresholds = precision_recall_curve(labels, scores)

    if len(thresholds) == 0:
        return 0.5

    f1_values = (
        2 * precisions[:-1] * recalls[:-1] / np.maximum(precisions[:-1] + recalls[:-1], 1e-12)
    )

    return float(thresholds[int(np.argmax(f1_values))])


def build_candidate_models() -> dict[str, Pipeline]:
    return {
        "logistic_regression": Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        max_iter=2000,
                        class_weight="balanced",
                        random_state=SEED,
                    ),
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


def train_candidate_models(
    models: dict[str, Pipeline],
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_validation: np.ndarray,
    y_validation: np.ndarray,
) -> tuple[dict[str, Pipeline], dict[str, np.ndarray], dict[str, Any]]:
    fitted_models: dict[str, Pipeline] = {}
    validation_scores: dict[str, np.ndarray] = {}

    results: dict[str, Any] = {
        "always_negative": classification_metrics(
            y_validation,
            np.zeros(len(y_validation), dtype=int),
            np.zeros(len(y_validation), dtype=float),
        )
    }

    print("\nTraining candidate models...")

    for name, model in models.items():
        model.fit(x_train, y_train)
        scores = model.predict_proba(x_validation)[:, 1]

        fitted_models[name] = model
        validation_scores[name] = scores

        predictions = (scores >= 0.5).astype(int)
        results[name] = classification_metrics(
            y_validation,
            predictions,
            scores,
        )

        print(f"{name}: validation average precision = {results[name]['average_precision']:.4f}")

    return fitted_models, validation_scores, results


def select_best_model(
    fitted_models: dict[str, Pipeline],
    validation_scores: dict[str, np.ndarray],
    results: dict[str, Any],
    y_validation: np.ndarray,
) -> tuple[str, Pipeline, float, dict[str, Any]]:
    selected_name = max(
        fitted_models,
        key=lambda name: results[name]["average_precision"],
    )

    selected_model = fitted_models[selected_name]
    selected_scores = validation_scores[selected_name]

    threshold = select_threshold(y_validation, selected_scores)
    predictions = (selected_scores >= threshold).astype(int)

    validation_metrics = classification_metrics(
        y_validation,
        predictions,
        selected_scores,
    )

    return selected_name, selected_model, threshold, validation_metrics


def save_training_outputs(
    selected_model: Pipeline,
    selected_name: str,
    threshold: float,
    feature_names: list[str],
    y_train: np.ndarray,
    y_validation: np.ndarray,
    results: dict[str, Any],
    validation_metrics: dict[str, Any],
) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    artifact = {
        "model": selected_model,
        "model_name": selected_name,
        "threshold": threshold,
        "feature_names": feature_names,
        "label_description": (
            "Injected change present in the reduced reference simulator; "
            "not a verified real-world equipment fault."
        ),
    }

    report = {
        "eligible_records": {
            "train": len(y_train),
            "validation": len(y_validation),
        },
        "feature_count": len(feature_names),
        "feature_names": feature_names,
        "seed": SEED,
        "validation_candidate_results": results,
        "selected_model": selected_name,
        "selected_threshold": threshold,
        "selected_validation_metrics": validation_metrics,
        "limitations": [
            "The physical label represents an injected change in the reduced reference simulator.",
            "A model prediction is a reported signal departure, "
            "not proof of a real equipment fault.",
            "Overlapping windows from the same episode are not independent fault events.",
            "No test-split evaluation is performed during model development.",
        ],
    }

    joblib.dump(
        artifact,
        MODEL_DIR / "anomaly_detection_model.joblib",
    )

    with (REPORT_DIR / "evaluation_report.json").open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(report, file, indent=2)


def main() -> None:
    """Train candidate models and select using validation data."""
    print("Loading official dataset splits...")

    train_records = load_records("train")
    validation_records = load_records("validation")

    train_rows, y_train, _, _ = prepare_split(train_records)
    validation_rows, y_validation, _, _ = prepare_split(validation_records)

    if len(np.unique(y_train)) < 2:
        raise ValueError("Training data must contain both physical classes.")

    if len(np.unique(y_validation)) < 2:
        raise ValueError("Validation data must contain both physical classes.")

    feature_names = sorted({feature_name for row in train_rows for feature_name in row})

    x_train = feature_matrix(train_rows, feature_names)
    x_validation = feature_matrix(validation_rows, feature_names)

    print(f"Eligible training records: {len(y_train)}")
    print(f"Eligible validation records: {len(y_validation)}")
    print(f"Number of features: {len(feature_names)}")

    models = build_candidate_models()

    fitted_models, validation_scores, results = train_candidate_models(
        models,
        x_train,
        y_train,
        x_validation,
        y_validation,
    )

    selected_name = max(
        fitted_models,
        key=lambda name: results[name]["average_precision"],
    )

    selected_name, selected_model, threshold, validation_metrics = select_best_model(
        fitted_models,
        validation_scores,
        results,
        y_validation,
    )

    print(f"\nSelected model: {selected_name}")
    print(f"Validation-selected threshold: {threshold:.6f}")

    save_training_outputs(
        selected_model,
        selected_name,
        threshold,
        feature_names,
        y_train,
        y_validation,
        results,
        validation_metrics,
    )

    print("\nValidation results:")
    print(json.dumps(validation_metrics, indent=2))
    print(f"\nSaved model to: {MODEL_DIR}")
    print(f"Saved evaluation report to: {REPORT_DIR}")


if __name__ == "__main__":
    main()
