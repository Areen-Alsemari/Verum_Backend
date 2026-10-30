"""Observability audit of the single faults: what each fault changes in the emitted tags.

Inputs: the plant model and the fault types of ``verum.faults``. Outputs:
``local/results/fault_audit_baseline.json`` and ``fault_audit_runs.json`` (every run; a partial
rerun ``faults <kind> ...`` writes ``fault_audit_runs_<kinds>.json``) and, from the report stage
(``python tools/fault_audit_report.py``), ``fault_audit.md`` (the tables), ``fault_audit.json`` and
``fault_audit_summary.md`` (the table ``docs/fault_models.md`` quotes). Run as
``python tools/fault_audit.py {baseline|faults}``.
Grid: each fault type, 8 log-spaced severities across its range, scenarios S0-A (delivery from
TK-101 at 9 m), S0-C (concurrent receipt and delivery) and S0-B (receipt) as applicable, three
assets or locations per type, onset 900 s, 1800 s observed after the onset, coastal, 25 C,
reference fittings, hydraulic ramp 300 s, with the healthy twin of the same seed (demand process
off).
Assumptions: the signal is the noise-free sampled series of each emitted tag averaged over 60 s
(decision D68); the thresholds are 3 times the noise standard deviation of the tag and 3 times the
healthy-variability standard deviation measured over 20 seeds with the demand process on (the
cross-seed standard deviation of the 60 s mean, averaged over the observed window); a candidate
that violates a gate is recorded as rejected and is not an observation (decision D66). The leak
discharge coefficient only scales the area: Q = Cd A sqrt(2 p / rho) depends on the product, so the
detectable area at another Cd is the area at 0.62 times 0.62 / Cd (a unit test checks the identity).
Severity ranges are those of decisions D60 to D64 and are not adjusted.
Source: ``docs/design_decisions.md`` D60 to D68; ``docs/fault_models.md``.
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

from verum.faults import FaultSet, FaultSpec
from verum.hydraulics import HydraulicModel
from verum.sensors import load_sensor_config
from verum.sensors.adapter import observe_rows
from verum.sim.episode import run_episode
from verum.sim.scenario import load_scenario

ONSET_S, OBSERVED_S, RAMP_S = 900.0, 1800.0, 300.0
DURATION_S = ONSET_S + OBSERVED_S
N_SEV = 8
SEEDS = 20
RESULTS = Path("local/results")
GRID = np.arange(ONSET_S, DURATION_S + 1e-9, 10.0)  # times of the 60 s means
CFG = load_sensor_config()
CONT = [t for t, s in CFG.tags.items() if s.kind == "continuous"]
EVENT = [t for t, s in CFG.tags.items() if s.kind == "event"]
SPAN = {t: CFG.tags[t].range_hi - CFG.tags[t].range_lo for t in CONT}  # type: ignore[operator]
SIGMA = {t: CFG.sigma(CFG.tags[t].noise_class) for t in CONT}


def sev(lo: float, hi: float) -> list[float]:
    return [float(x) for x in np.geomspace(lo, hi, N_SEV)]


# (fault type, variant) -> label, severity coordinate values, builder of the magnitude
LEAK_AREAS = sev(2e-6, 1e-3)
CLOSURE = sev(0.10, 0.85)  # 1 - alpha_stuck of a restriction
HEAD_LOSS = sev(0.02, 0.30)  # 1 - head scale
FRACTION = sev(0.002, 0.05)  # of span (bias) or of span per hour (drift)
STUCK_ALPHA = sev(0.005, 0.02)

ASSETS: dict[str, dict[str, list[str]]] = {
    "leak": {
        "S0-A": ["E-S101a", "E-PA3", "E-D1"],
        "S0-C": ["E-S102a", "E-PA3", "E-D1"],
        "S0-B": ["E002", "E003", "E-R101a"],
    },
    "restriction": {
        "S0-A": ["XV-S101", "XV-PAI", "XV-PAO"],
        "S0-C": ["XV-S102", "XV-PAI", "XV-R101"],
        "S0-B": ["XV-R101", "XV-R102", "XV-R103"],
    },
    "pump": {"S0-A": ["P-101A", "P-101B"], "S0-C": ["P-101A", "P-101B"]},
    "bias": {
        "S0-A": ["FT-201", "PT-202A", "LT-101"],
        "S0-C": ["FT-201", "PT-001", "LT-102"],
        "S0-B": ["FT-001", "PT-001", "LT-101"],
    },
    "misroute_a": {
        "S0-A": ["XV-S102", "XV-S103", "XV-PBI"],
        "S0-C": ["XV-S101", "XV-R102", "XV-PBO"],
        "S0-B": ["XV-R102", "XV-R103"],
    },
    "misroute_b": {
        "S0-A": ["XV-S101", "XV-PAI", "XV-PAO"],
        "S0-C": ["XV-S102", "XV-PAO", "XV-R101"],
        "S0-B": ["XV-R101"],
    },
}
ASSETS["drift"] = ASSETS["bias"]
ASSETS["stuck"] = ASSETS["bias"]
KINDS = ("leak", "restriction", "pump", "bias", "drift", "stuck", "misroute_a", "misroute_b")


def coordinates(kind: str) -> list[float | None]:
    return {
        "leak": LEAK_AREAS, "restriction": CLOSURE, "pump": HEAD_LOSS, "bias": FRACTION,
        "drift": FRACTION, "stuck": [None], "misroute_a": [None], "misroute_b": STUCK_ALPHA,
    }[kind]  # type: ignore[return-value]  # fmt: skip


def make_spec(kind: str, asset: str, coord: float | None, cd: float = 0.62) -> FaultSpec:
    if kind == "leak":
        assert coord is not None
        return FaultSpec("PIPE_LEAK", "orifice", asset, ONSET_S, RAMP_S, coord, 0.5, cd)
    if kind == "restriction":
        assert coord is not None
        return FaultSpec("VALVE_RESTRICTION", "restriction", asset, ONSET_S, RAMP_S, 1.0 - coord)
    if kind == "pump":
        assert coord is not None
        return FaultSpec("PUMP_HEAD_DEGRADATION", "head_scale", asset, ONSET_S, RAMP_S, 1.0 - coord)
    if kind in ("bias", "drift"):
        assert coord is not None
        return FaultSpec("SENSOR_DRIFT", kind, asset, ONSET_S, None, coord)
    if kind == "stuck":
        return FaultSpec("SENSOR_DRIFT", "stuck", asset, ONSET_S, None, 0.0)
    if kind == "misroute_a":
        return FaultSpec("VALVE_MISROUTING", "closed_but_open", asset, ONSET_S, RAMP_S, 1.0)
    assert coord is not None
    return FaultSpec("VALVE_MISROUTING", "open_but_stuck", asset, ONSET_S, RAMP_S, coord)


# --- one episode ----------
def clean_series(directory: Path, hook: Any = None) -> dict[str, np.ndarray]:
    """60 s means of the noise-free sampled series on GRID, and the event rows, by tag."""
    rows = observe_rows(directory, hook=hook, clean=True).observations
    out: dict[str, np.ndarray] = {}
    for tag in CONT:
        r = [
            (x["t_sim_s"], x["value"])
            for x in rows
            if x["tag_id"] == tag and x["value"] is not None
        ]
        t, v = np.array([a for a, _ in r]), np.array([b for _, b in r])
        out[tag] = np.array(
            [
                v[(t > g - 60.0) & (t <= g)].mean() if ((t > g - 60.0) & (t <= g)).any() else np.nan
                for g in GRID
            ]
        )
    for tag in EVENT:  # the event sequence as time, value, time, value, ...
        flat = [v for x in rows if x["tag_id"] == tag for v in (x["t_sim_s"], x["value"])]
        out[tag] = np.array(flat, dtype=float)
    return out


def truth_series(directory: Path) -> dict[str, np.ndarray]:
    """True value of each continuous tag's source quantity on GRID (before the sensor chain)."""
    from verum.sensors.adapter import _nodes, _series
    from verum.truth import read_rows

    hydraulic = read_rows(directory, "hydraulic_state")
    meta = json.loads((directory / "episode.json").read_text(encoding="utf-8"))
    out = {}
    for tag in CONT:
        ref = CFG.tags[tag].ref
        series = _series(hydraulic, ref["record_type"], ref["element_id"])
        nodes = _nodes(series, ref["field"], meta["atmosphere_pa_abs"])
        out[tag] = np.interp(GRID, nodes.t, nodes.x)
    return out


