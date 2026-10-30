"""Valve restriction, pump head degradation and misrouting (decisions D61, D62, D64).

Inputs: steady solves with a valve opening, a scaled pump curve and a forced lineup, and short
engine runs of the delivery scenario. Outputs: pass/fail.

Derivations (hand arithmetic):
    * Valve loss (D19, D4): K(alpha) = 0.1 (1/Kv_fraction)^2 with Kv_fraction = 50^(alpha - 1)
      above alpha_c = 0.05 and 0.4 x 50^-0.95 = 0.009728 at alpha = 0.02. Hence K(0.5) = 0.1 x 50 =
      5.0, K(0.9) = 0.1 x 50^0.2 = 0.2187, K(0.15) = 0.1 x 50^1.7 = 77.3 and K(0.02) = 1056.7.
    * Pump: H(Q) = h (54 - 12 (Q/300)^2) for a head scale h. The delivery of TK-102 at 7 m with the
      reference fittings has the series path of ``_reference_hydraulics`` (segments counted by
      hand there) and the boundary law with c = 10.0609 m; the operating flow is the root of
      pump head - required head, found by ``brentq`` in the reference module's functions.
    * Misrouting (a): XV-R101 and XV-R102 open with 600 m3/h received and TK-101 at 9 m, TK-102 at
      7 m: the split is the root of the two branch equations in the reference module.
    * Misrouting (b): the pump branch valve XV-PAO at alpha 0.02 adds K(0.02) = 1056.7 at the DN200
      pump branch; the reference path gets a segment with that coefficient and no length.
    * The valve contact (D31) asserts at 0.98 and releases below 0.97: a ceiling of 0.5 reached
      linearly over 30 s from 300 s releases the contact at 300 + 30 x (1 - 0.97) / 0.5 = 301.8 s.
Independence: the reference module solves the series path by a scalar root find and does not
import the package; the valve law values are hand arithmetic.

    * Restriction modes (D74): in both modes the loss is K(0.5) = 5.0 (the valve adds 4.9 to the
      open-valve loss); a visible restriction releases the open contact at 301.8 s, an obstruction
      leaves it asserted.

Source: ``docs/design_decisions.md`` D19, D31, D61, D62, D64, D74; ``docs/fault_models.md``.
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
    assert model.valve_extra_k(alpha) + 0.1 == pytest.approx(k, rel=1e-3)


def test_the_delivery_flow_falls_monotonically_with_the_opening(model: HydraulicModel) -> None:
    flows = [delivery_flow(model, {"XV-S102": a}) for a in (1.0, 0.9, 0.7, 0.5, 0.3, 0.15)]
    assert all(b < a for a, b in zip(flows, flows[1:], strict=False))
    assert flows[0] == pytest.approx(300.0, abs=0.05)


def test_the_restricted_valve_loss_and_contact_in_an_engine_run(model: HydraulicModel) -> None:
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
    """Decision D74: the loss follows the ceiling in both modes. Hand: K(0.5) = 0.1 x 50 = 5.0,
    so the valve adds 5.0 - 0.1 = 4.9 to the open-valve loss, solved by the reference path."""
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
    with pytest.raises(ContractError, match="mode"):
        _restricted_delivery(model, None)


@pytest.mark.parametrize("scale", [1.0, 0.9, 0.7])
def test_the_operating_point_with_a_scaled_curve_is_the_closed_form_series_solve(
    model: HydraulicModel, scale: float
) -> None:
    assert delivery_flow(model, scale=scale) == pytest.approx(reference_flow(scale), rel=2e-4)


def test_the_delivery_flow_falls_monotonically_with_the_head_scale(model: HydraulicModel) -> None:
    flows = [delivery_flow(model, scale=s) for s in (1.0, 0.98, 0.9, 0.8, 0.7)]
    assert all(b < a for a, b in zip(flows, flows[1:], strict=False))


def test_the_pump_ramp_in_an_engine_run_follows_the_scaled_curve(model: HydraulicModel) -> None:
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
    k_stuck = 0.1 / (0.4 * 50.0**-0.95) ** 2
    assert k_stuck == pytest.approx(1056.7, rel=1e-3)
    got = delivery_flow(model, {"XV-PAO": 0.02})
    assert got == pytest.approx(reference_flow(1.0, extra_k=k_stuck - 0.1), rel=2e-3)


def test_a_head_degradation_of_the_stopped_pump_changes_nothing(model: HydraulicModel) -> None:
    """P-101B does not run in S0-A, so a fault on it leaves every truth row unchanged."""
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
