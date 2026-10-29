"""Gates, the check valve, conservation, configuration, fittings and isolation.

Inputs: ``HydraulicModel`` with modified inputs or configuration. Outputs:
pass/fail.
Key assumptions:
    * A rejection is an exception (over-constrained boundary, pump outside its
      curve, no property scenario). A phase or NPSH failure is reported in the
      result and the solved flows are identical to the passing temperature case,
      so nothing is clipped.
    * Node conservation is re-computed here from the edge flows and the
      topology with separate code, not read from the solver's own residuals.
    * Bend positions and loss coefficients are counted by hand from the route
      polylines of the audited document (see the comments).

Source: ``revised/02_hydraulic_model.md`` sections 5 and 8 (gates G2 to G6);
decisions D2, D7, D8, D11, D15.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import pytest

from _hydraulic_cases import (
    INITIAL_LEVELS,
    SCENARIO,
    TANKS,
    VariableSpeedPump,
    deliver_lineup,
    delivery_case,
    receipt_case,
)
from verum.contracts import ContractError, Topology
from verum.graph import Lineup, load_route_geometry
from verum.hydraulics import (
    ConvergenceError,
    DeliveryBoundary,
    HydraulicInputError,
    HydraulicModel,
    OverConstrained,
    PropertyScenarioRequired,
    PumpOutsideCurve,
    ReceiptBoundary,
    SteadyInputs,
    load_boundary_law_coefficient,
    load_fitting_profile,
)
from verum.hydraulics.fittings import bends_per_edge, edge_loss_coefficients
from verum.hydraulics.solver import LossLaw, OneWay
from verum.params import UnresolvedParameter

# --- boundary gates ----------


def test_delivery_flow_with_a_fixed_pump_and_reservoir_is_over_constrained(
    model: HydraulicModel,
) -> None:
    inputs = dataclasses.replace(
        delivery_case("TK-102", 7.0), delivery=DeliveryBoundary(flow_m3h=300.0)
    )
    with pytest.raises(OverConstrained, match="delivery"):
        model.solve(inputs)


def test_receipt_with_flow_and_pressure_is_over_constrained(model: HydraulicModel) -> None:
    inputs = receipt_case(
        ("TK-101",), receipt=ReceiptBoundary(flow_m3h=600.0, pressure_pa_gauge=1e5)
    )
    with pytest.raises(OverConstrained):
        model.solve(inputs)


def test_negative_boundary_values_are_refused(model: HydraulicModel) -> None:
    with pytest.raises(ValueError):
        model.solve(receipt_case(("TK-101",), receipt=ReceiptBoundary(flow_m3h=-1.0)))
    with pytest.raises(ValueError):
        model.solve(delivery_case("TK-102", 7.0, law=-1.0))


def test_an_extrapolated_pump_point_is_rejected(model: HydraulicModel) -> None:
    # Pure fixed 2 barg boundary at the fixed speed: the intersection is at 351 m3/h, beyond 350.
    with pytest.raises(PumpOutsideCurve) as caught:
        model.solve(delivery_case("TK-101", 1.8, law=0.0))
    assert "351" in str(caught.value)


def test_domain_rule_uses_q_over_s(model: HydraulicModel) -> None:
    # At s = 0.9 the flow is about 331 m3/h, below 350, but Q/s is about 368 m3/h, above 350.
    loose = model.solve(
        delivery_case("TK-101", 9.0, law=0.0, pump_element=VariableSpeedPump(0.9, False))
    )
    assert loose.pump is not None
    assert loose.pump.flow_m3h < 350 < loose.pump.reference_equivalent_flow_m3h
    with pytest.raises(PumpOutsideCurve):
        model.solve(delivery_case("TK-101", 9.0, law=0.0, pump_element=VariableSpeedPump(0.9)))


@pytest.mark.parametrize("scenario", [None, "UNKNOWN"])
def test_no_property_scenario_is_rejected(model: HydraulicModel, scenario: str | None) -> None:
    inputs = dataclasses.replace(delivery_case("TK-102", 7.0), scenario=scenario)
    with pytest.raises(PropertyScenarioRequired):
        model.solve(inputs)


def test_phase_failure_is_reported_and_nothing_is_clipped(model: HydraulicModel) -> None:
    cool = model.solve(delivery_case("TK-103", 1.8, temperature_c=25.0))
    hot = model.solve(delivery_case("TK-103", 1.8, temperature_c=45.0))
    assert cool.phase.status == "OK"
    assert hot.phase.status == "SCREEN_FAILED"
    assert hot.phase.npsha_m is not None and hot.phase.npsha_m < 0
    assert hot.gates["G4_phase"] == "SCREEN_FAILED"
    assert dict(hot.edge_flows_m3s) == dict(cool.edge_flows_m3s)  # same hydraulics, same flows
    assert hot.pump is not None and hot.pump.flow_m3h > 0


def test_npsh_margin_failure_is_reported(model: HydraulicModel) -> None:
    result = model.solve(delivery_case("TK-103", 1.8, npsh3=6.0))
    assert result.phase.status == "NPSH_MARGIN_FAILED"
    assert result.phase.margin_ratio is not None and 1.0 < result.phase.margin_ratio < 1.3


def test_screen_failure_takes_precedence_over_margin_failure(model: HydraulicModel) -> None:
    result = model.solve(delivery_case("TK-103", 1.8, temperature_c=45.0, npsh3=6.0))
    assert result.phase.status == "SCREEN_FAILED"


def test_passing_case_is_ok_with_margin_at_least_1_3(model: HydraulicModel) -> None:
    result = model.solve(delivery_case("TK-102", 7.0))
    assert result.phase.status == "OK"
    assert result.phase.margin_ratio is not None and result.phase.margin_ratio >= 1.3


def test_minimum_absolute_pressure_is_reported_with_the_vapor_pressure(
    model: HydraulicModel,
) -> None:
    result = model.solve(delivery_case("TK-102", 7.0, temperature_c=35.0))
    assert result.phase.vapor_pressure_pa_abs == pytest.approx(67530.0, abs=2.0)
    assert result.phase.min_abs_pressure_pa is not None
    assert result.phase.min_abs_pressure_pa > result.phase.vapor_pressure_pa_abs


# --- check valve and standby ----------


def test_an_isolated_standby_branch_carries_zero_flow(model: HydraulicModel) -> None:
    result = model.solve(delivery_case("TK-102", 7.0, pump="A"))
    assert all(result.edge_flows_m3s[f"E-PB{i}"] == 0.0 for i in range(5))
    result_b = model.solve(delivery_case("TK-102", 7.0, pump="B"))
    assert all(result_b.edge_flows_m3s[f"E-PA{i}"] == 0.0 for i in range(5))


def test_an_open_but_stopped_pump_branch_carries_zero_flow(model: HydraulicModel) -> None:
    lineup = Lineup.of({"XV-S102", "XV-PAI", "XV-PAO", "XV-PBI", "XV-PBO"}, {"P-101A"})
    both_open = model.solve(dataclasses.replace(delivery_case("TK-102", 7.0), lineup=lineup))
    single = model.solve(delivery_case("TK-102", 7.0))
    assert all(both_open.edge_flows_m3s[f"E-PB{i}"] == 0.0 for i in range(5))
    assert both_open.pump is not None and single.pump is not None
    assert both_open.pump.flow_m3h == pytest.approx(single.pump.flow_m3h, rel=1e-12)


def test_reverse_flow_through_the_pump_branch_is_blocked(model: HydraulicModel) -> None:
    # An 8 barg reservoir needs more head than the 54 m shutoff head: the pump dead-heads
    # and the check valve stops the reservoir from driving flow backwards.
    result = model.solve(delivery_case("TK-102", 7.0, reservoir_pa=8.0e5))
    assert result.pump is not None and result.pump.status == "DEADHEAD"
    assert result.pump.flow_m3h == 0.0
    for edge in (
        "E-S102a",
        "E-S102b",
        "E-SH",
        "E-PA0",
        "E-PA1",
        "E-PA2",
        "E-PA3",
        "E-PA4",
        "E-D1",
        "E-D2",
    ):
        assert result.edge_flows_m3s[edge] == 0.0  # zero, never negative
    assert result.gates["G3_pump_domain"] == "DEADHEAD"
    assert result.node_heads_m["SUCTION_HEADER"] == 7.0
    reservoir_head = 0.5 + 8.0e5 / (750.0 * 9.80665)
    assert result.node_heads_m["DISCHARGE_HEADER"] == pytest.approx(reservoir_head, rel=1e-12)
    assert any("dead-headed" in n for n in result.notes)


def test_just_below_dead_head_the_flow_is_small_and_forward(model: HydraulicModel) -> None:
    # Reservoir head 53.9 m above the tank level: 0.5 + p/(rho g) = 7 + 53.9.
    pressure = (7.0 + 53.9 - 0.5) * 750.0 * 9.80665
    result = model.solve(delivery_case("TK-102", 7.0, reservoir_pa=pressure))
    assert result.pump is not None and 0.0 < result.pump.flow_m3h < 100.0
    assert all(result.edge_flows_m3s[e] > 0.0 for e in ("E-PA2", "E-PA3", "E-D2"))


def test_one_way_law_blocks_negative_head_difference() -> None:
    law = OneWay(LossLaw(lambda q: 100.0 * q * abs(q)))
    assert law.flow(-5.0) == 0.0 and law.flow(0.0) == 0.0
    assert law.flow(4.0) == pytest.approx(0.2)
    assert law.slope(-1.0) > 0.0


def test_loss_law_inverts_a_quadratic_loss() -> None:
    law = LossLaw(lambda q: 100.0 * q * abs(q) if q >= 0 else -100.0 * q * q)
    assert law.flow(4.0) == pytest.approx(0.2, rel=1e-10)
    assert law.flow(-4.0) == pytest.approx(-0.2, rel=1e-10)
    assert law.slope(4.0) == pytest.approx(1 / (2 * 100.0 * 0.2), rel=1e-5)


# --- conservation ----------

LINEUPS = [
    Lineup.of({"XV-R000", "XV-R101"}),
    Lineup.of({"XV-R000", "XV-R101", "XV-R102"}),
    Lineup.of({"XV-R000", "XV-R101", "XV-R102", "XV-R103"}),
    deliver_lineup("TK-103", "B"),
    Lineup.of({"XV-R000", "XV-R101", "XV-S102", "XV-PAI", "XV-PAO"}, {"P-101A"}),
    Lineup.of({"XV-R000", "XV-R101", "XV-S101", "XV-PBI", "XV-PBO"}, {"P-101B"}),
]


@pytest.mark.parametrize("lineup", LINEUPS, ids=[str(i) for i in range(len(LINEUPS))])
def test_mass_is_conserved_at_every_node(
    model: HydraulicModel, topology: Topology, lineup: Lineup
) -> None:
    result = model.solve(
        SteadyInputs(lineup, dict(INITIAL_LEVELS), SCENARIO, 25.0, delivery=DeliveryBoundary())
    )
    tolerance = model.config["mass_conservation_tolerance_kg_s"] / 750.0
    net: dict[str, float] = {}
    for edge in topology.edges:
        q = result.edge_flows_m3s[edge.edge_id]
        net[edge.from_node] = net.get(edge.from_node, 0.0) - q
        net[edge.to_node] = net.get(edge.to_node, 0.0) + q
    boundary = {"PIPELINE_RECEIPT_BOUNDARY", "DISTRIBUTION_BOUNDARY"}
    for node, imbalance in net.items():
        if node in boundary or ":" in node:
            continue
        assert abs(imbalance) <= tolerance, node
    # The boundary and tank nodes balance against the receipt, the delivery and the tanks.
    delivery = result.edge_flows_m3s["E-D2"]
    tanks = sum(result.tank_net_inflow_m3s.values())
    assert -net["PIPELINE_RECEIPT_BOUNDARY"] - delivery == pytest.approx(tanks, abs=tolerance * 4)
    assert net["DISTRIBUTION_BOUNDARY"] == pytest.approx(delivery, abs=tolerance)
    assert result.max_mass_residual_kg_s <= model.config["mass_conservation_tolerance_kg_s"]


def test_mass_tolerance_is_the_d8_value(model: HydraulicModel) -> None:
    assert model.config["mass_conservation_tolerance_kg_s"] == 4.2e-4


def test_the_solve_stops_with_an_error_if_it_cannot_converge(model: HydraulicModel) -> None:
    params = dict(model.config.parameters)
    from verum.params import ParamValue

    params["newton_max_iterations"] = ParamValue.selected(1.0, "1", "DESIGN", "TEST")
    tight = HydraulicModel(
        model.topology,
        model.geometry,
        model.fluid,
        dataclasses.replace(model.config, parameters=params),
    )
    with pytest.raises(ConvergenceError):
        tight.solve(delivery_case("TK-102", 7.0))


# --- inputs ----------


def test_a_missing_tank_level_is_refused(model: HydraulicModel) -> None:
    inputs = dataclasses.replace(delivery_case("TK-102", 7.0), tank_levels_m={})
    with pytest.raises(HydraulicInputError, match="TK-102"):
        model.solve(inputs)


def test_an_unknown_valve_in_the_lineup_is_refused(model: HydraulicModel) -> None:
    inputs = dataclasses.replace(delivery_case("TK-102", 7.0), lineup=Lineup.of({"XV-NOPE"}))
    with pytest.raises(ContractError):
        model.solve(inputs)


def test_an_idle_lineup_gives_an_empty_valid_result(model: HydraulicModel) -> None:
    result = model.solve(SteadyInputs(Lineup.of(), dict(INITIAL_LEVELS), SCENARIO, 25.0))
    assert result.pump is None and result.active_edges == frozenset()
    assert all(v == 0.0 for v in result.edge_flows_m3s.values())
    assert result.phase.status == "OK" and result.phase.min_abs_pressure_pa is None


def test_the_other_tank_levels_do_not_change_a_delivery(model: HydraulicModel) -> None:
    alone = model.solve(delivery_case("TK-102", 7.0))
    inputs = dataclasses.replace(delivery_case("TK-102", 7.0), tank_levels_m=dict(INITIAL_LEVELS))
    both = model.solve(inputs)
    assert alone.pump is not None and both.pump is not None
    assert alone.pump.flow_m3h == both.pump.flow_m3h


# --- unresolved parameter ----------


def test_an_unresolved_boundary_coefficient_stops_the_solve(root: Path, tmp_path: Path) -> None:
    shutil.copytree(root / "config", tmp_path / "config")
    law = tmp_path / "config" / "delivery_boundary.json"
    document = json.loads(law.read_text(encoding="utf-8"))
    document["parameters"]["reference_fittings"] = {
        "value": None,
        "unit": "m",
        "status": "unresolved",
        "evidence_tag": "OPEN",
        "unresolved_reason": "not solved",
    }
    law.write_text(json.dumps(document), encoding="utf-8")
    local = HydraulicModel.load(tmp_path / "config")
    with pytest.raises(UnresolvedParameter, match="not solved"):
        local.solve(delivery_case("TK-102", 7.0, profile="reference_fittings"))
    assert local.solve(delivery_case("TK-102", 7.0)).pump is not None  # the other profile resolves


def test_the_shipped_coefficients_are_resolved_and_documented() -> None:
    for profile in ("pipe_only", "reference_fittings"):
        record = load_boundary_law_coefficient(profile)
        assert record.status == "provisional" and record.provenance_id == "VERUM-DD-D2-v3.0"
        assert 5.0 < record.value < 15.0


# --- configuration and fittings ----------


def test_every_hydraulic_parameter_is_provisional_with_provenance(model: HydraulicModel) -> None:
    for name, record in model.config.parameters.items():
        assert record.status == "provisional" and record.provenance_id, name
        assert record.evidence_tag in {"REF", "DESIGN", "SIM", "CALC"}, name


def test_numerical_settings_are_declared_design_values(model: HydraulicModel) -> None:
    assert model.config.record("newton_flow_tolerance_m3s").evidence_tag == "DESIGN"
    assert (
        model.config["newton_flow_tolerance_m3s"]
        < model.config["mass_conservation_tolerance_kg_s"] / 750.0
    )


def test_fitting_profiles_hold_the_d15_values() -> None:
    reference = load_fitting_profile("reference_fittings")
    values = {k: reference.k(k) for k in reference.coefficients}
    assert values == {
        "per_bend": 0.3, "tank_outlet": 0.5, "tank_inlet": 1.0,
        "open_isolation_valve": 0.1, "open_check_valve": 2.0, "meter": 1.0,
    }  # fmt: skip
    assert all(load_fitting_profile("pipe_only").k(k) == 0.0 for k in reference.coefficients)
    assert load_fitting_profile("reference_fittings", 2.0).k("per_bend") == 0.6
    assert all(r.evidence_tag == "SIM" for r in reference.coefficients.values())


def test_bad_profile_or_multiplier_is_refused() -> None:
    with pytest.raises(ContractError):
        load_fitting_profile("handbook")
    with pytest.raises(ValueError):
        load_fitting_profile("pipe_only", -1.0)


# Hand count from the polylines: R-MAIN 1, R-101/102/103 3 each, S-101/102/103 3 each,
# S-HEADER 0, P-A 2, P-B 2, D-MAIN 1 (24 bends).
HAND_BENDS = {
    "E001": 0, "E002": 0, "E003": 1,
    "E-R101a": 2, "E-R101b": 1, "E-S101a": 1, "E-S101b": 2,
    "E-PA0": 1, "E-PA4": 1, "E-PB0": 1, "E-PB4": 1,
    "E-D1": 0, "E-D2": 1,
}  # fmt: skip


def test_bends_are_counted_from_the_polylines(topology: Topology) -> None:
    counts = bends_per_edge(topology, load_route_geometry())
    assert sum(counts.values()) == 24
    for edge, expected in HAND_BENDS.items():
        assert counts[edge] == expected, edge
    assert counts["E-PA1"] == counts["E-PA2"] == counts["E-PA3"] == 0


def test_reference_fitting_coefficients_per_edge(topology: Topology) -> None:
    profile = load_fitting_profile("reference_fittings")
    k = edge_loss_coefficients(topology, load_route_geometry(), profile, set(topology.edge_ids))
    assert k["E-R101b"] == pytest.approx(0.3 + 0.1 + 1.0)  # bend, XV-R101, tank inlet
    # S-102 has bends at 0.1 m, 17.55 m and 72.55 m; E-S102a spans 0 to 18 m.
    assert k["E-S102a"] == pytest.approx(2 * 0.3 + 0.5)  # two bends, tank outlet
    assert k["E-S102b"] == pytest.approx(0.3 + 0.1)  # one bend, XV-S102
    assert k["E-PA3"] == pytest.approx(2.0)  # check valve CV-PA
    assert k["E-PA4"] == pytest.approx(0.3 + 0.1)  # bend, XV-PAO
    assert k["E-D2"] == pytest.approx(0.3 + 1.0)  # bend, delivery meter
    assert k["E002"] == pytest.approx(1.0)  # receipt meter
    assert k["E003"] == pytest.approx(0.3 + 0.1)  # bend, XV-R000
    assert k["E-SH"] == 0.0


def test_pipe_only_gives_zero_everywhere_and_the_multiplier_scales(topology: Topology) -> None:
    geometry = load_route_geometry()
    zero = edge_loss_coefficients(
        topology, geometry, load_fitting_profile("pipe_only", 7.0), set(topology.edge_ids)
    )
    assert set(zero.values()) == {0.0}
    one = edge_loss_coefficients(
        topology, geometry, load_fitting_profile("reference_fittings"), set(topology.edge_ids)
    )
    two = edge_loss_coefficients(
        topology, geometry, load_fitting_profile("reference_fittings", 2.0), set(topology.edge_ids)
    )
    assert all(two[e] == pytest.approx(2 * one[e]) for e in one)


# --- result type and isolation ----------


def test_the_result_is_immutable(model: HydraulicModel) -> None:
    result = model.solve(delivery_case("TK-102", 7.0))
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.receipt_clipped = True  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.edge_flows_m3s["E001"] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        result.node_heads_m["TK-102:outlet_nozzle"] = 0.0  # type: ignore[index]


def test_the_result_has_the_required_content(model: HydraulicModel, topology: Topology) -> None:
    result = model.solve(delivery_case("TK-102", 7.0))
    assert set(result.edge_flows_m3s) == set(topology.edge_ids)
    assert result.pump is not None and result.pump.pump == "P-101A"
    assert set(result.gates) == {"G2_boundary", "G3_pump_domain", "G4_phase", "G6_conservation"}
    assert set(result.tank_net_inflow_m3s) == set(TANKS)
    assert result.tank_net_inflow_m3s["TK-102"] == pytest.approx(
        -result.edge_flows_m3s["E-S102a"], abs=1e-12
    )
    assert result.fitting_profile == "pipe_only" and result.boundary_law_coefficient_m > 11.9


def test_the_hydraulics_package_is_not_reachable_from_the_api_package() -> None:
    """The gateway (Phase 4) exposes only its own names and imports nothing from hydraulics."""
    import ast

    import verum.api as api

    assert sorted(n for n in dir(api) if not n.startswith("_") and n != "gateway") == [
        "Gateway", "GatewayViolation", "check_allowlist", "query",
    ]  # fmt: skip
    for module in (api.__file__, api.gateway.__file__):
        tree = ast.parse(Path(module or "").read_text(encoding="utf-8"))
        imported = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
        ]
        assert not [m for m in imported if "hydraulics" in m or "verum.truth" in m], module
