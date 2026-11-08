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
OUTPUT_DIR = ROOT / "tools" / "agents" / "anomaly_detection_artifacts"

NUMERIC_FIELDS = (
    "bad_quality_samples",
    "latest_received_age_s",
    "latest_value",
    "maximum",
    "mean",
    "measured_count",
    "minimum",
    "missing_samples",
    "previous_measured_age_s",
    "previous_measured_value",
    "rows_received",
    "slope_per_s",
    "standard_deviation",
)


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
        return [
            value
            for value in signals.values()
            if isinstance(value, dict)
        ]

    if isinstance(signals, list):
        return [
            value
            for value in signals
            if isinstance(value, dict)
        ]

    return []


def extract_features(record: dict[str, Any]) -> dict[str, float]:
    """Create tag-independent numerical features from observation summaries."""
    signals = get_signals(record)
    features: dict[str, float] = {
        "signal_count": float(len(signals)),
    }

    for field in NUMERIC_FIELDS:
        values: list[float] = []

        for signal in signals:
            value = signal.get(field)

            if isinstance(value, bool):
                values.append(float(value))
            elif isinstance(value, (int, float)):
                numeric_value = float(value)
                if np.isfinite(numeric_value):
                    values.append(numeric_value)

        prefix = field

        features[f"{prefix}_present_fraction"] = (
            len(values) / len(signals) if signals else 0.0
        )

        if values:
            array = np.asarray(values, dtype=float)
            features[f"{prefix}_mean"] = float(np.mean(array))
            features[f"{prefix}_std"] = float(np.std(array))
            features[f"{prefix}_min"] = float(np.min(array))
            features[f"{prefix}_max"] = float(np.max(array))
        else:
            features[f"{prefix}_mean"] = 0.0
            features[f"{prefix}_std"] = 0.0
            features[f"{prefix}_min"] = 0.0
            features[f"{prefix}_max"] = 0.0

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
) -> tuple[list[dict[str, float]], np.ndarray]:
    """Prepare eligible feature rows and their physical labels."""
    features: list[dict[str, float]] = []
    labels: list[bool] = []

    for record in records:
        label = eligible_label(record)

        if label is None:
            continue

        features.append(extract_features(record))
        labels.append(label)

    return features, np.asarray(labels, dtype=int)


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


def select_threshold(
    labels: np.ndarray,
    scores: np.ndarray,
) -> float:
    """Select the threshold that maximizes validation F1."""
    precisions, recalls, thresholds = precision_recall_curve(labels, scores)

    if len(thresholds) == 0:
        return 0.5

    f1_values = (
        2 * precisions[:-1] * recalls[:-1]
        / np.maximum(precisions[:-1] + recalls[:-1], 1e-12)
    )

    return float(thresholds[int(np.argmax(f1_values))])


def main() -> None:
    """Train candidate models, select using validation, and evaluate test once."""
    print("Loading official dataset splits...")

    train_records = load_records("train")
    validation_records = load_records("validation")
    test_records = load_records("test")

    train_rows, y_train = prepare_split(train_records)
    validation_rows, y_validation = prepare_split(validation_records)
    test_rows, y_test = prepare_split(test_records)

    if len(np.unique(y_train)) < 2:
        raise ValueError("Training data must contain both physical classes.")

    if len(np.unique(y_validation)) < 2:
        raise ValueError("Validation data must contain both physical classes.")

    feature_names = sorted(
        {
            feature_name
            for row in train_rows
            for feature_name in row
        }
    )

    x_train = feature_matrix(train_rows, feature_names)
    x_validation = feature_matrix(validation_rows, feature_names)
    x_test = feature_matrix(test_rows, feature_names)

    print(f"Eligible training records: {len(y_train)}")
    print(f"Eligible validation records: {len(y_validation)}")
    print(f"Eligible test records: {len(y_test)}")
    print(f"Number of features: {len(feature_names)}")

    baseline_scores = np.zeros(len(y_validation), dtype=float)
    baseline_predictions = np.zeros(len(y_validation), dtype=int)

    results: dict[str, Any] = {
        "always_negative": classification_metrics(
            y_validation,
            baseline_predictions,
            baseline_scores,
        )
    }

    models: dict[str, Pipeline] = {
        "logistic_regression": Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        max_iter=2000,
                        class_weight="balanced",
                        random_state=42,
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
                        random_state=42,
                        n_jobs=-1,
                    ),
                ),
            ]
        ),
    }

    fitted_models: dict[str, Pipeline] = {}
    validation_scores: dict[str, np.ndarray] = {}

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

        print(
            f"{name}: validation average precision = "
            f"{results[name]['average_precision']:.4f}"
        )

    selected_name = max(
        fitted_models,
        key=lambda name: results[name]["average_precision"],
    )

    selected_model = fitted_models[selected_name]
    selected_validation_scores = validation_scores[selected_name]

    threshold = select_threshold(
        y_validation,
        selected_validation_scores,
    )

    validation_predictions = (
        selected_validation_scores >= threshold
    ).astype(int)

    validation_metrics = classification_metrics(
        y_validation,
        validation_predictions,
        selected_validation_scores,
    )

    print(f"\nSelected model: {selected_name}")
    print(f"Validation-selected threshold: {threshold:.6f}")

    print("\nEvaluating the selected model on the test split once...")

    test_scores = selected_model.predict_proba(x_test)[:, 1]
    test_predictions = (test_scores >= threshold).astype(int)

    test_metrics = classification_metrics(
        y_test,
        test_predictions,
        test_scores,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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

    joblib.dump(artifact, OUTPUT_DIR / "anomaly_detection_model.joblib")

    report = {
        "eligible_records": {
            "train": len(y_train),
            "validation": len(y_validation),
            "test": len(y_test),
        },
        "feature_count": len(feature_names),
        "validation_candidate_results": results,
        "selected_model": selected_name,
        "selected_threshold": threshold,
        "selected_validation_metrics": validation_metrics,
        "test_metrics": test_metrics,
        "limitations": [
            "The physical label represents an injected change in the reduced reference simulator.",
            "A model prediction is a reported signal departure, not proof of a real equipment fault.",
            "Overlapping windows from the same episode are not independent fault events.",
            "The test split was evaluated only after model and threshold selection.",
        ],
    }

    with (OUTPUT_DIR / "evaluation_report.json").open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(report, file, indent=2)

    print("\nTest results:")
    print(json.dumps(test_metrics, indent=2))
    print(f"\nSaved model and report to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()