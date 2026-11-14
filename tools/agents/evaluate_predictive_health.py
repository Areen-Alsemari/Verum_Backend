"""Compare five-minute sensor forecasts and evaluate the frozen model choices."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from verum.agents.common.loader import iter_role_records

ROLE = "predictive_health"
HORIZON_S = 300
EVALUATION_SEED = 20261108
FEATURE_PROFILE_ID = "predictive-health-summary-v1"

# Originally selected on validation; FT-201 was removed after reviewing test.
RIDGE_TAGS = frozenset(
    {
        "LT-101",
        "LT-102",
        "LT-103",
        "PT-201",
        "PT-202A",
        "PT-202B",
        "PT-203",
    }
)

FEATURES = (
    "mean",
    "latest_value",
    "previous_measured_value",
    "minimum",
    "maximum",
    "standard_deviation",
    "slope_per_s",
    "measured_count",
    "missing_samples",
    "bad_quality_samples",
    "latest_received_age_s",
    "previous_measured_age_s",
)

Sensor = tuple[str, str]
Row = tuple[list[float], float]


def _number(value: Any) -> float:
    """Convert a finite numeric value or return NaN for a missing feature."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(value):
            return float(value)
    return math.nan


def _load_split(
    root: Path,
    split: str,
) -> tuple[dict[Sensor, list[Row]], dict[Sensor, int]]:
    """Load eligible targets and keep comparable rows with a current mean."""
    rows: dict[Sensor, list[Row]] = defaultdict(list)
    eligible: dict[Sensor, int] = defaultdict(int)

    for record in iter_role_records(root, ROLE, split):
        target = record.target
        if target["supervised_loss_mask"] is not True:
            continue
        if target["forecast_horizon_s"] != HORIZON_S:
            raise ValueError("Expected a five-minute forecast horizon")

        observations = record.input["observations"]
        summary = observations.get("summary", observations)
        signals = {signal["tag_id"]: signal for signal in summary["signals"]}

        for future in target["future_measurements"]:
            actual = _number(future["mean"])
            if not math.isfinite(actual):
                continue

            tag, unit = future["tag_id"], future["unit"]
            key = (tag, unit)
            eligible[key] += 1

            signal = signals.get(tag)
            if signal is None:
                continue
            if signal["unit"] != unit:
                raise ValueError(f"{tag}: observation and target units differ")

            features = [_number(signal.get(name)) for name in FEATURES]
            if math.isfinite(features[0]):
                rows[key].append((features, actual))

    return rows, eligible


def _arrays(rows: list[Row]) -> tuple[np.ndarray, np.ndarray]:
    """Convert feature rows and future means into separate arrays."""
    return (
        np.asarray([features for features, _ in rows], dtype=float),
        np.asarray([actual for _, actual in rows], dtype=float),
    )


def _ridge_pipeline() -> Any:
    """Build the same Ridge pipeline for evaluation and export."""
    return make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True),
        StandardScaler(),
        Ridge(alpha=1.0),
    )


def _export_model(rows: list[Row], unit: str) -> dict[str, Any]:
    """Fold preprocessing into coefficients and verify runtime parity."""
    x, y = _arrays(rows)
    fitted = _ridge_pipeline().fit(x, y)
    expected = fitted.predict(x)

    imputer, scaler, ridge = fitted.steps[0][1], fitted.steps[1][1], fitted.steps[2][1]
    scaled_weights = ridge.coef_ / scaler.scale_
    base = float(ridge.intercept_ - np.dot(scaled_weights, scaler.mean_))
    keep = np.flatnonzero(np.isfinite(imputer.statistics_))
    weights = np.zeros(len(FEATURES))
    offsets = np.zeros(len(FEATURES))
    weights[keep] = scaled_weights[: len(keep)]
    offsets[keep] = weights[keep] * imputer.statistics_[keep]
    offsets[imputer.indicator_.features_] += scaled_weights[len(keep) :]

    exported = base + np.where(np.isfinite(x), x * weights, offsets).sum(axis=1)
    np.testing.assert_allclose(exported, expected, rtol=1e-10, atol=1e-9)

    bounds = {}
    for index, name in enumerate(FEATURES):
        observed = x[np.isfinite(x[:, index]), index]
        bounds[name] = [float(observed.min()), float(observed.max())] if observed.size else None
    return {
        "unit": unit,
        "base": base,
        "weights": weights.tolist(),
        "missing_offsets": offsets.tolist(),
        "training_ranges": bounds,
    }


