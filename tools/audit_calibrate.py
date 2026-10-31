"""Threshold calibration of the agent-side audit, its scale factor and the check on held-out runs.

For each profile and lineup the features of the 200 calibration runs fix the healthy mean and the
99th percentile threshold of every feature and window length, and the scale factor that keeps at
most 1 percent of those runs from an alarm on any feature. Five folds of the calibration runs show
how much the factor varies, and the 100 held-out runs, which no derivation uses, give the
false-alarm rates. The noise floor of the mass balance is compared with the hand estimate from
the level noise.

See D79, D80, D89 and D89b.
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

from verum.evaluation.agent_audit import (
    calibrate,
    check_calibration_labels,
    deviation_maxima,
    folds,
    run_margin,
    scale_factor,
)
from verum.rng import RandomStreams
from verum.sensors import load_sensor_config
from verum.tanks import load_tank_geometry

RESULTS = Path("local/results")
FOLDS = 5
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


def thresholds(
    cal: dict[tuple[int, str], np.ndarray], rows: np.ndarray | None = None, boot: int = 200
) -> dict[tuple[int, str], dict[str, Any]]:
    """Healthy mean and 99th percentile threshold of every feature, from the chosen runs."""
    out = {}
    for key, series in cal.items():
        chosen = series if rows is None else series[rows]
        t = calibrate(chosen[:, 1:, :], boot=boot)
        if np.isfinite(t.value) and t.value > 0.0:
            out[key] = {"mean": t.mean, "value": t.value, "error": t.error, "runs": t.runs}
    return out


def ratios(
    data: dict[tuple[int, str], np.ndarray],
    th: dict[tuple[int, str], dict[str, Any]],
    rows: np.ndarray | None = None,
) -> np.ndarray:
    """Deviation over threshold for each feature, run and design draw: (features, runs, draws)."""
    out = []
    for key, t in th.items():
        series = data[key] if rows is None else data[key][rows]
        out.append(deviation_maxima(series[:, 1:, :], t["mean"]) / t["value"])
    return np.stack(out)


def derive_scale(
    cal: dict[tuple[int, str], np.ndarray], labels: list[str], seed_name: str
) -> dict[str, Any]:
    """Thresholds, scale factor and the cross-check by folds, from the calibration runs only."""
    check_calibration_labels(labels)
    th = thresholds(cal)
    scale = scale_factor(run_margin(ratios(cal, th)))
    count = len(labels)
    rng = RandomStreams(20261201).stream(seed_name)
    factors, out_of_fold = [], []
    for held in folds(count, FOLDS, rng):
        train = np.setdiff1d(np.arange(count), held)
        th_k = thresholds(cal, train, boot=0)
        c_k = scale_factor(run_margin(ratios(cal, th_k, train)))
        factors.append(c_k)
        out_of_fold += list(run_margin(ratios(cal, th_k, held)) > c_k)
    return {
        "thresholds": th, "scale": scale, "fold_scales": factors,
        "out_of_fold_rate": float(np.mean(out_of_fold)),
        "in_sample_rate": float(np.mean(run_margin(ratios(cal, th)) > scale)),
    }  # fmt: skip


def held_out_rates(
    held: dict[tuple[int, str], np.ndarray],
    th: dict[tuple[int, str], dict[str, Any]],
    scale: float,
) -> dict[str, Any]:
    """False-alarm rates on the held-out runs: per feature (scaled and not) and on any feature."""
    r = ratios(held, th)
    per_run = np.nanmax(r, axis=0)
    per_feature = {f"{k[0]}|{k[1]}": float(np.nanmean(r[i] > 1.0)) for i, k in enumerate(th)}
    scaled = {f"{k[0]}|{k[1]}": float(np.nanmean(r[i] > scale)) for i, k in enumerate(th)}
    return {
        "per_feature": per_feature, "per_feature_scaled": scaled,
        "any_unscaled": float(np.mean(run_margin(r) > 1.0)),
        "any_scaled": float(np.mean(run_margin(r) > scale)),
        "worst_draw_ignored_any_scaled": float(np.mean(per_run.max(axis=-1) > scale)),
    }  # fmt: skip


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
                labels = [f"cal|{fam}|{profile}|{k}" for k in range(CALIBRATION_RUNS)]
                derived = derive_scale(cal, labels, f"audit_folds/{profile}/{fam}")
                th, scale = derived["thresholds"], derived["scale"]
                fa = held_out_rates(held, th, scale)
                rates = np.array(list(fa["per_feature_scaled"].values()))
                fa.update(
                    scale=scale, fold_scales=derived["fold_scales"],
                    out_of_fold_rate=derived["out_of_fold_rate"],
                    in_sample_rate=derived["in_sample_rate"],
                    mean_per_feature_scaled=float(rates.mean()),
                    share_above_2_percent_scaled=float(np.mean(rates > 0.02)),
                    mean_per_feature=float(np.mean(list(fa["per_feature"].values()))),
                )  # fmt: skip
                floor = {
                    name: {
                        str(length): float(np.nanstd(cal[(length, name)][:, 1, :]))
                        for length in WINDOWS_S
                    }
                    for name in ("mass_balance", "mass_balance_matched")
                }
                summary[f"{profile}|{fam}"] = {
                    "thresholds": {f"{k[0]}|{k[1]}": v for k, v in th.items()},
                    "false_alarm": fa, "mass_balance_std": floor["mass_balance"],
                    "matched_std": floor["mass_balance_matched"],
                    "runs": [CALIBRATION_RUNS, HELD_OUT_RUNS],
                }  # fmt: skip
                print(profile, fam, f"scale {scale:.3f}", "held-out", fa["any_scaled"], flush=True)
    summary["hand_floor"] = {str(length): hand_floor(length) for length in WINDOWS_S}
    (RESULTS / "audit_calibration.json").write_text(json.dumps(summary), encoding="utf-8")


def report() -> None:
    """Tables of the calibration from the stored summary."""
    d = json.loads((RESULTS / "audit_calibration.json").read_text(encoding="utf-8"))
    hand = d.pop("hand_floor")
    out = ["# Calibration, scale factor and held-out check", ""]
    head = "| profile | lineup | scale | folds: min | max | spread (std) | out-of-fold rate "
    head += "| in-sample rate | held-out, any feature |"
    out += ["## Scale factor", "", head, "| --- |" + " --- |" * 8]
    for key, v in d.items():
        profile, fam = key.split("|")
        fa = v["false_alarm"]
        f = np.array(fa["fold_scales"])
        out.append(
            f"| {profile} | {fam} | {fa['scale']:.3f} | {f.min():.3f} | {f.max():.3f} | "
            f"{f.std(ddof=1):.3f} | {100 * fa['out_of_fold_rate']:.1f} percent | "
            f"{100 * fa['in_sample_rate']:.1f} percent | {100 * fa['any_scaled']:.0f} percent |"
        )
    head = "| profile | lineup | any feature, unscaled | per feature, unscaled (mean) "
    head += "| per feature, scaled (mean) | features above 2 percent, scaled |"
    out += ["", "## False-alarm rates on the held-out runs", "", head, "| --- |" + " --- |" * 5]
    for key, v in d.items():
        profile, fam = key.split("|")
        fa = v["false_alarm"]
        out.append(
            f"| {profile} | {fam} | {100 * fa['any_unscaled']:.0f} percent | "
            f"{100 * fa['mean_per_feature']:.2f} percent | "
            f"{100 * fa['mean_per_feature_scaled']:.2f} percent | "
            f"{100 * fa['share_above_2_percent_scaled']:.0f} percent |"
        )
    out += ["", "## Mass-balance noise floor (m3/h, standard deviation over healthy windows)", ""]
    out += ["| profile | lineup | feature | 60 s | 300 s | 900 s |", "| --- |" + " --- |" * 5]
    out.append(
        f"| hand | all | level noise | {hand['60']:.2f} | {hand['300']:.2f} | {hand['900']:.3f} |"
    )
    for key, v in d.items():
        profile, fam = key.split("|")
        for name, field in (("difference", "mass_balance_std"), ("matched", "matched_std")):
            m = v[field]
            out.append(
                f"| {profile} | {fam} | {name} | {m['60']:.2f} | {m['300']:.2f} | {m['900']:.3f} |"
            )
    for key, v in d.items():
        out += ["", f"## Features of {key.replace('|', ' ')}", ""]
        out += ["| window | feature | healthy mean | threshold | threshold error | false alarms |"]
        out += ["| --- | --- | --- | --- | --- | --- |"]
        trends: list[float] = []
        ordered = sorted(v["thresholds"].items(), key=lambda kv: feature_order(kv[0]))
        for name, t in ordered:
            length, feature = name.split("|")
            rate = v["false_alarm"]["per_feature_scaled"][name]
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
