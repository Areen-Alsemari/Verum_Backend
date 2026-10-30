"""Dead-leg pressures: relaxation, the standby branch and every lineup.

A segment cut off by a closing valve relaxes to the head across the valve with a 60 s time constant,
and the standby pump branch reads the head of the suction tee within the lag of two first-order
stages. Every lineup must give every edge an end pressure. The closed forms are in the "Dead-leg
pressures" section of the verification notes.

See D39.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import pytest

from _series import Series
from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.scenario import load_scenario
from verum.truth import ListSink

RHO, G = 750.0, 9.80665


def _engine(model: HydraulicModel, scenario: Any) -> Engine:
    return Engine(
        model, load_lineup_table(model.topology), scenario, load_sim_config(), ListSink(), "EP"
    )


def test_a_closed_receipt_segment_relaxes_to_the_tank_head_with_sixty_seconds(
    model: HydraulicModel,
) -> None:
    """After the common receipt valve closes, the isolated segment relaxes to the tank head as H_t +
    (H_0 - H_t) exp(-t/60 s). Independent: yes, because the closed form does not depend on the code
    and the heads are read from written rows.
    """
    scenario = dataclasses.replace(
        load_scenario("S0-B"),
        duration_s=500.0,
        healthy_envelope=False,
        receipt_flow_m3h=300.0,
        receipt_setpoint_m3h=300.0,
        schedule=[{"t_s": 100.0, "command": "close_valves", "valves": ["XV-R000"]}],
    )
    engine = _engine(model, scenario)
    assert engine.run().rejection is None
    sink: Any = engine.sink
    e002 = {
        r["t_sim_s"]: r["payload"]
        for r in sink.rows["hydraulic_state"]
        if r["record_type"] == "edge_state"
        and r["element_id"] == "E002"
        and r["side"] != "pre_event"
    }
    level = {
        r["t_sim_s"]: r["payload"]["level_m"]
        for r in sink.rows["hydraulic_state"]
        if r["record_type"] == "tank_state"
        and r["element_id"] == "TK-101"
        and r["side"] != "pre_event"
    }

    def head(t: float) -> float:
        return float(1.0 + (e002[t]["p_from_pa_abs"] - 101325.0) / (RHO * G))

    t_c = min(e002, key=lambda t: abs(t - 109.99))  # the closed threshold of XV-R000
    assert t_c == pytest.approx(109.99)
    h0, target = head(t_c), level[t_c]
    assert h0 > target + 0.1  # the cut-off segment holds a head above the tank head
    for t in (120.0, 140.0, 170.0, 230.0, 350.0):
        expected = target + (h0 - target) * math.exp(-(t - t_c) / 60.0)
        assert head(t) == pytest.approx(expected, abs=2e-3), t
    # after four time constants exp(-4) = 1.8 percent of the initial excess is left
    assert head(350.0) - target == pytest.approx(0.0183 * (h0 - target), rel=0.02)


def test_the_standby_branch_reads_the_suction_tee_head(series: dict[str, Series]) -> None:
    """The standby pump branch reads rho g (H_tee - z) within the lag of two relaxation stages,
    about 106 Pa. Independent: yes, because the lag is hand arithmetic.
    """
    s = series["S0-A"]
    tee = {t: h for t, side, h in s.head["PUMP_SUCTION_TEE"] if side is None}
    standby = {t: p for t, side, p, _to in s.edge_p["E-PB2"] if side is None}
    assert all(p is not None for p in standby.values())
    for t in (200.0, 1000.0, 3000.0):
        reading, level = standby[t], tee[t]
        assert reading is not None and level is not None
        later, earlier = tee[t + 100.0], tee[t - 100.0]
        assert later is not None and earlier is not None
        rate = abs(later - earlier) / 200.0  # m/s, finite difference
        assert 0.5e-4 < rate < 2e-4
        expected = RHO * G * (level - 0.5) + 101325.0  # z of the pump B branch is 0.5 m
        assert reading == pytest.approx(expected, abs=RHO * G * 2 * 60.0 * rate * 1.1), t
        assert reading >= expected - 1e-6  # it lags the falling head from above, never below


def test_no_lineup_produces_an_undetermined_pressure(model: HydraulicModel) -> None:
    """In all 16 lineups every edge has end pressures and every tap has a value. Independent: yes,
    because the expected outcome is the rule that no pressure is left undetermined.
    """
    table = load_lineup_table(model.topology)
    names = sorted(table.modes) if hasattr(table, "modes") else []
    assert len(names) == 16
    for name in names:
        scenario = dataclasses.replace(
            load_scenario("S0-A"),
            initial_mode=name,
            duration_s=3.0,
            healthy_envelope=False,
            tank_levels_m={"TK-101": 9.0, "TK-102": 9.0, "TK-103": 9.0},
        )
        engine = _engine(model, scenario)
        assert engine.run().rejection is None, name
        sink: Any = engine.sink
        for r in sink.rows["hydraulic_state"]:
            payload = r["payload"]
            if r["record_type"] == "edge_state":
                assert payload["p_from_pa_abs"] is not None, (name, r["element_id"])
                assert payload["p_to_pa_abs"] is not None, (name, r["element_id"])
            elif r["record_type"] == "node_state":
                assert payload["pressure_pa_abs"] is not None, (name, r["element_id"])
                assert payload["hydraulic_head_m"] is not None, (name, r["element_id"])
