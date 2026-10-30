"""The sensitivity sweeps of the rigid-column model as one study.

Each sweep changes one configuration parameter of a shipped scenario: the set-point and valve-stroke
window factors, the flow fraction below which a stroke is not judged, the demand process, the
wave-speed restraint and bulk modulus, and the loss multiplier, meter K, pump steepness and NPSH3
coefficient. The transient runs use the emergency-isolation scenario, and the pump-curve sweep keeps
the duty point by recalibrating the boundary coefficient. A sweep point outside the pump curve is
recorded as an error and not dropped. Pick a sweep by name on the command line.

See D42.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import sys
import time
from multiprocessing import Pool
from typing import Any

import numpy as np
import t_scenarios as T
from scipy.optimize import brentq

from verum.graph import Lineup
from verum.hydraulics import (
    DeliveryBoundary,
    HydraulicModel,
    PumpOutsideCurve,
    SteadyInputs,
    load_boundary_law_coefficient,
)
from verum.hydraulics.config import FittingProfile, load_fitting_profile
from verum.lineups import load_lineup_table
from verum.params import ParamValue
from verum.sim.config import SimConfig, load_sim_config
from verum.sim.engine import Engine
from verum.sim.scenario import load_scenario
from verum.transient import grid as gr
from verum.transient.driver import Probe, ValveEvent
from verum.truth import ListSink, NullSink

SCENARIOS = ["S0-A", "S0-A-inland", "S0-B", "S0-C", "S0-F", "S0-G", "S0u-D", "S0u-E"]
STROKE_FACTOR = "wave_criterion_factor_valve_stroke"


def _cfg(**params: float) -> SimConfig:
    c0 = load_sim_config()
    chosen = {k: ParamValue.selected(v, "1", "DESIGN", "D42-SWEEP") for k, v in params.items()}
    return dataclasses.replace(c0, parameters={**c0.parameters, **chosen})


def _run(args: tuple[str, dict[str, float], bool]) -> dict[str, Any]:
    scenario_id, params, want_rows = args
    model = HydraulicModel.load()
    sink = ListSink() if want_rows else NullSink()
    engine = Engine(
        model,
        load_lineup_table(model.topology),
        load_scenario(scenario_id),
        _cfg(**params),
        sink,
        "EP",
    )
    start = time.time()
    out = engine.run()
    res: dict[str, Any] = {
        "scenario": scenario_id,
        "params": params,
        "wall_s": time.time() - start,
        "rejection": out.rejection,
        "windows": [(w.kind, w.element_id, w.ratio) for w in out.windows],
    }
    if want_rows and isinstance(sink, ListSink):
        res.update(_delivery_summary(sink))
    return res


def _delivery_summary(sink: ListSink) -> dict[str, Any]:
    flows, margin = [], []
    for r in sink.rows["hydraulic_state"]:
        if r["side"] is not None:
            continue
        if r["record_type"] == "edge_state" and r["element_id"] == "E-D1":
            flows.append(r["payload"]["flow_m3s"] * 3600.0)
        if r["record_type"] == "pump_state" and r["payload"].get("NPSH_margin_ratio") is not None:
            margin.append(r["payload"]["NPSH_margin_ratio"])
    f = np.array(flows)
    return {
        "ft201_like_flow_m3h": {
            "mean": float(f.mean()),
            "std": float(f.std()),
            "min": float(f.min()),
            "max": float(f.max()),
        },
        "npsh_margin_min": float(min(margin)) if margin else None,
    }


def _sweep(name: str, factor_name: str, values: tuple[float, ...]) -> None:
    jobs = [(s, {factor_name: v}, False) for s in SCENARIOS for v in values]
    with Pool(4) as pool:
        res = pool.map(_run, jobs)
    with open(f"local/results/{name}.json", "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, default=str)


def d22() -> None:
    _sweep("d42_d22", "wave_criterion_factor", (5.0, 10.0, 20.0))


def d53() -> None:
    _sweep("d42_d53", STROKE_FACTOR, (10.0, 20.0, 25.0, 30.0, 50.0, 55.0))


def d58() -> None:
    _sweep("d42_d58", "stroke_window_min_flow_fraction", (0.05, 0.1, 0.2))


def d23() -> None:
    jobs = [
        ("S0-F", {"demand_sigma_log": s, "demand_correlation_time_s": c}, True)
        for s in (0.05, 0.1, 0.2)
        for c in (900.0, 1800.0, 3600.0)
    ]
    with Pool(4) as pool:
        res = pool.map(_run, jobs)
    with open("local/results/d42_d23.json", "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, default=str)


def _t1_peak(model: HydraulicModel, **spec_kw: Any) -> dict[str, Any]:
    """Valid-interval and closure-instant pressure peaks (barg) at the PT-001 tap, ESD closure."""
    t0 = 10.0
    levels = {"TK-101": 12.98, "TK-102": 7.0, "TK-103": 5.0}
    events = (ValveEvent("XV-R000", t0, 0.0, 10.0), ValveEvent("XV-R101", t0, 0.0, 30.0))
    saved = T.M
    T.M = model
    try:
        engine, rec = T.moc(
            "RECEIVE_101",
            levels,
            26.0,
            [Probe("pt001", "E002", 0.0)],
            receipt_flow_m3h=600.0,
            receipt_setpoint_m3h=600.0,
            valve_events=events,
            **spec_kw,
        )
    finally:
        T.M = saved
    t = rec["t"]
    p = engine.rho * engine.g * (rec["pt001.H"] - engine.z[engine.point_index("E002", 0.0)]) / 1e5
    limit = T.valid_limit(engine, 26.0)
    sel = (t >= t0) & (t <= 20.02)
    i = int(np.argmax(np.where(sel, p, -np.inf)))
    return {
        "peak_at_closure_barg": float(p[i]),
        "t_peak_s": float(t[i]),
        "valid_peak_barg": T.peak(t, p, t0, limit)[0],
        "first_phase_window_s": limit if engine.phase.windows else None,
        "round_trip_s": T.round_trip(T.RECEIPT_PATH) if "wave_speeds" not in spec_kw else None,
    }


def wave() -> None:
    m = HydraulicModel.load()
    base = gr.load_wave_speeds(m.directory)
    out = []
    for psi, bulk in (
        (1.0, 1.0e9),
        (0.8, 1.0e9),
        (1.0, 0.8e9),
        (1.0, 1.2e9),
        (0.8, 0.8e9),
        (0.8, 1.2e9),
    ):
        speeds = gr.scaled_speeds(base, psi, bulk, m.rho)
        r = _t1_peak(m, wave_speeds=speeds)
        trip = 2.0 * sum(T.EDGES[x].length_m / speeds[T._dn(T.EDGES[x])] for x in T.RECEIPT_PATH)
        r.update(
            psi=psi,
            bulk_pa=bulk,
            speeds={k: round(v, 1) for k, v in speeds.items()},
            round_trip_s=trip,
        )
        out.append(r)
        print(r, flush=True)
    with open("local/results/d42_wave.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)


def _steady(
    model: HydraulicModel,
    c: float,
    tank: str = "TK-101",
    level: float = 9.0,
    npsh3: float | None = None,
    mult: float = 1.0,
) -> dict[str, Any]:
    lineup = Lineup.of({f"XV-S{tank[3:]}", "XV-PAI", "XV-PAO"}, {"P-101A"})
    try:
        r = model.solve(
            SteadyInputs(
                lineup,
                {tank: level},
                "RVP_9_0",
                25.0,
                fitting_profile="reference_fittings",
                k_multiplier=mult,
                delivery=DeliveryBoundary(law_coefficient_m=c),
                npsh3_coefficient_m=npsh3,
            )
        )
    except PumpOutsideCurve as exc:  # the pump domain rule Q/s <= 350 m3/h
        return {"error": str(exc)}
    assert r.pump is not None
    return {
        "flow_m3h": r.pump.flow_m3h,
        "head_m": r.pump.head_rise_m,
        "npsh_margin_ratio": r.phase.margin_ratio,
    }


def _with_params(model: HydraulicModel, **kw: float) -> HydraulicModel:
    changed = copy.copy(model)
    chosen = {k: ParamValue.selected(v, "m", "DESIGN", "D50-SWEEP") for k, v in kw.items()}
    changed.config = dataclasses.replace(
        model.config, parameters={**model.config.parameters, **chosen}
    )
    return changed


def _k_multiplier(m: HydraulicModel, c0: float) -> list[dict[str, Any]]:
    rows = []
    for mult in (0.5, 1.0, 2.0, 3.0):
        r: dict[str, Any] = {"mult": mult}
        for level in (9.0, 1.8):  # the boundary coefficient stays at the profile value
            r[f"tk101_{level}"] = _steady(m, c0, level=level, mult=mult)
            if "error" not in r[f"tk101_{level}"]:
                r[f"tk101_{level}"]["margin"] = r[f"tk101_{level}"]["npsh_margin_ratio"]
        r["esd"] = _t1_peak(m, k_multiplier=mult)
        rows.append(r)
        print(r, flush=True)
    return rows


def _meter_k(m: HydraulicModel, c0: float) -> list[dict[str, Any]]:
    base = load_fitting_profile("reference_fittings", 1.0, m.directory)
    rows = []
    for mk in (0.5, 1.0, 2.0, 4.0):
        changed = copy.copy(m)
        coefficients = {
            **base.coefficients,
            "meter": ParamValue.selected(mk, "1", "DESIGN", "D50-SWEEP"),
        }
        changed._profiles = {
            ("reference_fittings", 1.0): FittingProfile("reference_fittings", coefficients, 1.0)
        }
        r = {
            "meter_k": mk,
            "tk101_9": _steady(changed, c0, level=9.0),
            "tk101_1.8": _steady(changed, c0, level=1.8),
            "esd": _t1_peak(changed),
        }
        rows.append(r)
        print(r, flush=True)
    return rows


def _pump_steepness(m: HydraulicModel) -> list[dict[str, Any]]:
    lineup = Lineup.of({"XV-S102", "XV-PAI", "XV-PAO"}, {"P-101A"})
    rows = []
    for k in (8.0, 12.0, 16.0):
        changed = _with_params(m, pump_shutoff_head_m=42.0 + k, pump_curve_coefficient_m=k)

        def flow(c: float, model: HydraulicModel = changed) -> float:
            try:
                point = model.solve(
                    SteadyInputs(
                        lineup,
                        {"TK-102": 7.0},
                        "RVP_9_0",
                        25.0,
                        fitting_profile="reference_fittings",
                        delivery=DeliveryBoundary(law_coefficient_m=c),
                    )
                ).pump
            except PumpOutsideCurve:
                return 1000.0
            assert point is not None
            return point.flow_m3h

        c = brentq(lambda x: flow(x) - 300.0, 0.2, 40.0, xtol=1e-10)
        r = {
            "k_m": k,
            "shutoff_head_m": 42.0 + k,
            "shutoff_ratio": (42.0 + k) / 42.0,
            "c_recalibrated_m": c,
            "tk101_9": _steady(changed, c, level=9.0),
            "tk101_1.8": _steady(changed, c, level=1.8),
        }
        rows.append(r)
        print(r, flush=True)
    return rows


def d50() -> None:
    m = HydraulicModel.load()
    c0 = float(load_boundary_law_coefficient("reference_fittings").value)
    out: dict[str, Any] = {"c0": c0}
    out["k_multiplier"] = _k_multiplier(m, c0)
    out["meter_k"] = _meter_k(m, c0)
    out["pump_steepness"] = _pump_steepness(m)
    out["npsh3"] = [
        {
            "npsh3_m": n3,
            "tk101_9": _steady(m, c0, level=9.0, npsh3=n3),
            "tk101_1.8": _steady(m, c0, level=1.8, npsh3=n3),
        }
        for n3 in (2.5, 4.0, 6.0)
    ]
    with open("local/results/d42_d50.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)


SWEEPS = {"d22": d22, "d53": d53, "d58": d58, "d23": d23, "wave": wave, "d50": d50}

if __name__ == "__main__":
    SWEEPS[sys.argv[1]]()
    print("done")
