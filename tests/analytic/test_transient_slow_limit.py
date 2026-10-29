"""Slow-limit equivalence of the transient engine and the rigid-column engine (R8).

Inputs: a 600 s receipt valve closure into TK-101 and a 600 s closure of the pump outlet valve
of a running delivery, each run by both engines from the same lineup, levels and valve command.
Outputs: pass/fail.
Key assumptions:
    * The rigid-column engine has no delivery set-point (the delivery flow follows the pump
      curve and the downstream law), so the slow delivery change is the 600 s stroke of
      XV-PAO; the receipt case is the 600 s stroke of XV-R000 at 600 m3/h.
    * Only for the receipt case, a term of 3 percent of the valve loss p - p(5 s) is allowed: it is
      measured, not derived. During the slow receipt closure the rigid column's pressure exceeds
      the steady package's value at the same opening by 0.2 to 2.0 percent of that loss (0.0072
      bar at 408 s) although its flow is constant and its inertia term vanishes; the elastic
      engine reproduces the steady package to 0.0001 bar. The cause in the rigid-column engine
      was not traced and is recorded as a finding. A separate check compares the elastic series
      with the steady package itself.
    * The loss law K(alpha) changes regime at the opening valve_alpha_c; the one instant at that
      opening is left out (the two engines sit on opposite sides of the kink by round-off).
    * Compared on one-second instants from 5 s to 580 s, before the last 3 percent of the
      stroke in which the throttling is a near-step and 2L/a is no longer small against the
      time scale of the change.
    * Not independent validation of either engine: both use the same valve law, friction law
      and boundary definitions; the test shows that the elastic and the rigid models agree in
      the limit in which they should.

Tolerance, derived. The two models differ in the inertia they carry: the rigid column has the
lumped head Lambda dQ/dt, the elastic model carries the same inertia as waves of round-trip
time T = 2 sum L/a. A flow that changes at the rate dQ/dt therefore differs between them by at
most the inertial pressure rho (sum L/A) |dQ/dt| of the path, and by at most T |dQ/dt| in flow
(the flow change during one round trip), apart from a relative 0.1 percent for the lumped
treatment and the one-step lag. The elastic model also stores liquid as the pressure changes, a
volume C dH with C = g sum(A L) / a^2 (4.0e-5 m3 per m of head on the receipt path), which the
rigid column does not; at a throttled valve this makes the pressure lag the quasi-static value
by tau = C dH/dQ = 2 C (head drop in the valve) / Q, at most 0.05 s over the compared range
(valve opening down to 0.05). The rigid-column engine advances in steps of at most 1 s and
writes the state at the end of a step, so its state can lead the elastic engine's by up to one
step. The allowance is therefore delta = 1.2 s: one rigid step plus 0.2 s, four times the
storage lag, for the one-second sampling and the interpolation of the elastic series. The
rigid-column run also lets TK-101 fill (600 m3/h into 706.858 m2 raises the level 2.36e-4 m/s and
the pressure at the tank 1.74 Pa/s) while the elastic run holds the tank level; the analytic
drift is added to the bound. (A first version took the growing difference, 0.0072 bar at 408 s,
for an error of the rigid-column engine; it is the filling of the tank, and the elastic engine
reproduces the steady package at the opening of each instant to 0.0001 bar.) The bounds are
    |dp| <= 0.001 |p| + rho (sum L/A) |dQ/dt| + delta |dp/dt| + rho g (Q / A_tank) (t - 5 s),
    |dQ| <= 0.001 |Q| + T |dQ/dt|,
with the sums over the edges of the path (receipt: E001, E002, E003, E-R101a, E-R101b, T = 0.36 s;
delivery: the suction, pump and delivery edges to the distribution boundary, T = 0.67 s) and the
rate taken from the rigid series by central difference. (A first version of the pressure bound
used T |dp/dt|, which is the wrong scale for a pressure that differs through inertia; it failed
by 45 percent at the last instant and the premise, not the data, was corrected.)

Source: ``docs/design_decisions.md`` D22, D43; ``tests/analytic/test_pt001_anchor.py`` for the
slow-closure pattern.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import pytest

from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.params import ParamValue
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.scenario import load_scenario
from verum.transient import TransientEngine, TransientSpec
from verum.transient.driver import Probe, ValveEvent
from verum.truth import ListSink

T0, STROKE, T_END = 10.0, 600.0, 580.0
LEVELS = {"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0}


def _rigid(
    model: HydraulicModel, base: str, valve: str, edge: str, pedge: str, **kw: Any
) -> dict[str, np.ndarray]:
    cfg0 = load_sim_config()
    key = "stroke_time_xv_r000_s" if valve == "XV-R000" else "stroke_time_other_motorized_s"
    cfg = dataclasses.replace(
        cfg0,
        parameters={
            **cfg0.parameters,
            key: ParamValue.selected(STROKE, "s", "DESIGN", "TEST-SLOW"),
        },
    )
    scenario = dataclasses.replace(
        load_scenario(base), duration_s=T_END + 5.0, healthy_envelope=False,
        schedule=[{"t_s": T0, "command": "close_valves", "valves": [valve]}], **kw,
    )  # fmt: skip
    engine = Engine(model, load_lineup_table(model.topology), scenario, cfg, ListSink(), "EP")
    engine.run()
    sink: Any = engine.sink
    rows = sorted(
        (r["t_sim_s"], r["payload"])
        for r in sink.rows["hydraulic_state"]
        if r["side"] is None and r["record_type"] == "edge_state" and r["element_id"] == edge
    )
    t_rows = np.array([x[0] for x in rows])  # the grid has gaps at event instants: interpolate
    t = np.arange(5.0, T_END + 1.0, 1.0)
    q = np.interp(t, t_rows, [x[1]["flow_m3s"] for x in rows])
    if pedge != edge:
        rows = sorted(
            (r["t_sim_s"], r["payload"])
            for r in sink.rows["hydraulic_state"]
            if r["side"] is None and r["record_type"] == "edge_state" and r["element_id"] == pedge
        )
        t_rows = np.array([x[0] for x in rows])
    p = np.interp(t, t_rows, [x[1]["p_to_pa_abs"] - model.patm for x in rows])
    return {"t": t, "q": q, "p": p}


def _moc(
    model: HydraulicModel, mode: str, valve: str, edge: str, pedge: str, **kw: Any
) -> dict[str, np.ndarray]:
    spec = TransientSpec(
        lineup=load_lineup_table(model.topology).mode(mode).lineup, tank_levels_m=dict(LEVELS),
        fitting_profile="reference_fittings", valve_events=(ValveEvent(valve, T0, 0.0, STROKE),),
        **kw,
    )  # fmt: skip
    e = TransientEngine(model, spec)
    rec = e.run(T_END + 1.0, [Probe("q", edge, 0.5), Probe("p", pedge, 1.0)], stride=1000)
    t = np.arange(5.0, T_END + 1.0, 1.0)
    z = e.z[e.point_index(pedge, 1.0)]
    return {
        "q": np.interp(t, rec["t"], rec["q.Q"]),
        "p": e.rho * e.g * (np.interp(t, rec["t"], rec["p.H"]) - z),
        "windows": np.array([len(e.phase.windows)]),
    }


def _inertia(model: HydraulicModel, path: tuple[str, ...]) -> float:
    """rho sum(L / A) over the edges of a path, in Pa s2 / m3."""
    edges = {e.edge_id: e for e in model.topology.edges}
    return model.rho * sum(
        edges[x].length_m / (np.pi * edges[x].inner_diameter_m ** 2 / 4.0) for x in path
    )


def _assert_equivalent(
    rigid: dict[str, np.ndarray],
    moc: dict[str, np.ndarray],
    t_rt: float,
    inertia: float,
    alpha_c: float,
    tank_drift_pa_s: float = 0.0,
) -> None:
    t, step = rigid["t"], 1.0
    # the loss law changes regime at alpha_c; an instant within 0.5 s of that opening falls on
    # either side of the kink in the two engines, so it is not compared
    off_kink = np.abs(t - (T0 + (1.0 - alpha_c) * STROKE)) > 0.5
    rate_q = np.gradient(rigid["q"], step)
    bounds = {
        "q": 1e-3 * np.abs(rigid["q"]) + t_rt * np.abs(rate_q),
        "p": 1e-3 * np.abs(rigid["p"])
        + tank_drift_pa_s * (t - t[0])
        + inertia * np.abs(rate_q)
        + 1.2 * np.abs(np.gradient(rigid["p"], step)),
    }
    for name in ("q", "p"):
        ref, other = rigid[name], moc[name]
        bound = bounds[name]
        worst = np.where(off_kink, np.abs(other - ref) - bound, -np.inf)
        assert np.all(worst <= 0.0), (name, float(t[np.argmax(worst)]), float(np.max(worst)))
    assert moc["windows"][0] == 0


def _assert_elastic_equals_steady(model: HydraulicModel, moc: dict[str, np.ndarray]) -> None:
    """The elastic series against the steady package at the opening of each instant (independent:
    the steady package solves the network with the valve position given, at the constant flow)."""
    from verum.graph import Lineup
    from verum.hydraulics import ReceiptBoundary, SteadyInputs

    t = np.arange(5.0, T_END + 1.0, 1.0)
    rate = np.gradient(moc["p"], 1.0)
    lineup = Lineup.of({"XV-R000", "XV-R101"})
    for k in range(95, len(t), 60):  # t = 100, 160, ..., 560 s
        alpha = 1.0 - (t[k] - T0) / STROKE
        if abs(alpha - model.config["valve_alpha_c"]) < 1e-3:
            continue  # the instant on the kink of the loss law
        r = model.solve(
            SteadyInputs(
                lineup, dict(LEVELS), "RVP_9_0", 25.0, fitting_profile="reference_fittings",
                receipt=ReceiptBoundary(flow_m3h=600.0), valve_positions={"XV-R000": alpha},
            )
        )  # fmt: skip
        steady = r.edge_end_pressures_pa_gauge["E002"][1]
        assert abs(moc["p"][k] - steady) <= 1e-3 * steady + 0.2 * abs(rate[k]), float(t[k])


@pytest.mark.slow
def test_r8_receipt_closure_over_600_s_agrees_with_the_rigid_column(model: HydraulicModel) -> None:
    flow = {"receipt_flow_m3h": 600.0, "receipt_setpoint_m3h": 600.0}
    rigid = _rigid(model, "S0-B", "XV-R000", "E001", "E002", **flow)
    moc = _moc(model, "RECEIVE_101", "XV-R000", "E001", "E002", **flow)
    path = ("E001", "E002", "E003", "E-R101a", "E-R101b")
    alpha_c = model.config["valve_alpha_c"]
    drift = model.rho * model.g * (600.0 / 3600.0) / 706.858347
    _assert_equivalent(rigid, moc, 0.36, _inertia(model, path), alpha_c, drift)
    _assert_elastic_equals_steady(model, moc)
    assert rigid["p"].max() > 4.0e5  # reaches the throttled end (4.6 bar against 1.2 open)


@pytest.mark.slow
def test_r8_delivery_valve_closure_over_600_s_agrees_with_the_rigid_column(
    model: HydraulicModel,
) -> None:
    rigid = _rigid(model, "S0-A", "XV-PAO", "E-PA4", "E-PA4")
    moc = _moc(model, "DELIVER_101_A", "XV-PAO", "E-PA4", "E-PA4")
    path = (
        "E-S101a", "E-S101b", "E-SH", "E-PA0", "E-PA1", "E-PA2", "E-PA3", "E-PA4", "E-D1", "E-D2",
    )  # fmt: skip
    _assert_equivalent(rigid, moc, 0.67, _inertia(model, path), model.config["valve_alpha_c"])
    assert rigid["q"][-1] < 0.7 * rigid["q"][0]  # the flow has fallen well down the pump curve
