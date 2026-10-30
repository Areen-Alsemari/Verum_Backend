"""Valve restriction, pump head degradation and misrouting.

Steady solves with a restricted valve, a scaled pump curve and a forced lineup are compared with a
separate series-path reference, and short engine runs check the ramps and the open contact. The
valve-law values and the reference solves are derived in the "Valve restriction, pump degradation
and misrouting" section of the verification notes.

See D61, D62, D64 and D74.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from scipy.optimize import brentq

import _fault_cases as fc
import _reference_hydraulics as ref
from verum.contracts.errors import ContractError
from verum.faults import FaultSet, FaultSpec
from verum.graph import Lineup
from verum.hydraulics import DeliveryBoundary, HydraulicModel, ReceiptBoundary, SteadyInputs
from verum.sensors.adapter import _contact_changes

C_REFERENCE = 10.0609
TANK2 = Lineup.of({"XV-S102", "XV-PAI", "XV-PAO"}, {"P-101A"})


def delivery_flow(
    model: HydraulicModel, positions: dict[str, float] | None = None, scale: float = 1.0
) -> float:
    pump = model.default_pump()
    pump = dataclasses.replace(pump, h0_m=pump.h0_m * scale, k_m=pump.k_m * scale)
    r = model.solve(
        SteadyInputs(
            TANK2,
            {"TK-102": 7.0},
            "RVP_9_0",
            25.0,
            fitting_profile="reference_fittings",
            delivery=DeliveryBoundary(law_coefficient_m=C_REFERENCE),
            pump=pump,
            valve_positions=positions or {},
        )  # fmt: skip
    )
    assert r.pump is not None
    return r.pump.flow_m3h


def reference_flow(scale: float, extra_k: float = 0.0) -> float:
    segments = ref.tank2_reference_fittings_segments()
    if extra_k:
        segments = [*segments, (ref.D200, 0.0, extra_k)]

    def f(q: float) -> float:
        need = ref.required_head(q, 7.0, C_REFERENCE, 200000.0, segments)
        return scale * (54.0 - 12.0 * (q * 3600.0 / 300.0) ** 2) - need

    return float(brentq(f, 1e-6, 0.5, xtol=1e-14)) * 3600.0


@pytest.mark.parametrize(("alpha", "k"), [(0.5, 5.0), (0.9, 0.2187), (0.15, 77.3)])
def test_the_loss_at_a_stuck_opening_is_the_d19_hand_value(
    model: HydraulicModel, alpha: float, k: float
) -> None:
    """The loss coefficient of a valve at a stuck opening equals the hand value of the valve law.
    Independent: yes, because the value is hand arithmetic.
    """
    assert model.valve_extra_k(alpha) + 0.1 == pytest.approx(k, rel=1e-3)


def test_the_delivery_flow_falls_monotonically_with_the_opening(model: HydraulicModel) -> None:
    """The delivery flow falls as the valve opening is reduced, and is 300 m3/h when fully open.
    Independent: yes, because only the direction and the design flow are checked.
    """
    flows = [delivery_flow(model, {"XV-S102": a}) for a in (1.0, 0.9, 0.7, 0.5, 0.3, 0.15)]
    assert all(b < a for a, b in zip(flows, flows[1:], strict=False))
    assert flows[0] == pytest.approx(300.0, abs=0.05)


def test_the_restricted_valve_loss_and_contact_in_an_engine_run(model: HydraulicModel) -> None:
    """In an engine run a restricted valve shows the ceiling opening, its loss coefficient, and the
    release of the open contact at the hand-computed time. Independent: yes, because the times and
    loss follow from the valve law by hand.
    """
    spec = FaultSpec(
        "VALVE_RESTRICTION",
        "restriction",
        "XV-S101",
        300.0,
        30.0,
        0.5,
        fault_mode="position_visible",
    )
    e, outcome = fc.run(model, "S0-A", 500.0, FaultSet((spec,)))
    assert outcome.rejection is None
    rows: Any = e.sink.rows["hydraulic_state"]  # type: ignore[attr-defined]
    valve = [r for r in rows if r["record_type"] == "valve_state" and r["element_id"] == "XV-S101"]
    last = [r for r in valve if r["t_sim_s"] == 400.0 and r["side"] is None][0]["payload"]
    assert last["position_frac"] == pytest.approx(0.5, abs=1e-12)
    assert last["commanded_open"] is True and last["physically_closed"] is False
    assert last["k_loss"] == pytest.approx(5.0, rel=1e-9)  # hand: 0.1 x 50
    series = [(r["t_sim_s"], r["side"], r["payload"]) for r in valve]
    changes = _contact_changes(series, 0.98, 0.97)
    assert changes[0] == (0.0, 1) and len(changes) == 2 and changes[1][1] == 0
    assert changes[1][0] == pytest.approx(301.8, abs=0.05)


def _restricted_delivery(model: HydraulicModel, mode: str | None) -> tuple[Any, float, float]:
    """TK-102 delivering through XV-S102 with a ceiling of 0.5 from 300 s; flow and tank level
    at 480 s."""
    spec = FaultSpec(
        "VALVE_RESTRICTION", "restriction", "XV-S102", 300.0, 30.0, 0.5, fault_mode=mode
    )
    e, outcome = fc.run(
        model, "S0-A", 500.0, FaultSet((spec,)), initial_mode="DELIVER_102_A",
        tank_levels_m={"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0},
    )  # fmt: skip
    assert outcome.rejection is None
    rows: Any = e.sink.rows["hydraulic_state"]  # type: ignore[attr-defined]
    flow = next(
        r["payload"]["flow_m3s"] * 3600.0
        for r in rows
        if r["t_sim_s"] == 480.0 and r["side"] is None and r["record_type"] == "pump_state"
        and r["element_id"] == "P-101A"
    )  # fmt: skip
    level = next(
        r["payload"]["level_m"]
        for r in rows
        if r["t_sim_s"] == 480.0 and r["side"] is None and r["record_type"] == "tank_state"
        and r["element_id"] == "TK-102"
    )  # fmt: skip
    return e, flow, level


@pytest.mark.parametrize("mode", ["position_visible", "obstruction"])
def test_both_restriction_modes_reduce_the_flow_by_the_d19_hand_value(
    model: HydraulicModel, mode: str
) -> None:
    """Both restriction modes reduce the delivery flow as the loss of the ceiling opening does,
    because the loss follows the ceiling in both. Independent: yes, because the reference solves the
    series path with a separate root find.
    """
    _, flow, level = _restricted_delivery(model, mode)
    # The tank has fallen from 7 m to the level of the row, so the reference is solved there.
    segments = [*ref.tank2_reference_fittings_segments(), (ref.D200, 0.0, 4.9)]

    def residual(q: float) -> float:
        need = ref.required_head(q, level, C_REFERENCE, 200000.0, segments)
        return float(54.0 - 12.0 * (q * 3600.0 / 300.0) ** 2 - need)

    expected = float(brentq(residual, 1e-6, 0.5, xtol=1e-14)) * 3600.0
    assert flow == pytest.approx(expected, rel=2e-4)
    assert flow < 300.0 - 1.0


def test_the_contact_reads_open_for_an_obstruction_and_not_open_for_a_visible_restriction(
    model: HydraulicModel,
) -> None:
    """An obstruction leaves the open contact asserted while a visible restriction releases it.
    Independent: yes, because the expected contact states follow from the contact thresholds.
    """
    def contact(mode: str) -> list[tuple[float, int]]:
        e, _, _ = _restricted_delivery(model, mode)
        rows: Any = e.sink.rows["hydraulic_state"]
        valve = [
            r for r in rows if r["record_type"] == "valve_state" and r["element_id"] == "XV-S102"
        ]
        late = [r for r in valve if r["t_sim_s"] == 480.0 and r["side"] is None][0]["payload"]
        if mode == "obstruction":
            assert late["position_frac"] == pytest.approx(0.5) and late["k_loss"] == pytest.approx(
                5.0
            )
            assert late["contact_position_frac"] == pytest.approx(1.0)  # the stem is open
        else:
            assert "contact_position_frac" not in late
        series = [(r["t_sim_s"], r["side"], r["payload"]) for r in valve]
        return _contact_changes(series, 0.98, 0.97)

    assert contact("obstruction") == [(0.0, 1)]  # the contact never releases
    visible = contact("position_visible")
    assert len(visible) == 2 and visible[1][1] == 0  # released as the opening falls below 0.97
    assert visible[1][0] == pytest.approx(301.8, abs=0.05)


def test_a_restriction_without_a_mode_is_refused_when_injected(model: HydraulicModel) -> None:
    """A restriction that names no mode is refused when it is injected. Independent: yes, because
    the expected outcome is the refusal rule.
    """
    with pytest.raises(ContractError, match="mode"):
        _restricted_delivery(model, None)


@pytest.mark.parametrize("scale", [1.0, 0.9, 0.7])
def test_the_operating_point_with_a_scaled_curve_is_the_closed_form_series_solve(
    model: HydraulicModel, scale: float
) -> None:
    """The delivery flow with a scaled pump curve equals the root of the series-path equation.
    Independent: yes, because the reference module solves the path by a scalar root find without
    importing the package.
    """
    assert delivery_flow(model, scale=scale) == pytest.approx(reference_flow(scale), rel=2e-4)


def test_the_delivery_flow_falls_monotonically_with_the_head_scale(model: HydraulicModel) -> None:
    """The delivery flow falls as the pump head scale is reduced. Independent: yes, because only the
    direction is checked.
    """
    flows = [delivery_flow(model, scale=s) for s in (1.0, 0.98, 0.9, 0.8, 0.7)]
    assert all(b < a for a, b in zip(flows, flows[1:], strict=False))


def test_the_pump_ramp_in_an_engine_run_follows_the_scaled_curve(model: HydraulicModel) -> None:
    """During an engine run the delivery flow follows the scaled pump curve while the head scale
    ramps. Independent: yes, because the expected flow is solved by the reference module.
    """
    spec = FaultSpec("PUMP_HEAD_DEGRADATION", "head_scale", "P-101A", 200.0, 30.0, 0.8)
    e, outcome = fc.run(
        model, "S0-A", 400.0, FaultSet((spec,)), initial_mode="DELIVER_102_A",
        tank_levels_m={"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0},
    )  # fmt: skip
    assert outcome.rejection is None
    rows: Any = e.sink.rows["hydraulic_state"]  # type: ignore[attr-defined]
    at300 = [r for r in rows if r["t_sim_s"] == 300.0 and r["side"] is None]
    level = next(
        r["payload"]["level_m"]
        for r in at300
        if r["record_type"] == "tank_state" and r["element_id"] == "TK-102"
    )
    flow = next(
        r["payload"]["flow_m3s"] * 3600
        for r in at300
        if r["record_type"] == "pump_state" and r["element_id"] == "P-101A"
    )

    def f(q: float) -> float:
        need = ref.required_head(
            q, level, C_REFERENCE, 200000.0, ref.tank2_reference_fittings_segments()
        )
        return 0.8 * (54.0 - 12.0 * (q * 3600.0 / 300.0) ** 2) - need

    assert flow == pytest.approx(float(brentq(f, 1e-6, 0.5, xtol=1e-14)) * 3600.0, rel=2e-3)


def test_misrouting_a_two_receipt_branches_split_as_the_reference_roots(
    model: HydraulicModel,
) -> None:
    """With both receipt branches forced open the flow splits as the roots of the two branch
    equations. Independent: yes, because the split is solved by the reference module.
    """
    levels = {"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0}
    lineup = Lineup.of({"XV-R000", "XV-R101", "XV-R102"}, set())
    r = model.solve(
        SteadyInputs(
            lineup,
            levels,
            "RVP_9_0",
            25.0,
            fitting_profile="pipe_only",
            receipt=ReceiptBoundary(flow_m3h=600.0),
        )  # fmt: skip
    )
    expected, _ = ref.receipt_flows(levels, ["TK-101", "TK-102"])
    assert r.tank_net_inflow_m3s["TK-101"] * 3600 == pytest.approx(expected[0], rel=1e-3)
    assert r.tank_net_inflow_m3s["TK-102"] * 3600 == pytest.approx(expected[1], rel=1e-3)


def test_misrouting_b_a_stuck_pump_branch_valve_matches_the_reference_loss(
    model: HydraulicModel,
) -> None:
    """A pump branch valve stuck nearly closed adds the hand-computed loss coefficient and gives the
    reference flow. Independent: yes, because the coefficient is hand arithmetic and the flow comes
    from the reference module.
    """
    k_stuck = 0.1 / (0.4 * 50.0**-0.95) ** 2
    assert k_stuck == pytest.approx(1056.7, rel=1e-3)
    got = delivery_flow(model, {"XV-PAO": 0.02})
    assert got == pytest.approx(reference_flow(1.0, extra_k=k_stuck - 0.1), rel=2e-3)


def test_a_head_degradation_of_the_stopped_pump_changes_nothing(model: HydraulicModel) -> None:
    """A head fault on the stopped pump leaves every truth row unchanged, while the same fault on
    the running pump changes them. Independent: yes, because the comparison is between a healthy and
    a faulted run.
    """
    spec = FaultSpec("PUMP_HEAD_DEGRADATION", "head_scale", "P-101B", 100.0, 30.0, 0.7)
    healthy, _ = fc.run(model, "S0-A", 400.0)
    faulted, outcome = fc.run(model, "S0-A", 400.0, FaultSet((spec,)))
    assert outcome.rejection is None
    assert healthy.sink.rows == faulted.sink.rows  # type: ignore[attr-defined]
    running = FaultSpec("PUMP_HEAD_DEGRADATION", "head_scale", "P-101A", 100.0, 30.0, 0.7)
    changed, _ = fc.run(model, "S0-A", 400.0, FaultSet((running,)))
    rows_changed: Any = changed.sink.rows["hydraulic_state"]  # type: ignore[attr-defined]
    rows_healthy: Any = healthy.sink.rows["hydraulic_state"]  # type: ignore[attr-defined]
    assert rows_changed != rows_healthy
