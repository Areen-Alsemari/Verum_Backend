"""Receipt set-point steps: inertial head of the rigid-column engine against the transient engine.

The cases are a step down from 600 to 300 m3/h, a start-up from 0 to 600 m3/h, and a step up from
300 to 600 m3/h. The set-point law is first order, so dQ/dt = (Q_set - Q) / tau_c with the cap not
binding. The transient pressure is averaged over a window of 2.0 s to remove the 1.0 s oscillation
of the network response, which the rigid column does not represent.

See D22, D36 and D53.
"""

from __future__ import annotations

import dataclasses
import json
import math
import sys
from typing import Any

import numpy as np

from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.scenario import Scenario, load_scenario
from verum.transient import TransientEngine, TransientSpec
from verum.transient.driver import Probe
from verum.truth import ListSink

SAMPLES = (1.0, 2.0, 4.0)
WINDOW_S = 2.0
TAU_S = 2.0
G = 9.80665
DOWNSTREAM_OF_PT001 = ("E002", "E003", "E-R101a", "E-R101b")


def scenarios() -> dict[str, tuple[Scenario, float, float, float]]:
    """Case name -> (scenario, step time, flow before, set-point after), flows in m3/h."""
    g = load_scenario("S0-G")
    up = dataclasses.replace(
        g,
        duration_s=110.0,
        receipt_flow_m3h=300.0,
        receipt_setpoint_m3h=300.0,
        schedule=[{"t_s": 100.0, "command": "receipt_setpoint", "value_m3h": 600.0}],
    )
    return {
        "step_down_S0-G": (g, 1200.0, 600.0, 300.0),
        "start_up_S0-B": (load_scenario("S0-B"), 0.0, 0.0, 600.0),
        "step_up_300_to_600": (up, 100.0, 300.0, 600.0),
    }


def run_rigid(model: HydraulicModel, scenario: Scenario) -> list[dict[str, Any]]:
    engine = Engine(
        model, load_lineup_table(model.topology), scenario, load_sim_config(), ListSink(), "EP"
    )
    assert engine.run().rejection is None
    sink: Any = engine.sink
    return list(sink.rows["hydraulic_state"])


def lambda_down(model: HydraulicModel, edges: tuple[str, ...]) -> float:
    total = 0.0
    for name in edges:
        e = model.topology.edge(name)
        total += e.length_m / (G * math.pi * e.inner_diameter_m**2 / 4)
    return total


def moc_series(
    model: HydraulicModel, level_m: float, flow: float, to: float, t_end: float
) -> tuple[np.ndarray, np.ndarray]:
    lineup = load_lineup_table(model.topology).mode("RECEIVE_101").lineup
    spec = TransientSpec(
        lineup=lineup,
        tank_levels_m={"TK-101": level_m, "TK-102": 7.0, "TK-103": 5.0},
        fitting_profile="reference_fittings",
        receipt_flow_m3h=flow,
        receipt_setpoint_m3h=flow,
        setpoint_events=((10.0, to),),
    )
    engine = TransientEngine(model, spec)
    rec = engine.run(10.0 + t_end, [Probe("pt", "E002", 0.0)], stride=1)
    z = engine.z[engine.point_index("E002", 0.0)]
    return rec["t"] - 10.0, engine.rho * engine.g * (rec["pt.H"] - z) / 1e5


def oscillation_amplitude(t: np.ndarray, p: np.ndarray) -> dict[str, float]:
    """Largest departure (bar) of the transient pressure from its 2 s running mean, by interval
    after the step.
    """
    mean = np.array([p[(t >= x - WINDOW_S / 2) & (t <= x + WINDOW_S / 2)].mean() for x in t])
    out = {}
    for lo, hi in ((1.0, 2.0), (2.0, 5.0), (5.0, 10.0), (10.0, 20.0), (20.0, 30.0)):
        sel = (t >= lo) & (t < hi)
        out[f"{lo:g}-{hi:g} s"] = float(np.abs(p[sel] - mean[sel]).max())
    return out


