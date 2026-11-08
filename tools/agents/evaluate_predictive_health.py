"""Compare five-minute sensor forecasts and evaluate the frozen model choices."""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from verum.agents.common.loader import iter_role_records

ROLE = "predictive_health"
HORIZON_S = 300

# Frozen before test evaluation, using the lowest validation MAE per sensor.
RIDGE_TAGS = frozenset({
    "FT-201",
    "LT-101",
    "LT-102",
    "LT-103",
    "PT-201",
    "PT-202A",
    "PT-202B",
    "PT-203",
})

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


def main() -> None:
    """Fit models on train and print per-sensor evaluation metrics as CSV."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Path to the dataset release")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Evaluate the frozen model choices on the held-out test split",
    )
    args = parser.parse_args()

    split = "test" if args.test else "validation"
    train, _ = _load_split(args.root, "train")
    evaluation, eligible = _load_split(args.root, split)

    if not eligible:
        raise ValueError(f"No eligible targets found in {split}")

    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow([
        "tag_id",
        "unit",
        "model",
        "train_rows",
        "eligible_targets",
        "evaluated_rows",
        "forecast_coverage",
        "mae",
        "rmse",
    ])

    for tag, unit in sorted(eligible):
        key = (tag, unit)
        train_rows = train.get(key, [])
        eval_rows = evaluation.get(key, [])
        count = len(eval_rows)
        coverage = count / eligible[key]

        if args.test and tag in RIDGE_TAGS and not train_rows:
            raise ValueError(f"No training rows for selected Ridge model: {tag}")

        if not count:
            writer.writerow([
                tag, unit, "unavailable", len(train_rows),
                eligible[key], 0, "0.0000", "", "",
            ])
            continue

        x_eval, y_eval = _arrays(eval_rows)
        predictions = {"persistence": x_eval[:, 0]}

        if train_rows and (not args.test or tag in RIDGE_TAGS):
            x_train, y_train = _arrays(train_rows)
            ridge = make_pipeline(
                SimpleImputer(strategy="median", add_indicator=True),
                StandardScaler(),
                Ridge(alpha=1.0),
            )

            with threadpool_limits(limits=1):
                predictions["ridge"] = ridge.fit(x_train, y_train).predict(x_eval)

                if not args.test:
                    tree = HistGradientBoostingRegressor(
                        max_iter=100,
                        random_state=42,
                        early_stopping=False,
                    )
                    predictions["hist_gradient_boosting"] = tree.fit(
                        x_train, y_train
                    ).predict(x_eval)

        for name, predicted in predictions.items():
            error = predicted - y_eval
            mae = np.mean(np.abs(error))
            rmse = np.sqrt(np.mean(error**2))
            writer.writerow([
                tag, unit, name, len(train_rows), eligible[key],
                count, f"{coverage:.4f}", f"{mae:.8g}", f"{rmse:.8g}",
            ])


if __name__ == "__main__":
    main()