"""Collection stage of the agent-side audit: the observed tags of every run in 10 s blocks.

Each run stores, for every continuous tag, the sum and the count of the observed values in 10 s
blocks, and the event rows of valve contacts and pump status. Window means and least-squares slopes
over any window that is a multiple of 10 s follow exactly from the blocks. The runs are the healthy
calibration set, a separate healthy set for checking the false-alarm rate, the fault grid and the
sensor-fault cases applied to the first calibration run of each lineup. A rerun skips stored runs.

See D77 to D81.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import numpy as np
from fault_audit import ASSETS, CONT, EVENT, SENSOR_KINDS, SPAN, coordinates, make_spec
from fault_audit_v2 import DURATION_S, FAMILIES, fault_jobs, scenario_of

from verum.faults import FaultSet, FaultSpec
from verum.hydraulics import HydraulicModel
from verum.sensors.adapter import observe_rows
from verum.sim.episode import run_episode

STORE = Path("local/results/audit")
BLOCK_S = 10.0
N_BLOCKS = int(DURATION_S / BLOCK_S)
CALIBRATION_RUNS = 200
HELD_OUT_RUNS = 100
HELD_OUT_SHIFT = 1000
PROFILES = ("v1", "v2")
FAMILY_NAMES = tuple(FAMILIES)
Job = dict[str, Any]


def path_of(label: str) -> Path:
    return STORE / (label.replace("|", "_") + ".npz")


def blocks(rows: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    """Sum and count of the observed values per block, for each continuous tag."""
    out: dict[str, np.ndarray] = {}
    for tag in CONT:
        r = [
            (x["t_sim_s"], x["value"])
            for x in rows
            if x["tag_id"] == tag and x["value"] is not None
        ]
        t, v = np.array([a for a, _ in r]), np.array([b for _, b in r])
        k = np.floor(t / BLOCK_S).astype(int)
        keep = (k >= 0) & (k < N_BLOCKS)
        out[f"s_{tag}"] = np.bincount(k[keep], weights=v[keep], minlength=N_BLOCKS)
        out[f"c_{tag}"] = np.bincount(k[keep], minlength=N_BLOCKS).astype(float)
    return out


def events(rows: list[dict[str, Any]]) -> str:
    ev = {
        tag: [[x["t_sim_s"], x["value"]] for x in rows if x["tag_id"] == tag]
        for tag in EVENT
        if not tag.startswith("LSHH")
    }
    return json.dumps(ev)


def store(label: str, rows: list[dict[str, Any]]) -> None:
    np.savez_compressed(path_of(label), events=np.array(events(rows)), **blocks(rows))


def store_sensor_cases(family: str, profile: str, directory: Path) -> None:
    for kind in SENSOR_KINDS:
        for asset in ASSETS[kind][FAMILIES[family][0]]:
            for i, coord in enumerate(coordinates(kind)):
                hook = FaultSet((make_spec(kind, asset, coord),)).sensor_hook(SPAN)
                label = f"case|{kind}|{family}|{asset}|{i}|{profile}"
                store(label, observe_rows(directory, hook=hook).observations)


def run_job(job: Job) -> str:
    model = HydraulicModel.load()
    sc = scenario_of(job["family"], job["profile"], job["shift"])
    spec = FaultSpec(**job["spec"]) if job["spec"] else None
    out = Path(tempfile.mkdtemp(prefix="audit_"))
    try:
        result = run_episode(sc.scenario_id, out, model, sc, FaultSet((spec,)) if spec else None)
        if result.rejected:
            gate = str(result.outcome.rejection.get("gate")) if result.outcome.rejection else ""
            np.savez_compressed(path_of(job["label"]), rejected=np.array(gate))
            return job["label"]
        store(job["label"], observe_rows(result.directory).observations)
        if job["sensors"]:
            store_sensor_cases(job["family"], job["profile"], result.directory)
        return job["label"]
    finally:
        shutil.rmtree(out, ignore_errors=True)


def healthy_jobs(profile: str) -> list[Job]:
    jobs = []
    for family in FAMILY_NAMES:
        for kind, count, base in (
            ("cal", CALIBRATION_RUNS, 0),
            ("held", HELD_OUT_RUNS, HELD_OUT_SHIFT),
        ):
            for k in range(count):
                jobs.append(
                    {
                        "label": f"{kind}|{family}|{profile}|{k}",
                        "family": family,
                        "profile": profile,
                        "shift": base + k,
                        "spec": None,
                        "sensors": kind == "cal" and k == 0 and family != "B2",
                    }
                )
    return jobs


def main(profiles: list[str]) -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    jobs = [j for p in profiles for j in healthy_jobs(p) + fault_jobs(p)]
    todo = [j for j in jobs if not path_of(j["label"]).exists()]
    todo.sort(key=lambda j: (not j["sensors"], j["spec"] is None))  # long jobs first
    print(len(jobs), "runs,", len(todo), "to do", flush=True)
    with Pool(9) as pool:
        for k, label in enumerate(pool.imap_unordered(run_job, todo, chunksize=1)):
            if k % 50 == 0:
                print(k, label, flush=True)
    print("done")


if __name__ == "__main__":
    main(sys.argv[1:] or list(PROFILES))
