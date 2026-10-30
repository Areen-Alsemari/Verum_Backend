"""Single-pipe reservoir-valve cases of the published water-hammer experiments.

Each case builds a transient engine on a reservoir, one pipe and a test-only valve that follows the
authors' closure law, and returns the head at the valve over time. The wave speed is set directly
with 24 reaches at Courant number one, and the friction is the quasi-steady Darcy factor of the
library, not Colebrook. The valve law and the substitution of water properties are described in the
"Experiment cases" section of the verification notes.

See D56.
"""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from scipy.signal import find_peaks

from _transient_cases import edge
from verum.graph import Lineup
from verum.hydraulics import HydraulicModel
from verum.transient import TransientEngine, TransientSpec
from verum.transient.driver import NetworkDef, Probe
from verum.transient.friction import darcy_factor
from verum.transient.interior import c_plus

G = 9.80665
REACHES = 24
VAPOR_PA_WATER = 2339.0
# The stub after the valve only lets the imposed flow leave. Its points sit far below the pipe so
# that the vapor check, which uses the pressure head, never reads the rarefaction behind the valve
# (the real valve discharges to the atmosphere and has no such column). Heads are piezometric, so
# the dynamics do not depend on this elevation.
STUB_Z_M = -1.0e4
DATA = Path(__file__).parent / "data" / "jensen_2018_experiments.json"


def load() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(DATA.read_text(encoding="utf-8"))
    return loaded


def build(model: HydraulicModel, case: dict[str, Any]) -> tuple[TransientEngine, float]:
    """The engine of an experiment and the elevation of the valve (0)."""
    d, length, a = case["D_mm"] / 1000.0, case["L_m"], case["a_m_s"]
    area, u0, rho = math.pi * d**2 / 4, case["u0_m_s"], case["rho"]
    dt = length / (REACHES * a)
    drop = length * math.sin(math.radians(case["slope_deg"]))
    f0 = float(
        darcy_factor(np.array([u0]), np.array([d]), rho, case["mu"], case["roughness_um"] * 1e-6)[0]
    )
    h_up = case["H_res_m"] - u0**2 / (2 * G)
    h_valve = h_up - f0 * length / d * u0**2 / (2 * G)
    q0 = area * u0
    net = NetworkDef(
        edges=(
            edge("P1", "TKR:outlet_nozzle", "XV-T", length, d, -drop, 0.0),
            edge("P2", "XV-T", "TKD:receipt_nozzle", 2.0 * a * dt, d, STUB_Z_M, STUB_Z_M),
        ),
        k={"P1": 0.0, "P2": 0.0},
        pumps=(),
        node_z={},
        initial={"P1": (h_up, h_valve, q0), "P2": (h_valve, h_valve, q0)},
    )
    holder: dict[str, TransientEngine] = {}
    law = _valve_law(holder, q0, h_valve, case["tc_s"], case["m"])
    spec = TransientSpec(
        lineup=Lineup(frozenset({"XV-T"}), frozenset()),
        tank_levels_m={"TKR": case["H_res_m"], "TKD": h_valve + u0**2 / (2 * G)},
        wave_speeds={0: a},
        dt_s=dt,
        flow_schedules={"XV-T": law},
    )
    engine = TransientEngine(model, spec, net)
    engine.pc = dataclasses.replace(
        engine.pc, rho=rho, mu=case["mu"], roughness=case["roughness_um"] * 1e-6
    )
    engine.rho, engine.vapor_pa = rho, VAPOR_PA_WATER
    holder["engine"] = engine
    return engine, 0.0


def _valve_law(
    holder: dict[str, TransientEngine], q0: float, h0: float, tc: float, m: float
) -> Callable[[float], float]:
    """Flow through the valve at time t from the C+ relation of the pipe end (implicit)."""

    def law(t: float) -> float:
        tau = 1.0 - (t / tc) ** m if t < tc else 0.0
        if tau <= 0.0:
            return 0.0
        e = holder["engine"]
        k = e.series_index["XV-T"]
        e_in = e.s_e1[k]
        pt, nb = np.array([e.end_pt[e_in]]), np.array([e.end_nb[e_in]])
        cp = float(c_plus(e.pc, e.h, e.q, pt, nb)[0])
        b = float(e.b_end[e_in])
        cv2 = (q0 * tau) ** 2 / h0
        return float(0.5 * (-cv2 * b + math.sqrt((cv2 * b) ** 2 + 4.0 * cv2 * max(cp, 0.0))))

    return law


def head_at_valve(
    model: HydraulicModel, case: dict[str, Any], duration_s: float
) -> tuple[TransientEngine, np.ndarray, np.ndarray]:
    engine, z_valve = build(model, case)
    rec = engine.run(duration_s, [Probe("v", "P1", 1.0)], stride=1)
    return engine, rec["t"], rec["v.H"] - z_valve


def peaks(t: np.ndarray, h: np.ndarray, h_res: float, surge: float) -> np.ndarray:
    """Indices of the head peaks that rise above the reservoir head by 10 percent of the Joukowsky
    surge, in time order, with a plateau counted once at its middle.
    """
    idx, _ = find_peaks(h, height=h_res + 0.1 * surge, prominence=0.05 * surge)
    return np.asarray(idx)


def frequency_hz(t: np.ndarray, idx: np.ndarray, n: int = 10) -> float:
    """Mean frequency from the first to the n-th peak."""
    return float((n - 1) / (t[idx[n - 1]] - t[idx[0]]))
