"""Pipe leak: the orifice law, mass conservation, rejection and the transient check.

The leak flow is compared with the hand-evaluated orifice formula, the tank and node balances are
checked with a suction-side and a delivery-side leak, and a leak ramped over 300 s is compared with
the transient engine. The derivations and the tolerance are in the "Pipe leak" section of the
verification notes.

See D10 and D60.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

import _fault_cases as fc
from verum.graph import Lineup
from verum.hydraulics import HydraulicModel, LeakInput, SteadyInputs
from verum.hydraulics.leaks import OrificeLaw
from verum.lineups import load_lineup_table
from verum.sim.engine import Rejected
from verum.transient import TransientEngine, TransientSpec

CD, RHO, G = 0.62, 750.0, 9.80665
DELIVERY = Lineup.of({"XV-S101", "XV-PAI", "XV-PAO"}, {"P-101A"})


def solve(model: HydraulicModel, leaks: list[LeakInput]) -> Any:
    return model.solve(
        SteadyInputs(
            DELIVERY,
            {"TK-101": 9.0},
            "RVP_9_0",
            25.0,
            fitting_profile="reference_fittings",
            leaks=tuple(leaks),
        )  # fmt: skip
    )


def test_the_orifice_law_at_a_fixed_pressure_by_hand() -> None:
    """The orifice law gives the hand-computed flow at 200 kPa. Independent: yes, because the
    expected value is hand arithmetic.
    """
    law = OrificeLaw(CD * 1.0e-3 * math.sqrt(2.0 * G))
    q = law.flow(200000.0 / (RHO * G))
    assert q == pytest.approx(0.014318, abs=2e-6)
    assert q == pytest.approx(CD * 1.0e-3 * math.sqrt(2 * 200000.0 / RHO), rel=1e-12)


def test_doubling_the_area_doubles_the_flow_at_fixed_pressure() -> None:
    """Doubling the area doubles the flow at a fixed head, and the flow is zero at zero or negative
    head. Independent: yes, because the law is linear in the area by construction of the formula.
    """
    delta = 25.0
    one, two = OrificeLaw(0.6 * 5e-4), OrificeLaw(0.6 * 1e-3)
    assert two.flow(delta) == pytest.approx(2.0 * one.flow(delta), rel=1e-14)
    assert one.flow(0.0) == 0.0 and one.flow(-3.0) == 0.0  # outward flow only


@pytest.mark.parametrize(("edge", "area"), [("E-PA3", 5e-4), ("E-S101a", 2e-4)])
def test_the_solved_leak_flow_is_the_orifice_flow_at_the_solved_pressure(
    model: HydraulicModel, edge: str, area: float
) -> None:
    """The leak flow of the network solve equals the orifice formula at the pressure the solve
    found. Independent: no, because the pressure comes from the solve and only the formula is
    independent.
    """
    r = solve(model, [LeakInput(edge, 0.5, area, CD)])
    p = r.leak_pressures_pa_gauge[edge]
    assert p > 10000.0
    assert r.leak_flows_m3s[edge] == pytest.approx(CD * area * math.sqrt(2.0 * p / RHO), rel=1e-9)


@pytest.mark.parametrize("cd", [0.5, 0.8])
def test_the_leak_depends_only_on_the_product_of_the_coefficient_and_the_area(
    model: HydraulicModel, cd: float
) -> None:
    """Two leaks with the same product of discharge coefficient and area give the same flows.
    Independent: yes, because the identity follows from the formula.
    """
    area = 3e-4
    a = solve(model, [LeakInput("E-PA3", 0.5, area, cd)])
    b = solve(model, [LeakInput("E-PA3", 0.5, area * cd / 0.62, 0.62)])
    assert a.leak_flows_m3s["E-PA3"] == pytest.approx(b.leak_flows_m3s["E-PA3"], rel=1e-9)
    assert a.pump.flow_m3h == pytest.approx(b.pump.flow_m3h, rel=1e-9)


def test_the_tank_gives_up_the_pump_flow_plus_a_suction_leak_and_nodes_balance(
    model: HydraulicModel,
) -> None:
    """The tank gives up the pump flow plus a suction-side leak, and the pump flow equals the
    boundary flow plus a delivery-side leak. Independent: yes, because the balances are conservation
    statements.
    """
    r = solve(model, [LeakInput("E-S101a", 0.5, 4e-4, CD)])
    leak = r.leak_flows_m3s["E-S101a"]
    assert -r.tank_net_inflow_m3s["TK-101"] == pytest.approx(
        r.pump.flow_m3h / 3600.0 + leak, rel=1e-9
    )
    assert r.max_mass_residual_kg_s < 4.2e-4  # the configured node tolerance
    d = solve(model, [LeakInput("E-PA3", 0.5, 4e-4, CD)])
    boundary = d.edge_flows_m3s["E-D2"]
    assert d.pump.flow_m3h / 3600.0 == pytest.approx(boundary + d.leak_flows_m3s["E-PA3"], rel=1e-9)


def test_the_engine_ledger_closes_with_the_spill_and_detects_a_double_subtraction(
    model: HydraulicModel,
) -> None:
    """The engine ledger closes with the spilled mass and fails when the spill is subtracted twice.
    Independent: yes, because the spilled mass is a hand estimate and the double subtraction is
    injected.
    """
    e, outcome = fc.run(model, "S0-A", 1000.0, fc.leak("E-PA3", 5e-4, 300.0, 30.0))
    assert outcome.rejection is None and outcome.ledger["closed"]
    spilled = e.state.cum_spilled_m3 * model.rho
    # Hand: about 33 m3/h for 670 s after the end of the ramp, plus half of it during the ramp.
    assert spilled == pytest.approx(33.0 / 3600.0 * 685.0 * model.rho, rel=0.05)
    assert e._ledger(e.state.t)["spilled_kg"] == pytest.approx(spilled)
    e.state.cum_spilled_m3 *= 2.0  # the same mass subtracted twice
    assert not e._ledger(e.state.t)["closed"]


def test_a_leak_below_the_minimum_gauge_pressure_is_rejected(model: HydraulicModel) -> None:
    """A leak at less than 10 kPa gauge is rejected by the fault gate. Independent: yes, because the
    limit is the stated rule.
    """
    e, outcome = fc.run(model, "S0-A", 400.0, fc.leak("E-PA3", 5e-4, 300.0, 30.0))
    assert outcome.rejection is None
    result = e.state.current
    assert result is not None
    low = {"E-PA3": 9000.0}
    import dataclasses

    with pytest.raises(Rejected) as exc:
        e._check_leaks(400.0, dataclasses.replace(result, leak_pressures_pa_gauge=low))
    assert exc.value.record["gate"] == "SGF" and exc.value.record["limit"] == 10000.0
    e._check_leaks(400.0, dataclasses.replace(result, leak_pressures_pa_gauge={"E-PA3": 11000.0}))


def test_a_leak_on_an_edge_without_a_determined_pressure_is_rejected(model: HydraulicModel) -> None:
    """A leak on an edge that carries no determined pressure is rejected by the fault gate.
    Independent: yes, because the expected outcome is the rejection rule.
    """
    _, outcome = fc.run(model, "S0-A", 400.0, fc.leak("E-R102a", 5e-4, 300.0, 30.0))
    assert outcome.rejection is not None and outcome.rejection["gate"] == "SGF"
    assert "no determined pressure" in outcome.rejection["detail"]


@pytest.mark.slow
def test_a_leak_ramped_over_300_s_agrees_with_the_transient_engine(model: HydraulicModel) -> None:
    """A leak ramped over 300 s gives the same leak flow in the rigid-column engine and in the
    transient engine within the hand-derived tolerance. Independent: no, because the transient
    engine is a separate model of the same equations and not independent validation.
    """
    onset, ramp, area = 100.0, 300.0, 5e-4
    e, outcome = fc.run(
        model, "S0-B", 460.0, fc.leak("E003", area, onset, ramp, 0.95),
        receipt_flow_m3h=600.0, receipt_setpoint_m3h=600.0,
    )  # fmt: skip
    assert outcome.rejection is None and outcome.ledger["closed"]
    rigid = fc.edge_series(e, "E003", "leak_flow_m3s")
    level = next(
        r["payload"]["level_m"]
        for r in e.sink.rows["hydraulic_state"]  # type: ignore[attr-defined]
        if r["record_type"] == "tank_state"
        and r["element_id"] == "TK-101"
        and r["t_sim_s"] == 450.0
    )
    lineup = load_lineup_table(model.topology).mode("RECEIVE_101").lineup
    spec = TransientSpec(
        lineup=lineup, tank_levels_m={"TK-101": level, "TK-102": 7.0, "TK-103": 5.0},
        fitting_profile="reference_fittings", receipt_flow_m3h=600.0, receipt_setpoint_m3h=600.0,
        leak=("RECEIPT_HEADER", CD * area * math.sqrt(2.0 * G)), leak_ramp=(onset, ramp),
    )  # fmt: skip
    t = TransientEngine(model, spec)
    marks = {}
    while t.t < 450.0 + 1e-9:
        t.step()
        for target in (190.0, 200.0, 290.0, 300.0, 440.0, 450.0):
            if abs(t.t - target) < 0.5 * t.dt:
                marks[target] = t.ledger.leak_m3
    final = rigid[450.0]
    assert final > 0.0
    for lo, hi in ((190.0, 200.0), (290.0, 300.0), (440.0, 450.0)):
        transient = (marks[hi] - marks[lo]) / 10.0
        mean = sum(rigid[float(x)] for x in range(int(lo), int(hi) + 1)) / 11.0
        assert transient == pytest.approx(mean, abs=0.015 * final), (hi, transient, mean, final)
