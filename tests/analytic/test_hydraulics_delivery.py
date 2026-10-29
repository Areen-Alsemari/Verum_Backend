"""Delivery side: network against closed-form series solves, required head, D2 points.

Inputs: ``HydraulicModel`` and the independent series-path solver in
``_reference_hydraulics``. Outputs: pass/fail.

Derivations (independent of the package, except where stated):
    * Closed-form series solve: the delivery path is one series line (tank,
      suction branch, DN250 header, pump branch, distribution main). The pump
      head equals the static difference plus the boundary law plus the summed
      Darcy losses; the operating flow is the root of that scalar equation
      (brentq). This is a different method from the node-head Newton solve.
    * Required pump head at 300 m3/h, pipe-only, fixed 2 barg boundary:
      H = 200000/(rho g) + (0.5 - h) + losses(300 m3/h); with 27.19 m of
      boundary head, 8.589 m of losses and h = 9 m this is 27.281 m (audited
      document); the speed ratio follows from 54 s^2 - 12 = H.
    * Reference-fittings TK-102 path: total K counted by hand (see
      ``_reference_hydraulics.tank2_reference_fittings_segments``).
    * Document values quoted below come from the audited reference package.
      The D2 operating points (312.6, 300.0, 287.5 m3/h) come from the audited
      reference script with the D2 resistance added (decision record D2).
Independence of the friction law: same law as the package (see
``test_hydraulics_friction.py``).

Source: ``revised/02_hydraulic_model.md`` sections 3.1, 3.2; decision D2 (v3.0).
"""

from __future__ import annotations

import pytest

import _reference_hydraulics as ref
from _hydraulic_cases import INITIAL_LEVELS, TANKS, VariableSpeedPump, delivery_case
from verum.hydraulics import HydraulicModel, PumpOutsideCurve, load_boundary_law_coefficient

LEVEL_CASES = [(t, h) for t, h in INITIAL_LEVELS.items()] + [(t, 1.8) for t in TANKS]
C_PIPE_ONLY = load_boundary_law_coefficient("pipe_only").value


@pytest.mark.parametrize(("tank", "level"), LEVEL_CASES)
@pytest.mark.parametrize("pump", ["A", "B"])
def test_network_flow_equals_the_closed_form_series_solve(
    model: HydraulicModel, tank: str, level: float, pump: str
) -> None:
    result = model.solve(delivery_case(tank, level, pump=pump))
    expected = ref.operating_flow_m3h(level, C_PIPE_ONLY, ref.delivery_segments(tank))
    assert result.pump is not None
    assert result.pump.flow_m3h == pytest.approx(expected, rel=1e-6)
    assert result.pump.head_rise_m == pytest.approx(ref.pump_head(expected / 3600), abs=1e-5)


@pytest.mark.parametrize(
    ("tank", "level", "document"),
    [("TK-101", 9.0, 312.6), ("TK-102", 7.0, 300.0), ("TK-103", 5.0, 287.5)],
)
def test_d2_operating_points_pipe_only(
    model: HydraulicModel, tank: str, level: float, document: float
) -> None:
    result = model.solve(delivery_case(tank, level))
    assert result.pump is not None
    assert result.pump.flow_m3h == pytest.approx(document, abs=0.1)


def test_tk102_at_7_m_runs_at_300_with_42_m(model: HydraulicModel) -> None:
    pump = model.solve(delivery_case("TK-102", 7.0)).pump
    assert pump is not None
    assert pump.flow_m3h == pytest.approx(300.0, abs=0.05)
    assert pump.head_rise_m == pytest.approx(42.0, abs=0.01)


def test_pipe_only_coefficient_is_11_96(model: HydraulicModel) -> None:
    assert C_PIPE_ONLY == pytest.approx(11.96, abs=0.005)


@pytest.mark.parametrize("pump", ["A", "B"])
def test_reference_fittings_closed_form_for_tk102(model: HydraulicModel, pump: str) -> None:
    c = load_boundary_law_coefficient("reference_fittings").value
    result = model.solve(delivery_case("TK-102", 7.0, profile="reference_fittings", pump=pump))
    expected = ref.operating_flow_m3h(7.0, c, ref.tank2_reference_fittings_segments())
    assert result.pump is not None
    assert result.pump.flow_m3h == pytest.approx(expected, rel=1e-6)
    assert result.pump.flow_m3h == pytest.approx(300.0, abs=0.05)


