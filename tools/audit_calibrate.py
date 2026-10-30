"""Threshold calibration of the agent-side audit, and its check on a separate healthy set.

For each profile and lineup the features of the calibration runs fix the healthy mean and the 99th
percentile threshold of every feature and window length; the features of the held-out runs give the
false-alarm rate of those thresholds. The noise floor of the mass-balance slope is compared with the
hand estimate from the level noise. Results are written to the store and printed as tables.

See D79 and D80.
"""

from __future__ import annotations

import json
import math
import pickle
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import numpy as np
from audit_collect import CALIBRATION_RUNS, HELD_OUT_RUNS, PROFILES, path_of
from audit_features import (
    DRAWS,
    LAYOUT,
    STORE,
    WINDOWS_S,
    features,
    load_run,
)

from verum.evaluation.agent_audit import calibrate, deviation_maxima
from verum.sensors import load_sensor_config
from verum.tanks import load_tank_geometry

RESULTS = Path("local/results")
Matrix = dict[tuple[int, str], np.ndarray]


def run_matrix(args: tuple[str, str]) -> Matrix | None:
    """Features of one stored run under the six designs: arrays of shape (6, windows)."""
    label, fam = args
    run = load_run(path_of(label))
    if run.rejected:
        return None
    per_draw = [features(run, fam, d) for d in range(len(DRAWS))]
    return {key: np.stack([f[key] for f in per_draw]) for key in per_draw[0]}


def group(
    profile: str, fam: str, kind: str, count: int, pool: Pool
) -> dict[tuple[int, str], np.ndarray]:
    """Stack the feature matrices of a healthy set: shape (runs, 6 draws, windows)."""
    cache = STORE / f"features_{kind}_{fam}_{profile}.pkl"
    if cache.exists():
        loaded: dict[tuple[int, str], np.ndarray] = pickle.loads(cache.read_bytes())
        return loaded
    labels = [(f"{kind}|{fam}|{profile}|{k}", fam) for k in range(count)]
    mats = [m for m in pool.map(run_matrix, labels, chunksize=2) if m is not None]
    stacked = {key: np.stack([m[key] for m in mats]) for key in mats[0]}
    cache.write_bytes(pickle.dumps(stacked))
    return stacked


def thresholds(cal: dict[tuple[int, str], np.ndarray]) -> dict[tuple[int, str], dict[str, Any]]:
    out = {}
    for key, series in cal.items():
        t = calibrate(series[:, 1:, :])
        if np.isfinite(t.value) and t.value > 0.0:
            out[key] = {"mean": t.mean, "value": t.value, "error": t.error, "runs": t.runs}
    return out


def false_alarms(
    held: dict[tuple[int, str], np.ndarray], th: dict[tuple[int, str], dict[str, Any]]
) -> dict[str, Any]:
    """Per feature and window length, and over all features, the share of held-out runs above 1."""
    ratios: dict[tuple[int, str], np.ndarray] = {}
    for key, t in th.items():
        ratios[key] = deviation_maxima(held[key][:, 1:, :], t["mean"]) / t["value"]
    per = {f"{k[0]}|{k[1]}": float(np.nanmean(r > 1.0)) for k, r in ratios.items()}
    by_length = {}
    for length in WINDOWS_S:
        stack = np.stack([r for k, r in ratios.items() if k[0] == length])
        by_length[str(length)] = float(np.mean(np.nanmax(stack, axis=0) > 1.0))
    every = np.stack(
        [
            np.nanmax(np.stack([r for k, r in ratios.items() if k[0] == length]), axis=0)
            for length in WINDOWS_S
        ]
    )
    return {
        "per_feature": per,
        "any_by_length": by_length,
        "any": float(np.mean(every.max(axis=0) > 1.0)),
    }


def hand_floor(length_s: int) -> float:
    """Noise of the summed volume rate of three tanks from the level noise, in m3/h.

    The slope of n readings 5 s apart has standard deviation sigma / sqrt(5^2 n (n^2 - 1) / 12).
    """
    n = length_s / 5.0
    sigma = load_sensor_config().sigma("level")
    spread = math.sqrt(25.0 * n * (n * n - 1.0) / 12.0)
    return load_tank_geometry().area_m2 * 3600.0 * sigma / spread * math.sqrt(3.0)


def main() -> None:
    summary: dict[str, Any] = {}
    with Pool(9) as pool:
        for profile in PROFILES:
            for fam in LAYOUT:
                cal = group(profile, fam, "cal", CALIBRATION_RUNS, pool)
                held = group(profile, fam, "held", HELD_OUT_RUNS, pool)
                th = thresholds(cal)
                fa = false_alarms(held, th)
                floor = {
                    str(length): float(np.nanstd(cal[(length, "mass_balance")][:, 1, :]))
                    for length in WINDOWS_S
                }
                summary[f"{profile}|{fam}"] = {
                    "thresholds": {f"{k[0]}|{k[1]}": v for k, v in th.items()},
                    "false_alarm": fa,
                    "mass_balance_std": floor,
                    "runs": [
                        int(next(iter(cal.values())).shape[0]),
                        int(next(iter(held.values())).shape[0]),
                    ],
                }
                print(profile, fam, "any-feature false alarm", fa["any"], flush=True)
    summary["hand_floor"] = {str(length): hand_floor(length) for length in WINDOWS_S}
    (RESULTS / "audit_calibration.json").write_text(json.dumps(summary), encoding="utf-8")


if __name__ == "__main__":
    main()
    sys.exit(0)
