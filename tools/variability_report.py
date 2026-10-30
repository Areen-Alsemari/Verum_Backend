"""Healthy variability of the emitted tags under profiles v1 and v2, over 20 seeds.

Each run lasts 2700 s. The measure is the cross-seed standard deviation of the 60 s mean of the
noise-free series, averaged over the window from 900 s to 2700 s, so it includes the differences
between regimes of different seeds. The within-run spread is reported next to it.

See D68 and D73.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import tempfile
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import numpy as np
from fault_audit import CONT, DURATION_S, RESULTS, SEEDS, clean_series

from verum.hydraulics import HydraulicModel
from verum.sim.episode import run_episode
from verum.sim.scenario import load_scenario

BASES = ("S0-A", "S0-B", "S0-C")
PROFILES = ("v1", "v2")
Job = tuple[str, str, int]


def scenario_of(base: str, profile: str, shift: int) -> Any:
    sid = base if profile == "v1" else f"{base}-v2"
    sc = load_scenario(sid)
    return dataclasses.replace(
        sc, duration_s=DURATION_S, seed=sc.seed + shift, demand_process=True,
        variability_profile=profile,
    )  # fmt: skip


def run_one(job: Job) -> dict[str, Any]:
    base, profile, shift = job
    model = HydraulicModel.load()
    sc = scenario_of(base, profile, shift)
    out = Path(tempfile.mkdtemp(prefix="var_"))
    try:
        result = run_episode(sc.scenario_id, out, model, sc)
        if result.rejected:
            return {"job": job, "rejected": result.outcome.rejection}
        return {
            "job": job, "rejected": None,
            "series": {k: v.tolist() for k, v in clean_series(result.directory).items()
                       if k in CONT},
            "regimes": result.outcome.regimes, "redraws": result.outcome.regime_redraws,
        }  # fmt: skip
    finally:
        shutil.rmtree(out, ignore_errors=True)


def run() -> None:
    jobs = [(b, p, k) for b in BASES for p in PROFILES for k in range(SEEDS)]
    with Pool(9) as pool:
        res = pool.map(run_one, jobs, chunksize=1)
    with open(RESULTS / "variability_runs.json", "w", encoding="utf-8") as fh:
        json.dump(res, fh)
    print("runs", len(res), "rejected", sum(1 for r in res if r["rejected"]))


def spreads(runs: list[dict[str, Any]], base: str, profile: str) -> dict[str, tuple[float, float]]:
    sel = [r for r in runs if r["job"][0] == base and r["job"][1] == profile and not r["rejected"]]
    out = {}
    for tag in CONT:
        x = np.array([r["series"][tag] for r in sel])
        x = x[:, ~np.isnan(x).any(axis=0)]
        out[tag] = (float(x.std(axis=0, ddof=1).mean()), float(x.std(axis=1, ddof=1).mean()))
    return out


def report() -> None:
    with open(RESULTS / "variability_runs.json", encoding="utf-8") as fh:
        runs = json.load(fh)
    lines = [
        "# Healthy variability of the emitted tags, profile v1 against v2", "",
        f"{SEEDS} seeds per cell, 2700 s, 60 s means of the noise-free sampled series, window "
        "900 to 2700 s. Cross-seed = standard deviation over seeds at each time, averaged over "
        "time (decision D68 measure). Within-run = standard deviation over time within a run, "
        "averaged over seeds.", "",
    ]  # fmt: skip
    for base in BASES:
        a, b = spreads(runs, base, "v1"), spreads(runs, base, "v2")
        lines += [
            f"## {base}", "",
            "| tag | cross-seed v1 | cross-seed v2 | ratio | within-run v1 | within-run v2 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]  # fmt: skip
        for tag in CONT:
            ratio = f"{b[tag][0] / a[tag][0]:.2f}" if a[tag][0] > 1e-9 else "-"  # v1 spread ~ 0
            lines.append(
                f"| {tag} | {a[tag][0]:.4g} | {b[tag][0]:.4g} | {ratio} | "
                f"{a[tag][1]:.4g} | {b[tag][1]:.4g} |"
            )
        lines.append("")
    redraws = [len(r["redraws"]) for r in runs if r["job"][1] == "v2" and not r["rejected"]]
    count = [len(r["regimes"]) for r in runs if r["job"][1] == "v2" and not r["rejected"]]
    lines += [
        f"v2 runs: {len(count)}; regimes per run {min(count)} to {max(count)}; redrawn candidates "
        f"in total {sum(redraws)}.", "",
    ]  # fmt: skip
    (RESULTS / "variability.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    import sys

    {"run": run, "report": report}[sys.argv[1]]()
