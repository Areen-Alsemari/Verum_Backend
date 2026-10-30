"""Rigid-column path dynamics: inertance, step responses, the slow limit, surge and decay.

The lumped paths and short engine runs are compared with hand derivations of the inertance, the
linearised step response, the first-order receipt response, the lag of a column behind a moving
equilibrium, the surge head, the capped flow and the decay of the flow in the emergency closure. The
derivations are in the "Rigid-column path dynamics" section of the verification notes.

See D22 and D26.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import pytest

import _reference_hydraulics as ref
from _series import Series
from verum.graph import Lineup
from verum.hydraulics import HydraulicModel, ReceiptBoundary, SteadyInputs
from verum.lineups import load_lineup_table
from verum.params import ParamValue
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.episode import EpisodeResult
from verum.sim.scenario import load_scenario
from verum.tanks import load_tank_geometry
from verum.truth import ListSink

RHO, G = 750.0, 9.80665
A300, A200 = math.pi * ref.D300**2 / 4, math.pi * ref.D200**2 / 4
INERTANCE = (150.0 / A300 + 45.0 / A200) / G  # s2/m2
H_CAP = 1.0 + 1.0e6 / (RHO * G)  # m, source head at the 10 barg cap (source elevation 1 m)
SCENARIO = "EPA_GENERIC_RVP10_REFERENCE"
TARGET = 2.5e-5


def _engine(model: HydraulicModel, scenario: Any, cfg: Any = None) -> Engine:
    return Engine(
        model,
        load_lineup_table(model.topology),
        scenario,
        cfg or load_sim_config(),
        ListSink(),
        "EP-TEST",
    )


def _rows(engine: Engine, kind: str, element: str) -> dict[float, dict[str, Any]]:
    sink: Any = engine.sink
    return {
        r["t_sim_s"]: r["payload"]
        for r in sink.rows["hydraulic_state"]
        if r["record_type"] == kind and r["element_id"] == element and r["side"] != "pre_event"
    }


def test_the_hand_inertance_of_the_receipt_path(model: HydraulicModel) -> None:
    """The inertance of the receipt path to tank TK-101 is 354 s2/m2, from the hand sum of length
    over area. Independent: yes, because the value is hand arithmetic.
    """
    assert (150.0 / A300 + 45.0 / A200) == pytest.approx(3471.7, abs=0.1)
    assert INERTANCE == pytest.approx(354.0, abs=0.1)
    from verum.sim.path import receipt_path

    lineup = Lineup(frozenset({"XV-R000", "XV-R101"}), frozenset())
    path = receipt_path(model, "TK-101", lineup, "reference_fittings")
    assert path.inertance == pytest.approx(INERTANCE, rel=1e-12)


def test_delivery_step_response_follows_the_linearised_closed_form(model: HydraulicModel) -> None:
    """A 1 percent departure of the delivery flow from the duty point relaxes as exp(-k t) with the
    rate k from the hand derivatives. Independent: yes, because the closed form and the loss
    derivative come from the reference module.
    """
    scenario = dataclasses.replace(load_scenario("S0-A"), initial_mode="DELIVER_102_A")
    scenario = dataclasses.replace(scenario, duration_s=40.0, healthy_envelope=False)
    scenario = dataclasses.replace(
        scenario, tank_levels_m={"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0}
    )
    engine = _engine(model, scenario)
    engine.run(until=0.0)
    q_eq = engine.state.delivery_flow_m3h / 3600.0
    c = 10.060889
    segments = ref.tank2_reference_fittings_segments()
    assert q_eq * 3600 == pytest.approx(
        ref.operating_flow_m3h(7.0, c, segments), rel=1e-6
    )  # the duty point
    inertance = ((90.0 + 20.0 + 250.0) / A200 + 35.0 / (math.pi * ref.D250**2 / 4)) / G
    h = 1e-6

    def net(q: float) -> float:
        return ref.path_loss(q, segments) + c * (q * 3600 / 300) ** 2 - ref.pump_head(q)

    slope = (net(q_eq + h) - net(q_eq - h)) / (2 * h)
    rate = slope / inertance
    assert 0.5 < rate < 1.0  # relaxation time between 1 and 2 s
    engine.state.delivery_flow_m3h = q_eq * 1.01 * 3600.0
    engine.run(until=30.0)
    flows = _rows(engine, "pump_state", "P-101A")
    for t in (1.0, 2.0, 3.0, 5.0, 8.0):
        expected = q_eq * (1.0 + 0.01 * math.exp(-rate * t))
        assert flows[t]["flow_m3s"] == pytest.approx(expected, rel=2e-5), t


def test_the_uncapped_receipt_response_keeps_the_controller_time_constant(
    series: dict[str, Series],
) -> None:
    """After a receipt set-point step the flow follows 300 + 300 exp(-t/2) m3/h. Independent: yes,
    because the reference is a closed form.
    """
    s = series["S0-G"]
    flows = {t: q for t, side, q in s.edge["E001"] if side != "pre_event"}
    assert flows[1200.0] * 3600 == pytest.approx(600.0, rel=1e-9)
    for dt in (1.0, 2.0, 4.0, 6.0, 10.0):
        expected = 300.0 + 300.0 * math.exp(-dt / 2.0)
        assert flows[1200.0 + dt] * 3600 == pytest.approx(expected, rel=1e-6), dt
    assert flows[3600.0] * 3600 == pytest.approx(300.0, rel=1e-9)


@pytest.mark.slow
def test_the_slow_limit_matches_the_phase_3_quasi_steady_flow(model: HydraulicModel) -> None:
    """A 600 s ramp of the set-point gives the flow of the first-order response solved piece by
    piece, and the volume matches within the accuracy target. Independent: yes, because the
    reference solves each staircase piece in closed form.
    """
    steps = 600
    schedule = [
        {"t_s": float(k), "command": "receipt_setpoint", "value_m3h": 600.0 * k / steps}
        for k in range(steps)
    ]
    scenario = dataclasses.replace(
        load_scenario("S0-B"),
        duration_s=600.0,
        schedule=schedule,
        healthy_envelope=False,
    )
    outcome = _engine(model, scenario).run()
    assert outcome.rejection is None
    q, volume = 0.0, 0.0
    decay = math.exp(-1.0 / 2.0)
    for k in range(steps):
        target = 600.0 / 3600.0 * k / steps
        q_next = target + (q - target) * decay
        volume += target * 1.0 + (q - target) * 2.0 * (1.0 - decay)
        q = q_next
    geometry = load_tank_geometry()
    start = geometry.volume_m3(9.0, RHO)
    engine_level = geometry.level_m(outcome.final_volumes["TK-101"], RHO)
    assert engine_level == pytest.approx(geometry.level_m(start + volume, RHO), abs=TARGET)


def test_the_s0a_volume_differs_from_the_quasi_steady_one_by_the_hand_lag(
    series: dict[str, Series],
) -> None:
    """The delivered volume differs from the quasi-steady volume by the lag of the column behind the
    falling duty flow, about 1.07e-6 m of level. Independent: yes, because the lag is a hand
    derivation.
    """
    s = series["S0-A"]
    flows = [(t, q) for t, side, _st, q, _ph, _m in s.pump["P-101A"] if side != "pre_event"]
    q0, q_end = flows[0][1], flows[-1][1]
    tau = 1.0 / 0.7257
    lag_volume = tau * (q0 - q_end)
    assert lag_volume / 706.858347 == pytest.approx(1.07e-6, rel=0.2)


def _quasi_steady_head(
    model: HydraulicModel, level: float, q_m3h: float, alpha: float | None, mode: str
) -> float:
    mode_def = load_lineup_table(model.topology).mode(mode)
    inputs = SteadyInputs(
        Lineup(mode_def.open_valves, mode_def.running_pumps),
        {"TK-101": level, "TK-102": 7.0, "TK-103": 5.0},
        SCENARIO,
        25.0,
        fitting_profile="reference_fittings",
        receipt=ReceiptBoundary(flow_m3h=q_m3h),
        valve_positions={} if alpha is None else {"XV-R000": alpha},
        apply_cap=False,
    )
    return model.solve(inputs).node_heads_m["PIPELINE_RECEIPT_BOUNDARY"]


def test_pt001_surge_head_is_the_downstream_inertance_times_the_flow_rate(
    model: HydraulicModel, series: dict[str, Series]
) -> None:
    """During the receipt ramp the PT-001 head exceeds the quasi-steady head by the inertance from
    the tap to the tank times dQ/dt. Independent: no, because the quasi-steady head comes from the
    steady solver, so this checks the offsets and not the loss law.
    """
    s = series["S0-B"]
    head = {t: h for t, side, h in s.head["PIPELINE_RECEIPT_BOUNDARY"] if side != "pre_event"}
    flow = {t: q for t, side, q in s.edge["E001"] if side != "pre_event"}
    level = {t: lv for t, side, lv, _v, _f in s.tank["TK-101"] if side != "pre_event"}
    downstream = INERTANCE - 45.0 / (G * A300)
    assert downstream == pytest.approx(290.5, abs=0.1)
    for t in (1.0, 2.0, 4.0):
        qdot = (600.0 / 3600.0) / 2.0 * math.exp(-t / 2.0)
        quasi = _quasi_steady_head(model, level[t], flow[t] * 3600.0, None, "RECEIVE_101")
        tap = head[t]
        assert tap is not None  # the tap has a head while the path is open
        loss_up = _loss_up(flow[t])
        assert tap - (quasi - loss_up) == pytest.approx(downstream * qdot, rel=1e-4), t


def _loss_up(q: float) -> float:
    return ref.loss(q, ref.D300, 30.0, 0.0) + ref.loss(q, ref.D300, 15.0, 1.0)


@pytest.mark.slow
def test_pt001_under_the_cap_is_the_cap_less_the_upstream_loss_plus_the_upstream_inertia(
    model: HydraulicModel,
) -> None:
    """During a slow closure under the cap the PT-001 head is the cap head less the upstream loss
    plus the upstream inertia term. Independent: no, because the quasi-steady tap comes from the
    steady solver, so this checks the offsets and not the loss law.
    """
    cfg0 = load_sim_config()
    cfg = dataclasses.replace(
        cfg0,
        parameters={
            **cfg0.parameters,
            "stroke_time_xv_r000_s": ParamValue.selected(2000.0, "s", "DESIGN", "TEST-SLOW-STROKE"),
        },
    )
    scenario = dataclasses.replace(
        load_scenario("S0-B"),
        duration_s=2012.0,
        healthy_envelope=False,
        receipt_flow_m3h=600.0,
        receipt_setpoint_m3h=600.0,
        schedule=[{"t_s": 10.0, "command": "close_valves", "valves": ["XV-R000"]}],
    )
    engine = _engine(model, scenario, cfg)
    outcome = engine.run()
    assert outcome.rejection is None
    heads = _rows(engine, "node_state", "PIPELINE_RECEIPT_BOUNDARY")
    flows = _rows(engine, "edge_state", "E001")
    valve = _rows(engine, "valve_state", "XV-R000")
    levels = _rows(engine, "tank_state", "TK-101")
    checked = 0
    for t in (1975.0, 1985.0, 1995.0, 2000.0):
        q = flows[t]["flow_m3s"]
        qdot = (flows[t + 1.0]["flow_m3s"] - flows[t - 1.0]["flow_m3s"]) / 2.0
        assert qdot < 0.0 and q * 3600.0 < 600.0 - 1.0  # decaying under the cap
        # Decision D36: the source head is the cap; the tap is after E001 and E002.
        tap = heads[t]["hydraulic_head_m"]
        assert tap == pytest.approx(H_CAP - _loss_up(q) + 45.0 / (G * A300) * abs(qdot), abs=0.02)
        quasi = _quasi_steady_head(
            model, levels[t]["level_m"], q * 3600.0, valve[t]["position_frac"], "RECEIVE_101"
        )
        downstream = INERTANCE - 45.0 / (G * A300)
        assert tap - (quasi - _loss_up(q)) == pytest.approx(downstream * qdot, rel=0.05)
        checked += 1
    assert checked == 4


def test_the_esd_decay_time_lies_between_the_hand_bounds(
    episodes: dict[str, EpisodeResult], series: dict[str, Series]
) -> None:
    """The flow collapse in the 10 s emergency closure lasts at most 0.275 s, which is shorter than
    ten wave round trips and therefore opens a validity window. Independent: yes, because the bounds
    are hand arithmetic.
    """
    windows = [w for w in series["S0u-E"].windows if w["kind"] == "flow_collapse"]
    assert len(windows) == 1
    w = windows[0]
    assert w["element_id"] == "XV-R000"
    decay = w["t_end_s"] - w["t_start_s"]
    assert 0.02 < decay <= 0.275 + 1e-3
    collapse = next(x for x in episodes["S0u-E"].outcome.windows if x.kind == "flow_collapse")
    assert w["t_end_s"] == pytest.approx(collapse.t_end_s)
    assert w["ratio"] == pytest.approx(decay / w["round_trip_s"])
    assert w["ratio"] < 10.0
