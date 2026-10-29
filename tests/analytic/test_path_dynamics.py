"""Rigid-column path dynamics: inertance, step responses, slow limit, surge and decay.

Inputs: the lumped paths and the engine run on short custom scenarios, and the written
episodes S0-A and S0u-E. Outputs: pass/fail.

Derivations (hand arithmetic):
    * Inertance. The receipt path to TK-101 is 150 m of DN300 (A = 0.0721936 m2) and 45 m of
      DN200 (A = 0.0322811 m2): sum L/A = 2077.7 + 1394.0 = 3471.7 1/m, I = sum L/(g A) =
      354.0 s2/m2.
    * Surge. Along the flow the head drops by the loss plus (L/(g A)) dQ/dt, so at the source
      the head exceeds the quasi-steady head by I dQ/dt. In S0-B Q(t) = (600/3600)(1 - exp(-t/2)),
      so dQ/dt(1 s) = (600/3600)/2 exp(-1/2) = 0.050544 m3/s2 and the surge is 17.9 m.
    * Cap. The supply cap of 10 barg is a head of 1 m + 1e6/(750 x 9.80665) = 136.96 m at the
      source. Under the cap dQ/dt = (H_cap - H_source(Q))/I, so the source head is the cap and
      the offset to the quasi-steady head is I |dQ/dt|.
    * Delivery step response. For a small departure from the duty point the column relaxes
      with rate k = (d/dQ)[loss + c (Q/300)^2 - pump head] / I.
    * Lag. A column that follows a slowly moving equilibrium lags it by tau dQ_eq/dt, with
      tau = 1/k; the volume it delivers over the hour then differs from the quasi-steady
      volume by tau (Q_eq(end) - Q_eq(0)).
Independence: the closed forms, the hand inertance and the cap head are independent of the
code under test. The reference losses come from ``_reference_hydraulics`` (a separate
implementation of the same friction law, so the law itself is not independently tested).
The quasi-steady reference heads come from the steady solver (the same formulas as the
engine's lumped path; this is stated in each such test).

Source: ``docs/design_decisions.md`` D22 and D26.
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
    assert (150.0 / A300 + 45.0 / A200) == pytest.approx(3471.7, abs=0.1)
    assert INERTANCE == pytest.approx(354.0, abs=0.1)
    from verum.sim.path import receipt_path

    lineup = Lineup(frozenset({"XV-R000", "XV-R101"}), frozenset())
    path = receipt_path(model, "TK-101", lineup, "reference_fittings")
    assert path.inertance == pytest.approx(INERTANCE, rel=1e-12)


def test_delivery_step_response_follows_the_linearised_closed_form(model: HydraulicModel) -> None:
    """A 1 % flow departure from the duty point relaxes as exp(-k t), k from hand derivatives.

    Independent for the closed form and the loss derivative (reference module, central
    difference); the duty point comes from the reference root find. The inertance of the TK-102
    delivery path is (90 + 20 + 250) m of DN200 plus 35 m of DN250, over g.
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
    """Independent closed form: Q(t) = 300 + 300 exp(-(t - 1200)/2) m3/h after the S0-G step."""
    s = series["S0-G"]
    flows = {t: q for t, side, q in s.edge["E001"] if side != "pre_event"}
    assert flows[1200.0] * 3600 == pytest.approx(600.0, rel=1e-9)
    for dt in (1.0, 2.0, 4.0, 6.0, 10.0):
        expected = 300.0 + 300.0 * math.exp(-dt / 2.0)
        assert flows[1200.0 + dt] * 3600 == pytest.approx(expected, rel=1e-6), dt
    assert flows[3600.0] * 3600 == pytest.approx(300.0, rel=1e-9)


def test_the_slow_limit_matches_the_phase_3_quasi_steady_flow(model: HydraulicModel) -> None:
    """A 600 s ramp of the set-point: the flow follows the Phase 3 first-order response.

    Independent: the reference solves dq/dt = (q_set(t) - q)/tau with the staircase set-point
    exactly, piece by piece (closed form of each piece). The Phase 3 engine integrated the
    same first-order response; the new engine must reproduce its volume within the D17 target.
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
    """The delivery column lags the slowly falling duty flow by tau dQ_eq/dt (hand derivation).

    Integrated over the hour the lag is tau (Q_eq(end) - Q_eq(0)) with tau = 1/k. With the
    TK-101 path inertance 1112.6 s2/m2 and the loss-plus-pump slope at the duty point,
    k = 0.7257 1/s, tau = 1.378 s, and the flow falls by 0.00049 m3/s over the hour, so the
    quasi-steady volume exceeds the engine's by about 6.7e-4 m3 (1.0e-6 m of level). The
    engine's pump flow rows give Q_eq(0) and Q_eq(end).
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