SENSOR_KINDS = ("bias", "drift", "stuck")
Job = tuple[str, str, dict[str, Any] | None, int | None, bool]


def run_case(args: Job) -> dict[str, Any]:
    """Run one episode of the audit; return its truth and clean sampled series or its rejection."""
    scenario_id, label, spec_record, seed_shift, demand = args
    model = HydraulicModel.load()
    scenario = dataclasses.replace(load_scenario(scenario_id), duration_s=DURATION_S)
    if seed_shift is not None:
        scenario = dataclasses.replace(
            scenario, seed=scenario.seed + seed_shift, demand_process=demand
        )
    spec = FaultSpec(**spec_record) if spec_record else None
    faults = FaultSet((spec,)) if spec else None
    out = Path(tempfile.mkdtemp(prefix="audit_"))
    try:
        result = run_episode(scenario_id, out, model, scenario, faults)
        if result.rejected:
            return {"label": label, "rejected": result.outcome.rejection}
        res: dict[str, Any] = {
            "label": label, "rejected": None,
            "series": {k: v.tolist() for k, v in clean_series(result.directory).items()},
            "truth": {k: v.tolist() for k, v in truth_series(result.directory).items()},
            "windows": [w.kind for w in result.outcome.windows],
        }  # fmt: skip
        if label.endswith(":twin"):  # sensor faults act on the twin's truth, in the chain only
            res["sensor_cases"] = sensor_cases(scenario_id, result.directory)
        return res
    finally:
        shutil.rmtree(out, ignore_errors=True)


