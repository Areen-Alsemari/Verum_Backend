"""Rigid-column flow dynamics of the receipt and delivery paths, integrated implicitly.

The flow of a path obeys dQ/dt = (H_drive - H_loss(Q)) / I with the inertance I = sum L_i / (g A_i).
On receipt the drive head is capped, and on delivery it is the tank head plus the pump head less the
reservoir head and the boundary law. The system is stiff when a valve nearly closes, so it is
integrated with Radau IIA. The volumes that have passed are states of the same system, so the ledger
closes by construction. Leaks are carried as frozen flows on each edge.

See D22, D60 and D73.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp

from verum.hydraulics.errors import ConvergenceError
from verum.hydraulics.pump import FixedSpeedPump
from verum.sim.path import LeakLayout, LumpedPath
from verum.sim.valves import Valve


@dataclass(frozen=True)
class ReceiptColumn:
    path: LumpedPath
    tank: str
    head_cap_m: float
    level_m: float
    area_m2: float
    tau_c_s: float
    setpoint_m3s: float
    layout: LeakLayout | None = None
    setpoint_fn: Callable[[float], float] | None = None  # profile v2: set-point in m3/s at t
    level_from_net_volume: Callable[[float], float] | None = None


@dataclass(frozen=True)
class DeliveryColumn:
    path: LumpedPath
    tank: str
    pump: FixedSpeedPump
    reservoir_head_m: float
    law_c_m: float
    level_m: float
    area_m2: float
    q_ref_m3h: float
    demand: Callable[[float], float]
    layout: LeakLayout | None = None
    level_from_net_volume: Callable[[float], float] | None = None


@dataclass(frozen=True)
class Advance:
    t0: float
    t1: float
    y1: tuple[float, float, float, float]
    qdot_r: float
    qdot_d: float
    dense: Callable[[float], np.ndarray]


Rhs = Callable[[float, np.ndarray], list[float]]


def _alphas(valves: Mapping[str, Valve], names: tuple[str, ...], t: float) -> dict[str, float]:
    return {v: valves[v].alpha(t) for v in names}


def make_rhs(
    receipt: ReceiptColumn | None, delivery: DeliveryColumn | None, valves: Mapping[str, Valve]
) -> Rhs:
    r_valves = receipt.path.valves() if receipt else ()
    d_valves = delivery.path.valves() if delivery else ()
    i_r = receipt.path.inertance if receipt else 1.0
    i_d = delivery.path.inertance if delivery else 1.0
    shared = bool(receipt and delivery and receipt.tank == delivery.tank)

    def rhs(t: float, y: np.ndarray) -> list[float]:
        q_r, q_d, c_r, c_d = float(y[0]), float(y[1]), float(y[2]), float(y[3])
        dq_r = dq_d = 0.0
        if receipt is not None:
            net = c_r - (c_d if shared else 0.0)
            level = (receipt.level_from_net_volume(net) if receipt.level_from_net_volume else
                     receipt.level_m + net / receipt.area_m2)
            h_source = level + receipt.path.loss(q_r, _alphas(valves, r_valves, t), receipt.layout)
            setpoint = receipt.setpoint_fn(t) if receipt.setpoint_fn else receipt.setpoint_m3s
            free = (setpoint - q_r) / receipt.tau_c_s
            dq_r = min(free, (receipt.head_cap_m - h_source) / i_r)
        if delivery is not None:
            net = (c_r if shared else 0.0) - c_d
            level = (delivery.level_from_net_volume(net) if delivery.level_from_net_volume else
                     delivery.level_m + net / delivery.area_m2)
            q_h = max(q_d, 0.0) * 3600.0
            deduct = delivery.layout.boundary_deduct if delivery.layout else 0.0
            q_b = max(q_d - deduct, 0.0) * 3600.0
            boundary = delivery.law_c_m * delivery.demand(t) * (q_b / delivery.q_ref_m3h) ** 2
            drive = level + delivery.pump.head_rise_m(q_h) - delivery.reservoir_head_m - boundary
            drive -= delivery.path.loss(q_d, _alphas(valves, d_valves, t), delivery.layout)
            dq_d = drive / i_d
            if q_d <= 0.0 and dq_d < 0.0:
                dq_d = 0.0
        out_r = receipt.layout.total if receipt is not None and receipt.layout else 0.0
        out_d = delivery.layout.tank_extra if delivery is not None and delivery.layout else 0.0
        return [dq_r, dq_d, q_r - out_r, q_d + out_d]

    return rhs


def advance(
    rhs: Rhs,
    t0: float,
    t1: float,
    y0: tuple[float, float, float, float],
    rtol: float,
    atol: float,
) -> Advance:
    """Integrate from ``t0`` to ``t1`` with Radau; the result carries a dense interpolant."""
    if t1 <= t0:
        raise ValueError("the interval must have a positive length")
    sol = solve_ivp(
        rhs, (t0, t1), list(y0), method="Radau", rtol=rtol, atol=atol, dense_output=True
    )
    if not sol.success:
        raise ConvergenceError(f"flow integration failed: {sol.message}")
    y1 = tuple(float(v) for v in sol.y[:, -1])
    rates = rhs(t1, sol.y[:, -1])
    return Advance(t0, t1, y1, rates[0], rates[1], sol.sol)  # type: ignore[arg-type]