def spectrum_peaks(t: np.ndarray, p: np.ndarray, n: int = 4) -> list[tuple[float, float]]:
    """Frequencies (Hz) and periods (s) of the largest peaks after removing a slow trend."""
    grid = np.arange(3.0, t[-1], 0.002)
    y = np.interp(grid, t, p)
    y = y - np.polyval(np.polyfit(grid - 3.0, y, 5), grid - 3.0)
    amp = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    freq = np.fft.rfftfreq(len(y), 0.002)
    idx = [i for i in np.argsort(amp)[::-1] if freq[i] > 0.2][:n]
    return [(round(float(freq[i]), 3), round(float(1.0 / freq[i]), 3)) for i in idx]


def case_table(
    model: HydraulicModel, name: str, spec: tuple[Scenario, float, float, float]
) -> dict:
    scenario, t_step, flow0, to = spec
    rows = run_rigid(model, scenario)
    patm, rho_g = model.patm, model.rho * model.g
    lam, lam_tap = (
        lambda_down(model, DOWNSTREAM_OF_PT001),
        lambda_down(model, DOWNSTREAM_OF_PT001[1:]),
    )
    by: dict[tuple[str, float, str | None], dict[str, Any]] = {}
    kinds = ("edge_state", "node_state", "tank_state")
    for r in rows:
        if r["record_type"] in kinds:
            by[(r["element_id"], r["t_sim_s"], r["side"])] = r["payload"]
    level = by[("TK-101", t_step, "pre_event")]["level_m"]
    out: dict[str, Any] = {
        "level_m": level,
        "lambda_down": lam,
        "lambda_tap": lam_tap,
        "points": {},
    }
    for side in ("pre_event", "post_event"):
        e002, tap = by[("E002", t_step, side)], by[("PIPELINE_RECEIPT_BOUNDARY", t_step, side)]
        out["points"][f"t+0 {side}"] = {
            "flow_m3h": by[("E001", t_step, side)]["flow_m3s"] * 3600.0,
            "pt001_barg": (e002["p_from_pa_abs"] - patm) / 1e5,
            "tap_head_m": tap["hydraulic_head_m"],
            "tap_barg": (tap["pressure_pa_abs"] - patm) / 1e5,
        }
    t, p = moc_series(model, level, flow0, to, 12.0 if name.startswith("step_down") else 7.0)
    for dt in SAMPLES:
        key_t = t_step + dt
        q = by[("E001", key_t, None)]["flow_m3s"] * 3600.0
        qdot = (to - q) / TAU_S / 3600.0
        e002, tap = by[("E002", key_t, None)], by[("PIPELINE_RECEIPT_BOUNDARY", key_t, None)]
        win = (t >= dt - WINDOW_S / 2) & (t <= dt + WINDOW_S / 2)
        out["points"][f"t+{dt:g}"] = {
            "flow_m3h": q,
            "qdot_m3s2": qdot,
            "pt001_barg": (e002["p_from_pa_abs"] - patm) / 1e5,
            "tap_head_m": tap["hydraulic_head_m"],
            "tap_barg": (tap["pressure_pa_abs"] - patm) / 1e5,
            "hand_lambda_qdot_m": lam * abs(qdot),
            "hand_lambda_qdot_bar": lam * abs(qdot) * rho_g / 1e5,
            "moc_window_mean_pt001_barg": float(p[win].mean()),
        }
        pt = out["points"][f"t+{dt:g}"]
        pt["difference_over_dip_percent"] = (
            100.0
            * (pt["moc_window_mean_pt001_barg"] - pt["pt001_barg"])
            / pt["hand_lambda_qdot_bar"]
        )
    if name.startswith("step_down"):
        series = moc_series(model, level, flow0, to, 30.0)
        out["spectrum_hz_s"] = spectrum_peaks(*series)
        out["oscillation_amplitude_bar"] = oscillation_amplitude(*series)
    return out


def main() -> None:
    model = HydraulicModel.load()
    result = {name: case_table(model, name, spec) for name, spec in scenarios().items()}
    with open("local/results/t4_dip.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, default=float)
    print(json.dumps(result, indent=1, default=float))


if __name__ == "__main__":
    sys.exit(main())