def sensor_cases(scenario_id: str, directory: Path) -> dict[str, dict[str, list[float]]]:
    """Clean series with each sensor fault applied to the twin's truth (labels as in all_jobs)."""
    out = {}
    for kind in SENSOR_KINDS:
        for asset in ASSETS[kind][scenario_id]:
            for i, coord in enumerate(coordinates(kind)):
                hook = FaultSet((make_spec(kind, asset, coord),)).sensor_hook(SPAN)
                series = clean_series(directory, hook)
                out[f"{kind}|{scenario_id}|{asset}|{i}"] = {t: series[t].tolist() for t in CONT}
    return out


# --- the grid ----------
def baseline() -> None:
    jobs: list[Job] = [
        (sid, f"{sid}:{k}", None, k, True) for sid in ("S0-A", "S0-B", "S0-C") for k in range(SEEDS)
    ]
    twins = [(sid, f"{sid}:twin", None, None, False) for sid in ("S0-A", "S0-B", "S0-C")]
    with Pool(9) as pool:
        res = pool.map(run_case, twins + jobs)
    with open(RESULTS / "fault_audit_baseline.json", "w", encoding="utf-8") as fh:
        json.dump(res, fh)
    print("baseline done", len(res))


def all_jobs() -> list[Job]:
    jobs = []
    for kind in KINDS:
        if kind in SENSOR_KINDS:
            continue
        for sid, assets in ASSETS[kind].items():
            for asset in assets:
                for i, coord in enumerate(coordinates(kind)):
                    spec = make_spec(kind, asset, coord)
                    jobs.append(
                        (sid, f"{kind}|{sid}|{asset}|{i}", dataclasses.asdict(spec), None, False)
                    )
    return jobs


def faults() -> None:
    """All fault runs, or only the kinds named after the command (written to a second file)."""
    only = sys.argv[2:]
    jobs = all_jobs() + [
        (sid, f"{sid}:twin", None, None, False) for sid in ("S0-A", "S0-B", "S0-C")
    ]
    if only:
        jobs = [j for j in jobs if j[1].split("|")[0] in only]
    print(len(jobs), "runs", flush=True)
    with Pool(9) as pool:
        res = []
        for k, r in enumerate(pool.imap_unordered(run_case, jobs, chunksize=1)):
            res.append(r)
            if k % 20 == 0:
                print(k, flush=True)
    name = "fault_audit_runs.json" if not only else f"fault_audit_runs_{'_'.join(only)}.json"
    with open(RESULTS / name, "w", encoding="utf-8") as fh:
        json.dump(res, fh)
    print("faults done", len(res))


if __name__ == "__main__":
    RESULTS.mkdir(parents=True, exist_ok=True)
    {"baseline": baseline, "faults": faults}[sys.argv[1]]()
