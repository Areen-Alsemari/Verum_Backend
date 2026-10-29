"""Static pressures, pressure basis and the NPSH reference values.

Inputs: ``HydraulicModel`` and literal document values. Outputs: pass/fail.

Derivations:
    * Static pressure at a tap: p = rho g (H - z) - rho v^2 / 2, with the
      velocity of the tap's reference edge. At the pump suction tee the
      reference edge is the DN250 header, A = pi 0.25446^2 / 4 = 0.050853 m2;
      at 300 m3/h v = 1.6388 m/s and v^2/(2g) = 0.13691 m (document: 0.136908).
    * PT-201 at 300 m3/h and 1.8 m, pipe-only: head at the tee is
      1.8 - losses(tank branch, header); the document values are
      -0.046 / -0.102 / -0.157 barg for TK-101 / 102 / 103.
    * Across the pump (same bore, same elevation, same velocity) the static
      pressure rises by exactly rho g times the head rise.
    * NPSHa at TK-102, 7 m, 25 C, 300 m3/h: (101325 - 49199)/(rho g) + (7 - 0.5)
      - losses = 10.79 m (document section 4). The solved flow of that case is
      300.0 m3/h, so the document's fixed 300 m3/h applies.
    * Vapor pressures of the reference correlation: 35.065 / 49.199 / 67.530 /
      90.863 kPa at 15 / 25 / 35 / 45 C (document section 1.1).
Independence: the document values are from the audit; the identities are hand
arithmetic. The tap formula is the one the package implements (stated in the
task), so the check on it is the identities and the document numbers.

Source: ``revised/02_hydraulic_model.md`` sections 1.1 and 4.
"""

from __future__ import annotations

import math

import pytest
from scipy.optimize import brentq

from _hydraulic_cases import SCENARIO, VariableSpeedPump, delivery_case
from verum.graph import Lineup
from verum.hydraulics import (
    HydraulicModel,
    PropertyScenarioRequired,
    SteadyInputs,
)
from verum.hydraulics.properties import vapor_pressure_pa

RHO, G, PATM = 750.0, 9.80665, 101325.0
D250 = 0.25446


def _at_300(model: HydraulicModel, tank: str, level: float):  # type: ignore[no-untyped-def]
    def excess(s: float) -> float:
        pump = VariableSpeedPump(s, enforce_domain=False)
        point = model.solve(delivery_case(tank, level, law=0.0, pump_element=pump)).pump
        assert point is not None
        return point.flow_m3h - 300.0

    s = float(brentq(excess, 0.5, 1.2, xtol=1e-12))
    return model.solve(
        delivery_case(tank, level, law=0.0, pump_element=VariableSpeedPump(s, False))
    )


@pytest.mark.parametrize(
    ("tank", "document_bar"), [("TK-101", -0.046), ("TK-102", -0.102), ("TK-103", -0.157)]
)
def test_pt201_static_pressure_at_1_8_m_and_300_m3h(
    model: HydraulicModel, tank: str, document_bar: float
) -> None:
    result = _at_300(model, tank, 1.8)
    tee = result.tap_pressures_pa_gauge["PUMP_SUCTION_TEE"]
    assert tee / 1e5 == pytest.approx(document_bar, abs=0.0006)
    velocity = result.edge_flows_m3s["E-SH"] / (math.pi * D250**2 / 4)
    assert velocity**2 / (2 * G) == pytest.approx(0.136908, abs=2e-5)
    head = result.node_heads_m["PUMP_SUCTION_TEE"]
    assert tee == pytest.approx(RHO * G * (head - 0.5) - RHO * velocity**2 / 2, rel=1e-12)
    assert result.to_abs(tee) == pytest.approx(tee + PATM)
    assert result.to_abs(tee) > 0  # absolute pressure stays positive while gauge is negative


def test_pressure_rise_across_the_pump_is_rho_g_times_the_head_rise(model: HydraulicModel) -> None:
    result = model.solve(delivery_case("TK-102", 7.0))
    assert result.pump is not None
    inlet = result.edge_end_pressures_pa_gauge["E-PA1"][1]
    outlet = result.edge_end_pressures_pa_gauge["E-PA2"][0]
    assert outlet - inlet == pytest.approx(RHO * G * result.pump.head_rise_m, rel=1e-9)


def test_still_fluid_has_the_hydrostatic_pressure_of_its_tank(model: HydraulicModel) -> None:
    inputs = SteadyInputs(Lineup.of({"XV-S101"}), {"TK-101": 9.0}, SCENARIO, 25.0)
    result = model.solve(inputs)
    assert result.active_edges == frozenset()
    assert result.tap_pressures_pa_gauge["PUMP_SUCTION_TEE"] == pytest.approx(
        RHO * G * (9.0 - 0.5), rel=1e-12
    )
    assert result.edge_end_pressures_pa_gauge["E-S101a"][0] == pytest.approx(
        RHO * G * (9.0 - 0.4), rel=1e-12
    )
    assert result.node_heads_m["SUCTION_HEADER"] == 9.0


@pytest.mark.parametrize(("tank", "level", "document"), [("TK-102", 7.0, 10.79)])
def test_npsha_at_25_c_matches_the_document(
    model: HydraulicModel, tank: str, level: float, document: float
) -> None:
    result = model.solve(delivery_case(tank, level))
    assert result.pump is not None and result.pump.flow_m3h == pytest.approx(300.0, abs=0.05)
    assert result.phase.npsha_m == pytest.approx(document, abs=0.01)


def test_npsha_at_45_c_matches_the_document(model: HydraulicModel) -> None:
    result = model.solve(delivery_case("TK-102", 7.0, temperature_c=45.0))
    assert result.phase.npsha_m == pytest.approx(5.13, abs=0.01)


def test_npsha_is_computed_from_the_pump_inlet_head(model: HydraulicModel) -> None:
    result = model.solve(delivery_case("TK-103", 5.0))
    assert result.pump is not None and result.phase.npsha_m is not None
    inlet = result.node_heads_m["P-101A:in"]
    expected = (PATM - result.phase.vapor_pressure_pa_abs) / (RHO * G) + (inlet - 0.5)
    assert result.phase.npsha_m == pytest.approx(expected, rel=1e-12)
    assert result.phase.npsh3_m == pytest.approx(
        4.0 * (result.pump.flow_m3h / 300.0) ** 2, rel=1e-12
    )
    assert result.phase.npsh3_m is not None
    assert result.phase.margin_ratio == pytest.approx(result.phase.npsha_m / result.phase.npsh3_m)


@pytest.mark.parametrize(
    ("celsius", "kpa"), [(15.0, 35.065), (25.0, 49.199), (35.0, 67.530), (45.0, 90.863)]
)
def test_vapor_pressure_of_the_reference_scenario(
    model: HydraulicModel, celsius: float, kpa: float
) -> None:
    value = vapor_pressure_pa(SCENARIO, celsius, model.config, model.fluid)
    assert value / 1000 == pytest.approx(kpa, abs=0.002)


def test_temperature_strata_are_25_35_45(model: HydraulicModel) -> None:
    assert [model.config.temperature_c(k) for k in ("25", "35", "45")] == [25.0, 35.0, 45.0]


@pytest.mark.parametrize(
    "scenario", [None, "", "NO_SUCH_SCENARIO", "EPA_GENERIC_MOTOR_GASOLINE_RVP10"]
)
def test_without_a_known_scenario_vapor_pressure_is_refused(
    model: HydraulicModel, scenario: str | None
) -> None:
    with pytest.raises(PropertyScenarioRequired):
        vapor_pressure_pa(scenario, 25.0, model.config, model.fluid)
