"""Representable severity range of every fault type and eligible asset, with the gate that ends it.

Inputs: the plant model, the fault types of ``verum.faults`` and the lineups of the scenarios.
Outputs: ``local/results/representable_range.json`` and ``representable_range.md``. Run as
``python tools/representable_range.py {run|report}``.
Method: for each (fault type, asset, lineup) the fault is applied at the least severe and at the
most severe end of its range (decisions D60 to D64), onset 600 s, ramp 30 s, observed for 1800 s
after the ramp; if the most severe end is rejected by an engine gate and the least severe end is
not, the largest passing severity is found by bisection (10 halvings, in the logarithm for a leak
area). The gate that rejects, its parameter and its time are recorded. A rejected candidate is
never labelled as healthy (decision D66).
Assumptions: severity runs from healthy to the extreme of the range: leak area up, closure fraction
of a restriction (1 - ceiling) up, head loss fraction (1 - head scale) up, and for misrouting (b)
the stuck opening down; the least severe end is the first point tried and the range is monotone in
severity (a run that passes at a severity also passes at every smaller one; the bisection assumes
this and the end points show whether it holds). Restriction mode does not change the hydraulics
(decision D74), so one mode is run. Sensor faults act only in the sensor chain and have no gate.
Source: ``docs/design_decisions.md`` D60 to D66, D74 to D76; serves the Phase 6b report.
"""

from __future__ import annotations

import dataclasses
import json
import math
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from verum.faults import FaultSet, FaultSpec
from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.scenario import load_scenario
from verum.truth import ListSink

RESULTS = Path("local/results")
ONSET_S, RAMP_S, OBSERVED_S = 600.0, 30.0, 1800.0
END_S = ONSET_S + RAMP_S + OBSERVED_S
HALVINGS = 10

# lineup -> (scenario file, initial mode)
LINEUPS: dict[str, tuple[str, str]] = {
    "DELIVER_101_A": ("S0-A", "DELIVER_101_A"),
    "DELIVER_101_B": ("S0-A", "DELIVER_101_B"),
    "DELIVER_102_A": ("S0-A", "DELIVER_102_A"),
    "DELIVER_103_A": ("S0-A", "DELIVER_103_A"),
    "RECEIVE_101": ("S0-B", "RECEIVE_101"),
    "RECEIVE_102": ("S0-B", "RECEIVE_102"),
    "RECEIVE_103": ("S0-B", "RECEIVE_103"),
    "RECEIVE_101_102": ("S0-B", "RECEIVE_101_102"),
    "RECEIVE_101_DELIVER_102_A": ("S0-C", "RECEIVE_101_DELIVER_102_A"),
}
LEAK_LINEUPS = ("DELIVER_101_A", "RECEIVE_101", "RECEIVE_101_DELIVER_102_A")
RESTRICTION_LINEUP = {
    "XV-R101": "RECEIVE_101", "XV-R102": "RECEIVE_102", "XV-R103": "RECEIVE_103",
    "XV-S101": "DELIVER_101_A", "XV-S102": "DELIVER_102_A", "XV-S103": "DELIVER_103_A",
    "XV-PAI": "DELIVER_101_A", "XV-PAO": "DELIVER_101_A",
    "XV-PBI": "DELIVER_101_B", "XV-PBO": "DELIVER_101_B",
}  # fmt: skip
MISROUTE_A = {
    "DELIVER_101_A": ("XV-S102", "XV-S103", "XV-PBI", "XV-PBO", "XV-R101"),
    "RECEIVE_101": ("XV-R102", "XV-R103", "XV-S101"),
}
RANGES = {  # kind -> (least severe, most severe) coordinate
    "leak": (2.0e-6, 1.0e-3),  # area, m2
    "restriction": (0.10, 0.85),  # closure fraction
    "pump": (0.02, 0.30),  # head loss fraction
    "misroute_b": (0.02, 0.005),  # stuck opening
}
Job = tuple[str, str, str, float | None]


def spec_of(kind: str, asset: str, coordinate: float | None) -> FaultSpec:
    if kind == "leak":
        assert coordinate is not None
        return FaultSpec("PIPE_LEAK", "orifice", asset, ONSET_S, RAMP_S, coordinate, 0.5, 0.62)
    if kind == "restriction":
        assert coordinate is not None
        return FaultSpec(
            "VALVE_RESTRICTION", "restriction", asset, ONSET_S, RAMP_S, 1.0 - coordinate,
            fault_mode="position_visible",
        )  # fmt: skip
    if kind == "pump":
        assert coordinate is not None
        return FaultSpec(
            "PUMP_HEAD_DEGRADATION", "head_scale", asset, ONSET_S, RAMP_S, 1.0 - coordinate
        )
    if kind == "misroute_a":
        return FaultSpec("VALVE_MISROUTING", "closed_but_open", asset, ONSET_S, RAMP_S, 1.0)
    assert coordinate is not None
    return FaultSpec("VALVE_MISROUTING", "open_but_stuck", asset, ONSET_S, RAMP_S, coordinate)