def test_reference_fittings_reduce_the_flow_at_equal_boundary_law(model: HydraulicModel) -> None:
    pipe = model.solve(delivery_case("TK-102", 7.0, law=C_PIPE_ONLY)).pump
    fit = model.solve(
        delivery_case("TK-102", 7.0, profile="reference_fittings", law=C_PIPE_ONLY)
    ).pump
    assert pipe is not None and fit is not None
    assert fit.flow_m3h < pipe.flow_m3h


# --- required head and speed ratios: reference-case reproduction -------------------------

REQUIRED = {
    ("TK-101", 9.0): (27.281, 0.853, 351.7),
    ("TK-102", 7.0): (30.037, 0.882, 340.0),
    ("TK-103", 5.0): (32.792, 0.911, 329.4),
    ("TK-101", 1.8): (34.481, None, None),
    ("TK-102", 1.8): (35.237, None, None),
    ("TK-103", 1.8): (35.992, None, None),
}


def _speed_for_300(model: HydraulicModel, tank: str, level: float) -> float:
    """Find s with the permissive-domain test pump so that the network gives 300 m3/h."""
    from scipy.optimize import brentq

    def excess(s: float) -> float:
        pump = VariableSpeedPump(s, enforce_domain=False)
        point = model.solve(delivery_case(tank, level, law=0.0, pump_element=pump)).pump
        assert point is not None
        return point.flow_m3h - 300.0

    return float(brentq(excess, 0.5, 1.2, xtol=1e-12))


@pytest.mark.parametrize(("tank", "level"), list(REQUIRED))
def test_required_head_at_300_m3h_with_fixed_2_barg_boundary(
    model: HydraulicModel, tank: str, level: float
) -> None:
    head, _, _ = REQUIRED[(tank, level)]
    s = _speed_for_300(model, tank, level)
    pump = VariableSpeedPump(s, enforce_domain=False)
    point = model.solve(delivery_case(tank, level, law=0.0, pump_element=pump)).pump
    assert point is not None
    assert point.flow_m3h == pytest.approx(300.0, abs=1e-6)
    assert point.head_rise_m == pytest.approx(head, abs=0.002)
    assert 54 * s * s - 12 == pytest.approx(head, abs=0.002)
    assert s == pytest.approx(ref.speed_for_flow(level, 300, ref.delivery_segments(tank)), abs=1e-7)


@pytest.mark.parametrize(("tank", "level"), [k for k, v in REQUIRED.items() if v[1] is not None])
def test_speed_ratios_and_reference_equivalent_flows(
    model: HydraulicModel, tank: str, level: float
) -> None:
    _, ratio, equivalent = REQUIRED[(tank, level)]
    s = _speed_for_300(model, tank, level)
    assert s == pytest.approx(ratio, abs=0.0006)
    assert 300 / s == pytest.approx(equivalent, abs=0.06)


def test_tk101_k0_speed_is_rejected_because_q_over_s_exceeds_350(model: HydraulicModel) -> None:
    s = _speed_for_300(model, "TK-101", 9.0)
    assert 300 / s > 350
    with pytest.raises(PumpOutsideCurve, match="outside the pump curve"):
        model.solve(delivery_case("TK-101", 9.0, law=0.0, pump_element=VariableSpeedPump(s)))


@pytest.mark.parametrize("tank", ["TK-102", "TK-103"])
def test_tk102_and_tk103_k0_speeds_are_accepted(model: HydraulicModel, tank: str) -> None:
    s = _speed_for_300(model, tank, INITIAL_LEVELS[tank])
    point = model.solve(
        delivery_case(tank, INITIAL_LEVELS[tank], law=0.0, pump_element=VariableSpeedPump(s))
    ).pump
    assert point is not None and point.reference_equivalent_flow_m3h <= 350


# --- boundary law and PT-203 ---------------------------------------------------------------


@pytest.mark.parametrize(("tank", "level"), LEVEL_CASES)
def test_boundary_node_head_and_pt203_pressure(
    model: HydraulicModel, tank: str, level: float
) -> None:
    result = model.solve(delivery_case(tank, level))
    assert result.pump is not None
    q = result.pump.flow_m3h
    dh = C_PIPE_ONLY * (q / 300) ** 2
    rho, g = 750.0, 9.80665
    total = 200000.0 + rho * g * dh  # 2 barg + rho g dH_d (decision D2): total-head pressure
    # The solve stops at 1e-9 m3/s, which leaves heads good to about 1e-8 relative.
    assert rho * g * (result.node_heads_m["DISTRIBUTION_BOUNDARY"] - 0.5) == pytest.approx(
        total, rel=1e-7
    )
    v = result.edge_flows_m3s["E-D2"] / (3.141592653589793 * ref.D200**2 / 4)
    assert result.tap_pressures_pa_gauge["DISTRIBUTION_BOUNDARY"] == pytest.approx(
        total - 0.5 * rho * v * v, rel=1e-7
    )


