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


def family_scale(
    cal: dict[tuple[int, str], np.ndarray],
    held: dict[tuple[int, str], np.ndarray],
    th: dict[tuple[int, str], dict[str, Any]],
) -> dict[str, float]:
    """Common factor on all thresholds that gives 1 percent of healthy runs an alarm on any feature.

    The factor is the 99th percentile, over calibration runs and draws, of the largest ratio over
    all features and window lengths; the rate on the held-out runs is then checked against it.
    """

    def worst(data: dict[tuple[int, str], np.ndarray]) -> np.ndarray:
        ratios = [
            deviation_maxima(data[k][:, 1:, :], t["mean"]) / t["value"] for k, t in th.items()
        ]
        return np.nanmax(np.stack(ratios), axis=0)

    scale = float(np.percentile(worst(cal), 99.0))
    return {"scale": scale, "held_out_rate": float(np.mean(worst(held) > scale))}


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
                fa.update(family_scale(cal, held, th))
                rates = np.array(list(fa["per_feature"].values()))
                fa["mean_per_feature"] = float(rates.mean())
                fa["share_above_2_percent"] = float(np.mean(rates > 0.02))
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


def report() -> None:
    """Tables of the calibration from the stored summary."""
    d = json.loads((RESULTS / "audit_calibration.json").read_text(encoding="utf-8"))
    hand = d.pop("hand_floor")
    out = ["# Calibration of the thresholds", ""]
    head = "| profile | lineup | calibration runs | held-out runs | threshold error, median | max |"
    out += ["## Runs and percentile error", "", head, "| --- | --- | --- | --- | --- | --- |"]
    for key, v in d.items():
        profile, fam = key.split("|")
        rel = [t["error"] / t["value"] for t in v["thresholds"].values()]
        out.append(
            f"| {profile} | {fam} | {v['runs'][0]} | {v['runs'][1]} | "
            f"{100 * np.median(rel):.1f} percent | {100 * max(rel):.1f} percent |"
        )
    head = "| profile | lineup | mean per feature | features above 2 percent | any feature "
    head += "| scale | any feature, scaled |"
    out += ["", "## False-alarm rates on the held-out runs", "", head, "| --- |" + " --- |" * 6]
    for key, v in d.items():
        profile, fam = key.split("|")
        fa = v["false_alarm"]
        out.append(
            f"| {profile} | {fam} | {100 * fa['mean_per_feature']:.2f} percent | "
            f"{100 * fa['share_above_2_percent']:.0f} percent | {100 * fa['any']:.0f} percent | "
            f"{fa['scale']:.2f} | {100 * fa['held_out_rate']:.0f} percent |"
        )
    out += ["", "## Mass-balance noise floor (m3/h)", ""]
    out += ["| profile | lineup | 60 s | 300 s | 900 s |", "| --- | --- | --- | --- | --- |"]
    out.append(f"| hand | all | {hand['60']:.2f} | {hand['300']:.2f} | {hand['900']:.3f} |")
    for key, v in d.items():
        m = v["mass_balance_std"]
        profile, fam = key.split("|")
        out.append(f"| {profile} | {fam} | {m['60']:.2f} | {m['300']:.2f} | {m['900']:.3f} |")
    for key, v in d.items():
        out += ["", f"## Features of {key.replace('|', ' ')}", ""]
        out += ["| window | feature | healthy mean | threshold | threshold error | false alarms |"]
        out += ["| --- | --- | --- | --- | --- | --- |"]
        trends: list[float] = []
        for name, t in sorted(v["thresholds"].items(), key=lambda kv: feature_order(kv[0])):
            length, feature = name.split("|")
            rate = v["false_alarm"]["per_feature"][name]
            if feature.startswith("trend:"):
                trends.append(rate)
                continue
            out.append(
                f"| {length} s | {feature} | {t['mean']:.4g} | {t['value']:.4g} | "
                f"{100 * t['error'] / t['value']:.1f} percent | {100 * rate:.0f} percent |"
            )
        out.append(
            f"| all | {len(trends)} trend features | | | | mean {100 * np.mean(trends):.1f} "
            f"percent, largest {100 * max(trends):.0f} percent |"
        )
    (RESULTS / "audit_calibration.md").write_text("\n".join(out) + "\n", encoding="utf-8")


def feature_order(name: str) -> tuple[str, int]:
    length, feature = name.split("|")
    return feature, int(length)


if __name__ == "__main__":
    report() if "report" in sys.argv else main()
