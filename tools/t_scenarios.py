"""Transient scenarios T1 to T3 and the invalid-window location: transient against rigid-column
engine.

Both engines start from the same lineup, levels and receipt flow, and the rigid-column engine runs a
short scenario with the same valve commands. Pressures are gauge, in bar, at the start of E002 (the
PT-001 tap), at its end, and at the receipt header. The transient engine has no cavitation model, so
values are quoted only up to the first invalid window and the rigid-column value is read at the same
instant.

See D22, D45, D53 and D55.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import sys
from collections import defaultdict
from typing import Any

import numpy as np

from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.params import ParamValue
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.scenario import load_scenario
from verum.transient import TransientEngine, TransientSpec
from verum.transient import grid as gr
from verum.transient.driver import Probe, ValveEvent
from verum.truth import ListSink

M = HydraulicModel.load()
TABLE = load_lineup_table(M.topology)
SPEEDS = gr.load_wave_speeds(M.directory)
EDGES = {e.edge_id: e for e in M.topology.edges}
PATM = M.patm
RECEIPT_PATH = ("E001", "E002", "E003", "E-R101a", "E-R101b")
# Valves along the receipt path and the edge after which each sits.
PATH_VALVES = {"XV-R000": "E002", "XV-R101": "E-R101a"}
Series = dict[str, tuple[np.ndarray, ...]]


def _dn(edge: Any) -> int:
    return {0.20274: 200, 0.25446: 250, 0.30318: 300}[round(edge.inner_diameter_m, 5)]


def round_trip(path: tuple[str, ...]) -> float:
    return 2.0 * sum(EDGES[x].length_m / SPEEDS[_dn(EDGES[x])] for x in path)


def rigid(
    base: str,
    schedule: list[dict[str, Any]],
    duration: float,
    stroke_r000: float | None = None,
    stroke_other: float | None = None,
    cap_pa: float | None = None,
    **scenario_fields: Any,
) -> tuple[Series, dict[str, Any] | None, Any]:
    """Run the rigid-column engine on a short scenario; return the edge series by edge."""
    cfg0 = load_sim_config()
    params = dict(cfg0.parameters)
    if stroke_r000 is not None:
        params["stroke_time_xv_r000_s"] = ParamValue.selected(stroke_r000, "s", "DESIGN", "STUDY")
    if stroke_other is not None:
        params["stroke_time_other_motorized_s"] = ParamValue.selected(
            stroke_other, "s", "DESIGN", "STUDY"
        )
    cfg = dataclasses.replace(cfg0, parameters=params)
    scenario = dataclasses.replace(
        load_scenario(base),
        duration_s=duration,
        healthy_envelope=False,
        schedule=schedule,
        **scenario_fields,
    )
    model = M
    if cap_pa is not None:
        cm = dataclasses.replace(
            M.config,
            parameters={
                **M.config.parameters,
                "receipt_pressure_cap_pa_gauge": ParamValue.selected(
                    cap_pa, "Pa", "DESIGN", "STUDY"
                ),
            },
        )
        model = copy.copy(M)
        model.config = cm
    engine = Engine(model, TABLE, scenario, cfg, ListSink(), "EP")
    outcome = engine.run()
    sink: Any = engine.sink
    rows: dict[str, tuple[list[float], ...]] = defaultdict(lambda: ([], [], [], []))
    for r in sink.rows["hydraulic_state"]:
        if r["record_type"] != "edge_state":
            continue
        p = r["payload"]
        t, q, pf, pt = rows[r["element_id"]]
        t.append(r["t_sim_s"])
        q.append(p["flow_m3s"])
        pf.append(np.nan if p["p_from_pa_abs"] is None else p["p_from_pa_abs"] - PATM)
        pt.append(np.nan if p["p_to_pa_abs"] is None else p["p_to_pa_abs"] - PATM)
    series = {k: tuple(np.array(v) for v in vals) for k, vals in rows.items()}
    return series, outcome.rejection, outcome


def moc(
    mode: str, levels: dict[str, float], t_end: float, probes: list[Probe], **spec_kw: Any
) -> tuple[TransientEngine, dict[str, np.ndarray]]:
    lineup = TABLE.mode(mode).lineup
    spec = TransientSpec(
        lineup=lineup, tank_levels_m=levels, fitting_profile="reference_fittings", **spec_kw
    )
    engine = TransientEngine(M, spec)
    return engine, engine.run(t_end, probes, stride=1)


def peak(t: np.ndarray, y: np.ndarray, lo: float, hi: float) -> tuple[float, float]:
    sel = np.isfinite(y) & (t >= lo) & (t <= hi)
    i = int(np.argmax(np.where(sel, y, -np.inf)))
    return float(y[i]), float(t[i])


def trough(t: np.ndarray, y: np.ndarray, lo: float, hi: float) -> tuple[float, float]:
    sel = np.isfinite(y) & (t >= lo) & (t <= hi)
    i = int(np.argmin(np.where(sel, y, np.inf)))
    return float(y[i]), float(t[i])


def moc_pressures(
    engine: TransientEngine, rec: dict[str, np.ndarray], taps: list[tuple[str, str, float]]
) -> dict[str, np.ndarray]:
    """Gauge pressure series (bar) at the probes from the piezometric heads."""
    out = {}
    for name, edge, frac in taps:
        z = engine.z[engine.point_index(edge, frac)]
        out[name] = engine.rho * engine.g * (rec[f"{name}.H"] - z) / 1e5
    return out


def valid_limit(engine: TransientEngine, t_end: float) -> float:
    """Start of the first phase_invalid window, or the end of the run if there is none."""
    return engine.phase.windows[0][0] if engine.phase.windows else t_end


# --- T1 and T2 ----------
def t_receipt_closure(
    stroke_r000: float,
    t0: float = 10.0,
    with_r101: bool = True,
    stroke_other: float = 30.0,
) -> dict[str, Any]:
    """Close XV-R000 (and XV-R101) while receiving 600 m3/h into TK-101, cap 10 barg."""
    levels = {"TK-101": 12.98, "TK-102": 7.0, "TK-103": 5.0}
    duration = t0 + max(stroke_r000, stroke_other if with_r101 else 0.0) + 6.0
    valves = ["XV-R000"] + (["XV-R101"] if with_r101 else [])
    events = [ValveEvent("XV-R000", t0, 0.0, stroke_r000)]
    if with_r101:
        events.append(ValveEvent("XV-R101", t0, 0.0, stroke_other))
    taps = [("pt001", "E002", 0.0), ("tap", "E002", 1.0), ("hdr", "E003", 1.0)]
    probes = [Probe(n, ed, f) for n, ed, f in taps] + [Probe("q", "E001", 0.5)]
    engine, rec = moc(
        "RECEIVE_101", levels, duration, probes, receipt_flow_m3h=600.0,
        receipt_setpoint_m3h=600.0, valve_events=tuple(events),
    )  # fmt: skip
    t, limit = rec["t"], valid_limit(engine, duration)
    p = moc_pressures(engine, rec, taps)
    res: dict[str, Any] = {
        "stroke_s": stroke_r000,
        "ratio": stroke_r000 / round_trip(RECEIPT_PATH),
        "first_phase_window_s": limit if engine.phase.windows else None,
        "n_windows": len(engine.phase.windows),
        "t_close_s": t0 + 0.999 * stroke_r000,
        "moc_valid": {},
        "moc_at_closure": {},
        "rigid_valid": {},
        "rigid_at_closure": {},
    }
    for name, _, _ in taps:
        res["moc_valid"][name] = peak(t, p[name], t0, limit) + trough(t, p[name], t0, limit)
        res["moc_at_closure"][name] = peak(t, p[name], t0, res["t_close_s"] + 0.02)
    schedule = [{"t_s": t0, "command": "close_valves", "valves": valves}]
    series, rejection, _ = rigid(
        "S0-B", schedule, duration, stroke_r000=stroke_r000, stroke_other=stroke_other,
        receipt_flow_m3h=600.0, receipt_setpoint_m3h=600.0, tank_levels_m=levels,
        initial_mode="RECEIVE_101",
    )  # fmt: skip
    res["rigid_rejection"] = rejection
    for name, edge, col in (("pt001", "E002", 2), ("tap", "E002", 3), ("hdr", "E003", 3)):
        tt, y = series[edge][0], series[edge][col] / 1e5
        res["rigid_valid"][name] = peak(tt, y, t0, limit)
        res["rigid_at_closure"][name] = peak(tt, y, t0, res["t_close_s"] + 0.02)
    tq, qq = series["E001"][0], series["E001"][1] * 3600.0
    grid = np.arange(t0, limit, 0.05)
    res["flow_max_abs_diff_m3h"] = float(
        np.abs(np.interp(grid, t, rec["q.Q"] * 3600.0) - np.interp(grid, tq, qq)).max()
    )
    return res


def run_t1_t2() -> dict[str, Any]:
    out: dict[str, Any] = {"T1": t_receipt_closure(10.0), "T2": []}
    for stroke in (2.0, 3.6, 7.2, 10.0, 20.0, 30.0):
        out["T2"].append(t_receipt_closure(stroke, with_r101=False))
    return out


# --- phase_invalid location ----------
def path_coordinate(edge_id: str, offset_m: float) -> float | None:
    """Distance (m) along the receipt path from the start of E001, or None off the path."""
    if edge_id not in RECEIPT_PATH:
        return None
    before = 0.0
    for name in RECEIPT_PATH:
        if name == edge_id:
            return before + offset_m
        before += EDGES[name].length_m
    return None


def valve_coordinate(valve: str) -> float:
    return path_coordinate(PATH_VALVES[valve], EDGES[PATH_VALVES[valve]].length_m) or 0.0


def first_vapor_point(engine: TransientEngine, t_end: float) -> dict[str, Any] | None:
    """Step the engine; at the first step with a point at or below the vapor pressure, say where."""
    while engine.t < t_end - 1e-9:
        engine.step()
        p_abs = engine.rho * engine.g * (engine.h - engine.z) + engine.model.patm
        if np.any(p_abs <= engine.vapor_pa):
            return describe_point(engine, p_abs)
    return None


def describe_point(engine: TransientEngine, p_abs: np.ndarray) -> dict[str, Any]:
    idx = int(np.argmin(p_abs))
    ei = int(engine.edge_of_point[idx])
    edge = engine.edges[ei]
    reach = engine.grid[ei].reach_length_m
    offset = (idx - int(engine.first[ei])) * reach
    s = path_coordinate(edge.edge_id, offset)
    out: dict[str, Any] = {
        "t_s": engine.t,
        "edge": edge.edge_id,
        "offset_from_edge_start_m": offset,
        "pressure_bar_abs": float(p_abs[idx] / 1e5),
        "vapor_pressure_bar_abs": float(engine.vapor_pa / 1e5),
        "points_at_or_below": int(np.sum(p_abs <= engine.vapor_pa)),
        "edges_with_points_below": sorted(
            {
                engine.edges[int(engine.edge_of_point[i])].edge_id
                for i in np.nonzero(p_abs <= engine.vapor_pa)[0]
            }
        ),
    }
    if s is not None:
        out["distance_from_valve_m"] = {v: s - valve_coordinate(v) for v in PATH_VALVES}
        # A point at the start of the edge after a valve is on its downstream face although its
        # coordinate equals the valve coordinate, so the side comes from the edge order.
        out["side_of_valve"] = {
            v: "downstream"
            if RECEIPT_PATH.index(edge.edge_id) > RECEIPT_PATH.index(PATH_VALVES[v])
            else "upstream"
            for v in PATH_VALVES
        }
    return out


def locate(stroke_r000: float, with_r101: bool, t0: float = 10.0) -> dict[str, Any]:
    levels = {"TK-101": 12.98, "TK-102": 7.0, "TK-103": 5.0}
    events = [ValveEvent("XV-R000", t0, 0.0, stroke_r000)]
    if with_r101:
        events.append(ValveEvent("XV-R101", t0, 0.0, 30.0))
    spec = TransientSpec(
        lineup=TABLE.mode("RECEIVE_101").lineup, tank_levels_m=levels,
        fitting_profile="reference_fittings", receipt_flow_m3h=600.0,
        receipt_setpoint_m3h=600.0, valve_events=tuple(events),
    )  # fmt: skip
    engine = TransientEngine(M, spec)
    found = first_vapor_point(engine, t0 + max(stroke_r000, 30.0 if with_r101 else 0.0) + 2.0)
    res: dict[str, Any] = {"stroke_s": stroke_r000, "with_xv_r101": with_r101, "first": found}
    if found is not None:
        res["seconds_after_command"] = found["t_s"] - t0
        res["fraction_of_xv_r000_stroke"] = (found["t_s"] - t0) / stroke_r000
        res["alpha_xv_r000"] = engine.alpha_at("XV-R000", found["t_s"])
    return res


# --- T3 ----------
def t_delivery_valve(stroke: float, t0: float = 10.0) -> dict[str, Any]:
    """Close XV-PAO over ``stroke`` seconds on a running delivery (TK-101, pump A)."""
    levels = {"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0}
    taps = [("disc", "E-PA3", 1.0), ("suct", "E-PA1", 0.0)]
    duration = t0 + stroke + 4.0
    probes = [Probe(n, ed, f) for n, ed, f in taps] + [Probe("q", "E-PA4", 0.5)]
    engine, rec = moc(
        "DELIVER_101_A", levels, duration, probes,
        valve_events=(ValveEvent("XV-PAO", t0, 0.0, stroke),),
    )  # fmt: skip
    t, limit = rec["t"], valid_limit(engine, duration)
    p = moc_pressures(engine, rec, taps)
    res: dict[str, Any] = {
        "stroke_s": stroke, "n_windows": len(engine.phase.windows),
        "first_phase_window_s": limit if engine.phase.windows else None, "moc": {}, "rigid": {},
    }  # fmt: skip
    path = ("E-SH", "E-PA0", "E-PA1", "E-PA2", "E-PA3", "E-PA4")
    res["ratio_pump_branch"] = stroke / round_trip(("E-S101a", "E-S101b") + path)
    schedule = [{"t_s": t0, "command": "close_valves", "valves": ["XV-PAO"]}]
    series, rejection, _ = rigid(
        "S0-A", schedule, duration, stroke_other=stroke, tank_levels_m=levels
    )
    res["rigid_rejection"] = rejection
    t_lim = min(limit, rejection["t_sim_s"] - 0.2 if rejection else duration)
    res["compare_until_s"] = t_lim
    for name, edge, col in (("disc", "E-PA3", 3), ("suct", "E-PA1", 2)):
        tt, y = series[edge][0], series[edge][col] / 1e5
        res["rigid"][name] = peak(tt, y, t0, t_lim) + trough(tt, y, t0, t_lim)
        res["moc"][name] = peak(t, p[name], t0, t_lim) + trough(t, p[name], t0, t_lim)
    tq, qq = series["E-PA4"][0], series["E-PA4"][1] * 3600.0
    grid = np.arange(t0, t_lim, 0.05)
    res["flow_max_abs_diff_m3h"] = float(
        np.abs(np.interp(grid, t, rec["q.Q"] * 3600.0) - np.interp(grid, tq, qq)).max()
    )
    return res


def t_pump_stop(delay: float, t0: float = 10.0) -> dict[str, Any]:
    levels = {"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0}
    taps = [("disc", "E-PA2", 1.0), ("suct", "E-PA1", 0.0)]
    probes = [Probe(n, ed, f) for n, ed, f in taps] + [Probe("q", "E-PA4", 0.5)]
    engine, rec = moc(
        "DELIVER_101_A", levels, t0 + 12.0, probes,
        pump_stops=((t0, "P-101A"),), check_valve_delay_s=delay,
    )  # fmt: skip
    t, limit = rec["t"], valid_limit(engine, t0 + 12.0)
    p = moc_pressures(engine, rec, taps)
    cv = engine.checks["CV-PA"]
    res: dict[str, Any] = {
        "delay_s": delay, "closed_at_s": cv.closed_at_s,
        "reverse_volume_m3": cv.reverse_volume_m3, "n_windows": len(engine.phase.windows),
        "first_phase_window_s": limit if engine.phase.windows else None, "moc": {},
    }  # fmt: skip
    for name, _, _ in taps:
        res["moc"][name] = peak(t, p[name], t0, limit) + trough(t, p[name], t0, limit)
    res["q_min_m3h"] = float((rec["q.Q"] * 3600.0).min())
    return res


def main(which: str) -> None:
    if which == "t12":
        out: Any = run_t1_t2()
        path = "local/results/t12.json"
    elif which == "t3":
        out = {
            "T3_valve": [t_delivery_valve(30.0), t_delivery_valve(10.0)],
            "T3_pump_stop": [t_pump_stop(d) for d in (0.05, 0.3, 1.0)],
        }
        path = "local/results/t3.json"
    else:
        out = {"T1": locate(10.0, True)}
        out["T2"] = [locate(s, False) for s in (7.2, 10.0, 30.0)]
        path = "local/results/phase_location.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print("wrote", path)


if __name__ == "__main__":
    main(sys.argv[1])