def test_pt001_surge_head_is_the_inertance_times_the_flow_rate(
    model: HydraulicModel, series: dict[str, Series]
) -> None:
    """S0-B ramp: head(PT-001) - quasi-steady head = I dQ/dt, with dQ/dt from the closed form.

    The quasi-steady head is a steady solve at the logged flow and level (same formulas as the
    engine's lumped path, so this checks the offset, not the loss law).
    """
    s = series["S0-B"]
    head = {t: h for t, side, h in s.head["PIPELINE_RECEIPT_BOUNDARY"] if side != "pre_event"}
    flow = {t: q for t, side, q in s.edge["E001"] if side != "pre_event"}
    level = {t: lv for t, side, lv, _v, _f in s.tank["TK-101"] if side != "pre_event"}
    for t in (1.0, 2.0, 4.0):
        qdot = (600.0 / 3600.0) / 2.0 * math.exp(-t / 2.0)
        quasi = _quasi_steady_head(model, level[t], flow[t] * 3600.0, None, "RECEIVE_101")
        assert head[t] is not None
        assert head[t] - quasi == pytest.approx(INERTANCE * qdot, rel=1e-4), t
    assert INERTANCE * (600.0 / 3600.0) / 2.0 * math.exp(-0.5) == pytest.approx(17.9, abs=0.05)


def test_pt001_is_at_the_cap_and_the_surge_is_i_times_the_decay_rate_under_the_cap(
    model: HydraulicModel,
) -> None:
    """Slow closure (2000 s stroke) of XV-R000 at 600 m3/h: under the cap the head at PT-001 is
    the cap head 136.96 m, and the offset to the quasi-steady head is I |dQ/dt|, with dQ/dt
    taken from the logged flow by a central difference over two seconds.
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
        assert heads[t]["hydraulic_head_m"] == pytest.approx(H_CAP, abs=1e-6)
        quasi = _quasi_steady_head(
            model, levels[t]["level_m"], q * 3600.0, valve[t]["position_frac"], "RECEIVE_101"
        )
        assert heads[t]["hydraulic_head_m"] - quasi == pytest.approx(
            INERTANCE * abs(qdot) * (-1.0), rel=0.05
        ) or (heads[t]["hydraulic_head_m"] - quasi) == pytest.approx(-INERTANCE * qdot, rel=0.05)
        checked += 1
    assert checked == 4


def test_the_esd_decay_time_lies_between_the_hand_bounds(
    episodes: dict[str, EpisodeResult], series: dict[str, Series]
) -> None:
    """Hand bounds on the decay of the flow (90 % to 10 %) in the 10 s closure under the cap.

    The cap binds when the valve loss at 600 m3/h reaches the head budget, alpha* = 0.03165
    (hand: K = 421.8 from the budget 136.96 - 13 - 9.37 m over v^2/2g = 0.27175 m, Kv ratio
    sqrt(0.1/421.8) = 0.015398, linear branch alpha = ratio x 0.05 / 50^-0.95). Until then the
    flow is 600 m3/h; afterwards it cannot fall below the cap-limited flow 600 alpha/alpha*
    (the column lags the equilibrium from above). The 90 % flow therefore occurs no earlier
    than alpha = 0.9 alpha* = 0.02849, 9.715 s into the stroke, and the valve is closed at
    9.99 s, so the decay time is at most 0.275 s. The collapse is faster than 10 wave round
    trips of the path (3.6 s), which is why it is a validity window.
    """
    windows = [w for w in series["S0u-E"].windows if w["kind"] == "flow_collapse"]
    assert len(windows) == 1
    w = windows[0]
    assert w["element_id"] == "XV-R000"
    decay = w["t_end_s"] - w["t_start_s"]
    assert 0.02 < decay <= 0.275 + 1e-3
    assert w["t_end_s"] == pytest.approx(episodes["S0u-E"].outcome.windows[0].t_end_s)
    assert w["ratio"] == pytest.approx(decay / w["round_trip_s"])
    assert w["ratio"] < 10.0
