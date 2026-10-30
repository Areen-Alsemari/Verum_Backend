"""Rigid-column flow dynamics of the receipt and delivery paths, integrated implicitly.

Inputs: a receipt column and a delivery column (each optional), the valve actuators, the
state ``[Q_r, Q_d, C_r, C_d]`` (path flows in m3/s and the volumes that have passed) and
a time interval. Outputs: the state at the end of the interval, the flow rates of change
there, and a dense interpolant over the interval.
Key assumptions:
    * Decision D22: ``dQ/dt = (H_drive - H_loss(Q)) / I`` with ``I = sum L_i / (g A_i)``.
      Receipt: ``H_drive = min(H_demand, H_cap)`` and ``H_demand = H_loss(Q) +
      I (Q_set - Q) / tau_c``, so that ``dQ/dt = min[(Q_set - Q) / tau_c,
      (H_cap - H_source(Q)) / I]`` where ``H_source = h_tank + H_loss(Q)``. Delivery:
      ``H_drive = h_tank + pump head(Q) - h_reservoir - c f_d (Q/Q_ref)^2``; the check
      valve keeps the flow from reversing.
    * The system is stiff when a valve nearly closes (the loss slope is large), so it is
      integrated with Radau IIA (implicit, order 5) with tolerances from the configuration.
      The volumes ``C_r`` and ``C_d`` are states of the same system, so the tank volumes
      and the ledger fluxes are the same numbers and the ledger closes by construction.
    * Tank levels inside the interval follow from the volumes with the local tank area
      (the geometry is piecewise linear); the valve openings are functions of time.
    * Leaks (decision D60, ``docs/fault_models.md``): the state is the source flow of the receipt
      column and the pump flow of the delivery column; the losses use the flow of each edge from the
      frozen leak flows of the layout, the boundary law uses the boundary flow, and the volumes
      that have passed are the flows into and out of the tank, ``dC_r = Q_r - leaks`` and
      ``dC_d = Q_d + suction leaks``. The inertial term keeps the single dQ/dt of D22.
    * Only the lumped paths are used here. The steady network solve is called afterwards
      for the node heads and pressures at the imposed flows.

Source: ``docs/design_decisions.md`` D22; ``revised/02_hydraulic_model.md`` section 3.
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
            level = receipt.level_m + (c_r - (c_d if shared else 0.0)) / receipt.area_m2
            h_source = level + receipt.path.loss(q_r, _alphas(valves, r_valves, t), receipt.layout)
            free = (receipt.setpoint_m3s - q_r) / receipt.tau_c_s
            dq_r = min(free, (receipt.head_cap_m - h_source) / i_r)
        if delivery is not None:
            level = delivery.level_m + ((c_r if shared else 0.0) - c_d) / delivery.area_m2
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
