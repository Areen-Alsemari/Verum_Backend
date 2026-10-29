"""Dead-leg pressures (decision D39): relaxation, standby branch, every lineup.

Inputs: short engine runs on custom scenarios and the written episode S0-A. Outputs:
pass/fail.

Derivations (hand arithmetic):
    * Relaxation. A segment isolated at time t_c with head H_0 relaxes to the head across its
      closed valve, H_target, as H(t) = H_target + (H_0 - H_target) exp(-(t - t_c)/60 s). Here
      XV-R000 closes on a 300 m3/h receipt into TK-101 (9 m): the segment E001 + E002 is cut off
      with a head a few metres above the tank and relaxes to the tank head, which the open
      XV-R101 gives to the header beyond the valve. The target is constant (no flow after the
      closure), so the closed form is exact for the model.
    * Standby branch. With pump A delivering, pump B's discharge-side segment sits behind a
      closed XV-PBI and takes the head of the suction tee: its pressure is rho g (H_tee - z).
Independence: the closed form is independent of the code; heads are read from written rows.

Source: ``docs/design_decisions.md`` D39.
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
    """Pump B's discharge-side segment relaxes (60 s per stage, two stages: E-PB1 to the open
    tee side, then E-PB2 to E-PB1) toward the tee head, which falls with the tank level; on a
    ramp the lag of two first-order stages is 2 tau |dH/dt|. The reading therefore equals
    rho g (H_tee - z) within that lag (hand: 2 x 60 s x 1.2e-4 m/s = 14 mm = 106 Pa)."""
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
    """All 16 lineups, three seconds each: every edge has end pressures and every tap a value."""
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