def _export(root: Path, destination: Path, train: dict[Sensor, list[Row]]) -> None:
    """Write the model artifact and provenance from training data only."""
    models: dict[str, Any] = {}
    for (tag, unit), rows in sorted(train.items()):
        if tag not in RIDGE_TAGS:
            continue
        if tag in models:
            raise ValueError(f"Multiple training units for {tag}")
        models[tag] = _export_model(rows, unit)
    if models.keys() != RIDGE_TAGS:
        raise ValueError(f"Missing Ridge models: {sorted(RIDGE_TAGS - models.keys())}")

    train_path = root / "role_views" / ROLE / "train.jsonl.gz"
    with train_path.open("rb") as stream:
        training_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    artifact = {
        "horizon_s": HORIZON_S,
        "feature_profile_id": FEATURE_PROFILE_ID,
        "features": list(FEATURES),
        "training_sha256": training_sha256,
        "seed": EVALUATION_SEED,
        "library_versions": {package: version(package) for package in ("numpy", "scikit-learn")},
        "models": models,
    }
    destination.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, allow_nan=False) + chr(10),
        encoding="utf-8",
    )
    print(f"Exported {len(models)} Ridge models to {destination}")


def _evaluation_predictions(
    tag: str,
    train_rows: list[Row],
    x_eval: np.ndarray,
    *,
    test: bool,
) -> dict[str, np.ndarray]:
    """Predict with persistence and the models enabled for this split."""
    predictions = {"persistence": x_eval[:, 0]}
    if not train_rows or (test and tag not in RIDGE_TAGS):
        return predictions

    x_train, y_train = _arrays(train_rows)
    predictions["ridge"] = _ridge_pipeline().fit(x_train, y_train).predict(x_eval)

    if not test:
        tree = HistGradientBoostingRegressor(
            max_iter=100,
            random_state=EVALUATION_SEED,
            early_stopping=False,
        )
        predictions["hist_gradient_boosting"] = tree.fit(x_train, y_train).predict(x_eval)

    return predictions


def _evaluate(root: Path, *, test: bool, train: dict[Sensor, list[Row]]) -> None:
    """Compare forecasts against the selected evaluation split."""
    split = "test" if test else "validation"
    evaluation, eligible = _load_split(root, split)
    if not eligible:
        raise ValueError(f"No eligible targets found in {split}")

    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(
        [
            "tag_id",
            "unit",
            "model",
            "train_rows",
            "eligible_targets",
            "evaluated_rows",
            "forecast_coverage",
            "mae",
            "rmse",
        ]
    )

    for key in sorted(eligible):
        writer.writerows(
            _sensor_evaluation_rows(
                key, train.get(key, []), evaluation.get(key, []), eligible[key], test=test
            )
        )


def _sensor_evaluation_rows(
    key: Sensor, train_rows: list[Row], eval_rows: list[Row], eligible: int, *, test: bool
) -> list[list[Any]]:
    """Compute the CSV rows for one sensor, including unavailable forecasts."""
    tag, unit = key
    if test and tag in RIDGE_TAGS and not train_rows:
        raise ValueError(f"No training rows for selected Ridge model: {tag}")
    count = len(eval_rows)
    if not count:
        return [[tag, unit, "unavailable", len(train_rows), eligible, 0, "0.0000", "", ""]]

    x_eval, y_eval = _arrays(eval_rows)
    predictions = _evaluation_predictions(tag, train_rows, x_eval, test=test)
    coverage = count / eligible
    rows: list[list[Any]] = []
    for name, predicted in predictions.items():
        error = predicted - y_eval
        mae = np.mean(np.abs(error))
        rmse = np.sqrt(np.mean(error**2))
        rows.append(
            [
                tag,
                unit,
                name,
                len(train_rows),
                eligible,
                count,
                f"{coverage:.4f}",
                f"{mae:.8g}",
                f"{rmse:.8g}",
            ]
        )
    return rows


def main() -> None:
    """Fit models on train and print per-sensor evaluation metrics as CSV."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Path to the dataset release")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Evaluate the frozen model choices on the held-out test split",
    )
    parser.add_argument("--export", type=Path, help="Write the training-only Ridge artifact")
    args = parser.parse_args()
    if args.export is not None and args.test:
        parser.error("--export and --test are separate operations")

    train, _ = _load_split(args.root, "train")
    if args.export is not None:
        _export(args.root, args.export, train)
        return
    _evaluate(args.root, test=args.test, train=train)


if __name__ == "__main__":
    main()