def test_pt203_varies_with_flow(model: HydraulicModel) -> None:
    pressures = [
        model.solve(delivery_case("TK-102", h)).tap_pressures_pa_gauge["DISTRIBUTION_BOUNDARY"]
        for h in (3.0, 7.0, 12.0)
    ]
    assert pressures[0] < pressures[1] < pressures[2]
    assert pressures[1] / 1e5 == pytest.approx(2.0 + 0.88 - 0.025, abs=0.01)


def test_zero_coefficient_holds_the_boundary_node_at_the_reservoir(model: HydraulicModel) -> None:
    result = model.solve(
        delivery_case("TK-102", 7.0, law=0.0, pump_element=VariableSpeedPump(0.882, False))
    )
    assert 750.0 * 9.80665 * (result.node_heads_m["DISTRIBUTION_BOUNDARY"] - 0.5) == pytest.approx(
        200000.0, rel=1e-12
    )


# --- pump power ---------------------------------------------------------------------------------


def test_pump_power_uses_the_constant_efficiency(model: HydraulicModel) -> None:
    pump = model.solve(delivery_case("TK-102", 7.0)).pump
    assert pump is not None
    q = pump.flow_m3h / 3600
    assert pump.hydraulic_power_w == pytest.approx(750 * 9.80665 * q * pump.head_rise_m, rel=1e-12)
    assert pump.shaft_power_w == pytest.approx(pump.hydraulic_power_w / 0.75, rel=1e-12)
    assert pump.hydraulic_power_w / 1000 == pytest.approx(25.73, abs=0.1)  # 750 g (300/3600) 42 m


def test_pump_curve_values() -> None:
    from verum.hydraulics import FixedSpeedPump

    pump = FixedSpeedPump(54.0, 12.0, 300.0, 350.0, 0.75)
    assert pump.head_rise_m(0.0) == 54.0
    assert pump.head_rise_m(300.0) == 42.0
    assert pump.in_domain(350.0) and not pump.in_domain(350.01) and not pump.in_domain(-0.1)
    assert pump.flow_m3s(-42.0) * 3600 == pytest.approx(300.0, rel=1e-12)
    assert pump.flow_m3s(-54.0) == 0.0 and pump.flow_m3s(-60.0) == 0.0
    with pytest.raises(ValueError):
        FixedSpeedPump(54.0, 12.0, 300.0, 350.0, 0.75, speed_ratio=0.9)


# --- K multiplier sensitivity -------------------------------------------------------------


@pytest.mark.parametrize("multiplier", [0.5, 1.0, 2.0])
def test_k_multiplier_sensitivity_matches_the_closed_form(
    model: HydraulicModel, multiplier: float
) -> None:
    """Independent: the hand-counted K of the TK-102 path is scaled and solved (c fixed)."""
    c = load_boundary_law_coefficient("reference_fittings").value
    segments = [
        (d, length, k * multiplier) for d, length, k in ref.tank2_reference_fittings_segments()
    ]
    expected = ref.operating_flow_m3h(7.0, c, segments)
    result = model.solve(
        delivery_case("TK-102", 7.0, profile="reference_fittings", multiplier=multiplier)
    )
    assert result.pump is not None
    assert result.pump.flow_m3h == pytest.approx(expected, rel=1e-6)


def test_k_multiplier_effect_on_tk102_is_a_few_percent(model: HydraulicModel) -> None:
    flows = {
        m: model.solve(
            delivery_case("TK-102", 7.0, profile="reference_fittings", multiplier=m)
        ).pump
        for m in (0.5, 1.0, 2.0)
    }
    q = {m: p.flow_m3h for m, p in flows.items() if p is not None}
    assert q[0.5] > q[1.0] > q[2.0]
    assert 100 * (q[0.5] / q[1.0] - 1) == pytest.approx(1.47, abs=0.05)
    assert 100 * (q[2.0] / q[1.0] - 1) == pytest.approx(-2.76, abs=0.05)


def test_the_two_profiles_have_equal_flow_at_the_calibration_point(model: HydraulicModel) -> None:
    a = model.solve(delivery_case("TK-102", 7.0, profile="pipe_only")).pump
    b = model.solve(delivery_case("TK-102", 7.0, profile="reference_fittings")).pump
    assert a is not None and b is not None
    assert a.flow_m3h == pytest.approx(300.0, abs=0.05) and b.flow_m3h == pytest.approx(
        300.0, abs=0.05
    )
