"""Slow-limit equivalence of the transient engine and the rigid-column engine.

A 600 s receipt valve closure and a 600 s closure of the pump outlet valve of a running delivery are
run by both engines from the same lineup, levels and valve command, and compared once per second.
Both engines use the same valve law, friction law and boundary definitions, so this shows that the
elastic and rigid models agree in the limit in which they should and does not validate either. The
derived tolerance is in the "Transient engine: slow limit" section of the verification notes.

See D22 and D43.
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
    """During a 600 s closure of the receipt valve the pressure and flow of the two engines agree
    within the derived bounds. Independent: no, because both engines share the valve law, friction
    law and boundary definitions.
    """
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
    """During a 600 s closure of the pump outlet valve the pressure and flow of the two engines
    agree within the derived bounds. Independent: no, because both engines share the valve law,
    friction law and boundary definitions.
    """
    rigid = _rigid(model, "S0-A", "XV-PAO", "E-PA4", "E-PA4")
    moc = _moc(model, "DELIVER_101_A", "XV-PAO", "E-PA4", "E-PA4")
    path = (
        "E-S101a", "E-S101b", "E-SH", "E-PA0", "E-PA1", "E-PA2", "E-PA3", "E-PA4", "E-D1", "E-D2",
    )  # fmt: skip
    _assert_equivalent(rigid, moc, 0.67, _inertia(model, path), model.config["valve_alpha_c"])
    assert rigid["q"][-1] < 0.7 * rigid["q"][0]  # the flow has fallen well down the pump curve
