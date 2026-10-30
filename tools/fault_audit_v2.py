"""Agent-side audit, collection stage: 60 s window means of the observed tags, per run.

Inputs: the plant model, the fault grid of the Phase 6a audit (``tools/fault_audit.py``) and the
profiles v1 and v2. Outputs: ``local/results/audit_v2_runs.jsonl``, one line per run, with the
window means of every continuous tag (the noisy observation rows an agent receives), the event
rows (valve contacts, pump run status) and, for a healthy run of the first seed, the same for every
sensor fault case. Run as ``python tools/fault_audit_v2.py [profile ...]``; a rerun skips the labels
already in the file. The analysis is ``tools/fault_audit_v2_report.py``.
Grid: the Phase 6a grid under each profile: 8 log-spaced severities, scenarios S0-A, S0-C and S0-B,
three assets per type, onset 900 s, 1800 s observed, ramp 300 s, coastal, 25 C, reference fittings;
restrictions in both modes (decision D74); misrouting (b) on the parallel receipt valves
``XV-R101`` and ``XV-R102`` of the lineup ``RECEIVE_101_102`` (decision D75) in place of the serial
valves of Phase 6a. Healthy runs: 20 seeds for each profile and each of the four lineups (the
fourth is S0-B with ``RECEIVE_101_102``).
Assumptions: profile v1 is the shipped scenario with the demand process on, profile v2 is its copy
S0-x-v2; the window k covers the time (60 (k - 1), 60 k] s; no value is imputed (a window without a
reading is NaN); a sensor fault acts on the readings of the healthy run of the first seed in the
sensor chain only, as in Phase 6a.
Source: ``docs/design_decisions.md`` D68, D73 to D78; serves the Phase 6b report.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import numpy as np
from fault_audit import (
    ASSETS,
    CONT,
    EVENT,
    N_SEV,
    ONSET_S,
    RAMP_S,
    SENSOR_KINDS,
    SPAN,
    coordinates,
    make_spec,
)

from verum.faults import FaultSet, FaultSpec
from verum.hydraulics import HydraulicModel
from verum.sensors.adapter import observe_rows
from verum.sim.episode import run_episode
from verum.sim.scenario import load_scenario

RESULTS = Path("local/results")
OUT = RESULTS / "audit_v2_runs.jsonl"
DURATION_S = 2700.0
WINDOW_S = 60.0
N_WINDOWS = int(DURATION_S / WINDOW_S)
SEEDS = 20
# family -> (scenario file, initial mode override)
FAMILIES: dict[str, tuple[str, str | None]] = {
    "A": ("S0-A", None), "B": ("S0-B", None), "C": ("S0-C", None),
    "B2": ("S0-B", "RECEIVE_101_102"),
}  # fmt: skip
PROFILES = ("v1", "v2")
MODES = ("position_visible", "obstruction")
MISROUTE_B_ASSETS = ("XV-R101", "XV-R102")
Job = dict[str, Any]


def scenario_of(family: str, profile: str, shift: int) -> Any:
    base, mode = FAMILIES[family]
    sc = load_scenario(base if profile == "v1" else f"{base}-v2")
    fields: dict[str, Any] = {
        "duration_s": DURATION_S, "seed": sc.seed + shift, "demand_process": True,
        "variability_profile": profile,
    }  # fmt: skip
    if mode:
        fields["initial_mode"] = mode
    return dataclasses.replace(sc, **fields)


def spec_for(kind: str, asset: str, coordinate: float | None, mode: str | None) -> FaultSpec:
    if kind == "restriction":
        assert coordinate is not None
        return FaultSpec(
            "VALVE_RESTRICTION", "restriction", asset, ONSET_S, RAMP_S, 1.0 - coordinate,
            fault_mode=mode,
        )  # fmt: skip
    return make_spec(kind, asset, coordinate)


def window_means(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for tag in CONT:
        r = [
            (x["t_sim_s"], x["value"])
            for x in rows
            if x["tag_id"] == tag and x["value"] is not None
        ]
        t, v = np.array([a for a, _ in r]), np.array([b for _, b in r])
        k = np.ceil(t / WINDOW_S).astype(int)
        keep = (k >= 1) & (k <= N_WINDOWS)
        total = np.bincount(k[keep], weights=v[keep], minlength=N_WINDOWS + 1)
        count = np.bincount(k[keep], minlength=N_WINDOWS + 1)
        mean = np.where(count > 0, total / np.maximum(count, 1), np.nan)
        out[tag] = mean[1:].tolist()
    return out


def events(rows: list[dict[str, Any]]) -> dict[str, list[list[float]]]:
    return {
        tag: [[x["t_sim_s"], x["value"]] for x in rows if x["tag_id"] == tag]
        for tag in EVENT
        if not tag.startswith("LSHH")
    }


def observed(rows_result: Any) -> dict[str, Any]:
    rows = rows_result.observations
    return {"wm": window_means(rows), "ev": events(rows)}


def sensor_cases(family: str, directory: Path) -> dict[str, Any]:
    out = {}
    for kind in SENSOR_KINDS:
        for asset in ASSETS[kind][FAMILIES[family][0]]:
            for i, coord in enumerate(coordinates(kind)):
                hook = FaultSet((make_spec(kind, asset, coord),)).sensor_hook(SPAN)
                out[f"{kind}|{family}|{asset}|{i}"] = observed(observe_rows(directory, hook=hook))
    return out


def run_job(job: Job) -> dict[str, Any]:
    model = HydraulicModel.load()
    sc = scenario_of(job["family"], job["profile"], job["shift"])
    spec = FaultSpec(**job["spec"]) if job["spec"] else None
    out = Path(tempfile.mkdtemp(prefix="audit2_"))
    try:
        result = run_episode(sc.scenario_id, out, model, sc, FaultSet((spec,)) if spec else None)
        if result.rejected:
            return {"label": job["label"], "rejected": result.outcome.rejection}
        record = {"label": job["label"], "rejected": None,
                  "windows": [w.kind for w in result.outcome.windows],
                  **observed(observe_rows(result.directory))}  # fmt: skip
        if job["sensors"]:
            record["sensor_cases"] = sensor_cases(job["family"], result.directory)
        return record
    finally:
        shutil.rmtree(out, ignore_errors=True)


def healthy_jobs(profile: str) -> list[Job]:
    return [
        {"label": f"healthy|{fam}|{profile}|{k}", "family": fam, "profile": profile, "shift": k,
         "spec": None, "sensors": k == 0 and fam != "B2"}
        for fam in FAMILIES
        for k in range(SEEDS)
    ]  # fmt: skip


def fault_jobs(profile: str) -> list[Job]:
    jobs: list[Job] = []

    def add(kind: str, fam: str, asset: str, i: int, coord: float | None, mode: str | None) -> None:
        spec = spec_for(kind, asset, coord, mode)
        label = f"{kind}|{fam}|{asset}|{i}|{mode or ''}|{profile}"
        jobs.append({"label": label, "family": fam, "profile": profile, "shift": 0,
                     "spec": dataclasses.asdict(spec), "sensors": False})  # fmt: skip

    for kind in ("leak", "restriction", "pump", "misroute_a"):
        for fam in ("A", "C", "B"):
            for asset in ASSETS[kind].get(FAMILIES[fam][0], []):
                for i, coord in enumerate(coordinates(kind)):
                    for mode in MODES if kind == "restriction" else (None,):
                        add(kind, fam, asset, i, coord, mode)
    for asset in MISROUTE_B_ASSETS:
        for i, coord in enumerate(coordinates("misroute_b")):
            add("misroute_b", "B2", asset, i, coord, None)
    return jobs


def done_labels() -> set[str]:
    if not OUT.exists():
        return set()
    return {json.loads(line)["label"] for line in OUT.read_text(encoding="utf-8").splitlines()}


def main(profiles: list[str]) -> None:
    jobs = [j for p in profiles for j in healthy_jobs(p) + fault_jobs(p)]
    finished = done_labels()
    todo = [j for j in jobs if j["label"] not in finished]
    todo.sort(key=lambda j: (not j["sensors"], j["spec"] is not None))  # long jobs first
    print(len(jobs), "jobs,", len(todo), "to run", flush=True)
    with Pool(9) as pool, OUT.open("a", encoding="utf-8") as fh:
        for k, r in enumerate(pool.imap_unordered(run_job, todo, chunksize=1)):
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            if k % 25 == 0:
                print(k, r["label"], flush=True)
    print("done", N_SEV)


if __name__ == "__main__":
    main(sys.argv[1:] or list(PROFILES))
