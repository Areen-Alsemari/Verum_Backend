"""Fit the topology residual detector on fault-free train windows and write its parameter file.

Inputs: the diagnostic reasoning role view of the train split, which carries the window
summaries and the labels used only to select fault-free windows. Output: a small JSON file of
fitted numbers, thresholds, units and the tag-to-role mapping, with the sha256 of the train file
used. No validation or test data is opened. The window threshold and the residual thresholds are
the 95th percentile of fault-free window values that the fitted model did not see, from five
folds that hold out whole units (family, atmosphere, temperature). The set conditions only form
those folds; the fitted model does not read them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

DETECTOR = Path(__file__).resolve().parents[1] / "detector"
sys.path.insert(0, str(DETECTOR))

import conditions  # noqa: E402
import guard  # noqa: E402
from candidates import Residuals  # noqa: E402
from systems import fold_map  # noqa: E402
from windows import Windows, load_split, subset  # noqa: E402

METHOD_ID = "topology_residual_v1"
FORMAT = 1
FOLDS = 5
PERCENTILE = 95
SLOPE_TO_PER_HOUR = 3600.0
RELEASE_DEFAULT = Path("data/reference_release_v2/verum_reference_v2")
TRAIN_VIEW = Path("role_views/diagnostic_reasoning/train.jsonl.gz")
TAG_ROLES = {
    "FT-001": ("m3/h", "mean", "receipt flow meter"),
    "FT-201": ("m3/h", "mean", "delivery flow meter"),
    "LT-101": ("m", "slope_per_s", "level of tank TK-101"),
    "LT-102": ("m", "slope_per_s", "level of tank TK-102"),
    "LT-103": ("m", "slope_per_s", "level of tank TK-103"),
    "PT-001": ("barg", "mean", "receipt line pressure"),
    "PT-201": ("barg", "mean", "pump suction header pressure"),
    "PT-202A": ("barg", "mean", "discharge pressure of pump P-101A"),
    "PT-202B": ("barg", "mean", "discharge pressure of pump P-101B"),
    "PT-203": ("barg", "mean", "discharge header pressure"),
    "P-101A": ("bool", "latest_value", "run state of pump P-101A"),
    "P-101B": ("bool", "latest_value", "run state of pump P-101B"),
}
RESIDUALS = {
    "R1": ("mass_balance", ["FT-001", "FT-201", "LT-101", "LT-102", "LT-103"]),
    "R2": ("pump_head", ["PT-202A", "PT-202B", "PT-201", "FT-201", "P-101A", "P-101B"]),
    "R3": ("discharge_loss", ["PT-202A", "PT-202B", "PT-203", "FT-201", "P-101A", "P-101B"]),
    "R4": ("receipt_line", ["PT-001", "FT-001"]),
}


def file_sha256(path: Path) -> str:
    """Hex sha256 of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def out_of_fold(train: Windows) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    """Scores and residual values of fault-free train windows from models that did not see them."""
    units = fold_map(train.unit, FOLDS)
    which = np.asarray([units[u] for u in train.unit])
    scores, parts = np.full(len(which), np.nan), np.full((len(which), 4), np.nan)
    for k in range(FOLDS):
        held = which == k
        fit = subset(train, ~held & (train.faulty == 0))
        scored = Residuals(fit, pooled_r4=True).score(subset(train, held))
        scores[held], parts[held] = scored.scores, scored.parts
    free = train.faulty == 0
    return scores[free], parts[free]


def fit_numbers(model: Residuals) -> dict[str, Any]:
    """The fitted coefficients and scales of the final model, in plain lists."""
    pump = [
        {"residual": k[0], "pump": k[2], "state": k[1], "coefficients": f.coef.tolist(),
         "sigma": f.sigma}
        for k, f in sorted(model.fits.items()) if k[0] in ("R2", "R3")
    ]  # fmt: skip
    r4 = model.fits[("R4", "*", "")]
    return {
        "mass_balance": {
            "coefficients": model.mass.coef.tolist(),
            "sigma": model.mass.sigma,
            "slope_to_per_hour": SLOPE_TO_PER_HOUR,
        },  # fmt: skip
        "pump_fits": pump,
        "receipt_line": {"coefficients": r4.coef.tolist(), "sigma": r4.sigma},
    }


def count_numbers(doc: dict[str, Any]) -> int:
    """Fitted numbers in the file: coefficients and scales of all fits."""
    mass = doc["mass_balance"]
    total = len(mass["coefficients"]) + 1
    total += sum(len(f["coefficients"]) + 1 for f in doc["pump_fits"])
    return total + len(doc["receipt_line"]["coefficients"]) + 1


def build_document(train: Windows, source: Path, rel: Path) -> dict[str, Any]:
    """Fit on all fault-free train windows and assemble the parameter document."""
    free = subset(train, train.faulty == 0)
    model = Residuals(free, pooled_r4=True)
    scores, parts = out_of_fold(train)
    doc: dict[str, Any] = {
        "method_id": METHOD_ID, "format": FORMAT,
        "provenance": {
            "train_file": str(TRAIN_VIEW), "train_file_sha256": file_sha256(rel / TRAIN_VIEW),
            "fit_windows": len(free.ids), "threshold_windows": len(scores), "folds": FOLDS,
            "fit_script": source.name, "splits_used": ["train"],
        },
        "inputs": {t: {"unit": u, "field": f, "role": r} for t, (u, f, r) in TAG_ROLES.items()},
        "mapping_note": "The roles follow tag names. The declared reference gives no "
        "instrument location; this mapping is unverified.",
        "residuals": {k: {"name": n, "reads": r} for k, (n, r) in RESIDUALS.items()},
        "dead_zone_sigmas": 1.0,
        **fit_numbers(model),
        "thresholds": {
            "rule": f"{PERCENTILE}th percentile of out-of-fold fault-free train window values",
            "window_score": float(np.percentile(scores, PERCENTILE)),
            "residuals": {
                f"R{j + 1}": float(np.percentile(parts[:, j], PERCENTILE)) for j in range(4)
            },
        },
    }  # fmt: skip
    doc["provenance"]["fitted_numbers"] = count_numbers(doc)
    return doc


def main() -> None:
    """Fit and write the parameter file; print its sha256."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, default=RELEASE_DEFAULT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    guard.install()
    train = load_split(args.release, "train")
    guard.ALLOWED_EPISODES.update(train.episodes)
    train = conditions.apply(train, conditions.read_conditions(args.release, train.episodes))
    doc = build_document(train, Path(__file__), args.release)
    text = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    args.out.write_text(text, encoding="utf-8")
    print(hashlib.sha256(text.encode()).hexdigest(), args.out)
    print("fitted numbers:", doc["provenance"]["fitted_numbers"],
          "window threshold:", round(doc["thresholds"]["window_score"], 4))  # fmt: skip
    print("opened:", guard.summary())


if __name__ == "__main__":
    main()