def run_one(job: Job) -> dict[str, Any]:
    kind, asset, lineup, coordinate = job
    model = HydraulicModel.load()
    sid, mode = LINEUPS[lineup]
    scenario = dataclasses.replace(load_scenario(sid), duration_s=END_S, initial_mode=mode)
    engine = Engine(
        model, load_lineup_table(model.topology), scenario, load_sim_config(), ListSink(),
        "EP-RANGE", None, FaultSet((spec_of(kind, asset, coordinate),)),
    )  # fmt: skip
    outcome = engine.run()
    rejection = outcome.rejection
    return {
        "job": list(job),
        "rejection": None if rejection is None else {
            k: rejection.get(k) for k in ("gate", "parameter", "t_sim_s", "value", "limit")
        },
        "windows": [w.kind for w in outcome.windows],
    }  # fmt: skip


def bisect(
    kind: str, asset: str, lineup: str, lo: float, hi: float
) -> tuple[float, dict[str, Any]]:
    """Largest passing coordinate between ``lo`` (passes) and ``hi`` (rejected)."""
    last = run_one((kind, asset, lineup, hi))
    for _ in range(HALVINGS):
        mid = math.sqrt(lo * hi) if kind == "leak" else 0.5 * (lo + hi)
        r = run_one((kind, asset, lineup, mid))
        if r["rejection"] is None:
            lo = mid
        else:
            hi, last = mid, r
    return lo, last["rejection"]


def one_case(case: tuple[str, str, str]) -> dict[str, Any]:
    kind, asset, lineup = case
    if kind == "misroute_a":
        r = run_one((kind, asset, lineup, None))
        return {"case": list(case), "least": r, "most": r, "largest": None, "limit_gate": None}
    least_c, most_c = RANGES[kind]
    least, most = run_one((kind, asset, lineup, least_c)), run_one((kind, asset, lineup, most_c))
    out: dict[str, Any] = {"case": list(case), "least": least, "most": most}
    if least["rejection"] is None and most["rejection"] is not None:
        out["largest"], out["limit_gate"] = bisect(kind, asset, lineup, least_c, most_c)
    else:
        out["largest"], out["limit_gate"] = (most_c if most["rejection"] is None else None), None
    return out


def cases() -> list[tuple[str, str, str]]:
    topology = HydraulicModel.load().topology
    out: list[tuple[str, str, str]] = []
    out += [("leak", e.edge_id, ln) for e in topology.edges for ln in LEAK_LINEUPS]
    out += [("restriction", v, ln) for v, ln in RESTRICTION_LINEUP.items()]
    out += [("pump", "P-101A", "DELIVER_101_A"), ("pump", "P-101B", "DELIVER_101_B")]
    out += [("misroute_a", v, ln) for ln, vs in MISROUTE_A.items() for v in vs]
    out += [("misroute_b", v, "RECEIVE_101_102") for v in ("XV-R101", "XV-R102")]
    return out


def run() -> None:
    todo = cases()
    print(len(todo), "cases", flush=True)
    with Pool(9) as pool:
        res = []
        for k, r in enumerate(pool.imap_unordered(one_case, todo, chunksize=1)):
            res.append(r)
            if k % 20 == 0:
                print(k, flush=True)
    (RESULTS / "representable_range.json").write_text(json.dumps(res), encoding="utf-8")


def label(rej: dict[str, Any] | None) -> str:
    if rej is None:
        return "passes"
    return f"{rej['gate']} {rej['parameter']}"


def report() -> None:
    res = json.loads((RESULTS / "representable_range.json").read_text(encoding="utf-8"))
    units = {"leak": "m2", "restriction": "closure fraction", "pump": "head loss fraction",
             "misroute_a": "forced open", "misroute_b": "stuck opening"}  # fmt: skip
    lines = ["# Representable severity range", "",
             f"Onset {ONSET_S:g} s, ramp {RAMP_S:g} s, {OBSERVED_S:g} s observed; ranges "
             f"{RANGES}.", ""]  # fmt: skip
    for kind in ("leak", "restriction", "pump", "misroute_a", "misroute_b"):
        rows = sorted((r for r in res if r["case"][0] == kind), key=lambda r: r["case"])
        lines += [f"## {kind} ({units[kind]})", "",
                  "| asset | lineup | least severe | most severe | largest passing | gate |",
                  "| --- | --- | --- | --- | --- | --- |"]  # fmt: skip
        for r in rows:
            largest = "-" if r["largest"] is None else f"{r['largest']:.4g}"
            gate = label(r["limit_gate"]) if r["limit_gate"] else "-"
            lines.append(
                f"| {r['case'][1]} | {r['case'][2]} | {label(r['least']['rejection'])} | "
                f"{label(r['most']['rejection'])} | {largest} | {gate} |"
            )
        lines.append("")
    (RESULTS / "representable_range.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    {"run": run, "report": report}[sys.argv[1]]()
