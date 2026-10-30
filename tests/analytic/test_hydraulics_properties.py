"""Property tests of the steady solve, using random levels, lineups and loss multipliers.

The checks are invariants and not value checks: the operating flow does not fall as the tank level
rises, the multiplier has no effect with the pipe-only profile and does not raise the flow with the
reference fittings, the two pump branches are mirror images, and every lineup conserves mass and
passes its own gates.

See D15.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from _hydraulic_cases import SCENARIO, TANKS, delivery_case
from verum.contracts import Topology
from verum.graph import Lineup
from verum.hydraulics import DeliveryBoundary, HydraulicModel, SteadyInputs
from verum.lineups import LineupTable, load_lineup_table

LEVEL = st.floats(min_value=1.8, max_value=12.0)
TANK = st.sampled_from(TANKS)
PROFILE = st.sampled_from(["pipe_only", "reference_fittings"])


def _flow(model: HydraulicModel, tank: str, level: float, **kw: object) -> float:
    point = model.solve(delivery_case(tank, level, **kw)).pump  # type: ignore[arg-type]
    assert point is not None
    return point.flow_m3h


@settings(max_examples=40, deadline=None)
@given(tank=TANK, a=LEVEL, b=LEVEL, profile=PROFILE)
def test_flow_does_not_decrease_when_the_tank_level_rises(
    model: HydraulicModel, tank: str, a: float, b: float, profile: str
) -> None:
    """The operating flow does not decrease when the tank level rises. Independent: yes, because the
    property is an invariant and needs no reference value.
    """
    low, high = sorted((a, b))
    assert (
        _flow(model, tank, low, profile=profile) <= _flow(model, tank, high, profile=profile) + 1e-9
    )


@settings(max_examples=30, deadline=None)
@given(tank=TANK, level=LEVEL, multiplier=st.floats(min_value=0.0, max_value=5.0))
def test_multiplier_has_no_effect_on_the_pipe_only_profile(
    model: HydraulicModel, tank: str, level: float, multiplier: float
) -> None:
    """The loss multiplier changes nothing with the pipe-only profile, where every fitting
    coefficient is zero. Independent: yes, because the property is an invariant.
    """
    base = _flow(model, tank, level, profile="pipe_only")
    assert _flow(model, tank, level, profile="pipe_only", multiplier=multiplier) == pytest.approx(
        base, rel=1e-9
    )


@settings(max_examples=30, deadline=None)
@given(tank=TANK, level=LEVEL, m1=st.floats(0.0, 4.0), m2=st.floats(0.0, 4.0))
def test_flow_does_not_increase_with_the_reference_fitting_multiplier(
    model: HydraulicModel, tank: str, level: float, m1: float, m2: float
) -> None:
    """With the reference fittings the flow does not increase as the multiplier grows. Independent:
    yes, because the property is an invariant.
    """
    low, high = sorted((m1, m2))
    kw = dict(profile="reference_fittings", law=10.0)
    assert (
        _flow(model, tank, level, multiplier=high, **kw)
        <= _flow(model, tank, level, multiplier=low, **kw) + 1e-9
    )


@settings(max_examples=30, deadline=None)
@given(tank=TANK, level=LEVEL, multiplier=st.floats(0.0, 3.0), profile=PROFILE)
def test_pump_a_and_pump_b_branches_are_symmetric(
    model: HydraulicModel, tank: str, level: float, multiplier: float, profile: str
) -> None:
    """The pump A and pump B branches give the same flow for every level and multiplier.
    Independent: yes, because the property is a symmetry of the network.
    """
    a = _flow(model, tank, level, pump="A", profile=profile, multiplier=multiplier)
    b = _flow(model, tank, level, pump="B", profile=profile, multiplier=multiplier)
    assert a == pytest.approx(b, rel=1e-9)


@pytest.fixture(scope="module")
def lineup_table(topology: Topology) -> LineupTable:
    return load_lineup_table(topology)


@settings(max_examples=60, deadline=None)
@given(
    data=st.data(),
    levels=st.tuples(LEVEL, LEVEL, LEVEL),
    profile=PROFILE,
)
def test_every_mode_conserves_mass_for_random_levels(
    model: HydraulicModel,
    topology: Topology,
    lineup_table: LineupTable,
    data: st.DataObject,
    levels: tuple[float, float, float],
    profile: str,
) -> None:
    """Every lineup mode conserves mass at every node for random levels and passes its own gates.
    Independent: yes, because the node balance is recomputed from the edge flows with separate code.
    """
    mode = lineup_table.mode(data.draw(st.sampled_from(sorted(lineup_table.modes))))
    inputs = SteadyInputs(
        Lineup(mode.open_valves, mode.running_pumps),
        dict(zip(TANKS, levels, strict=True)),
        SCENARIO,
        25.0,
        fitting_profile=profile,
        delivery=DeliveryBoundary(),
    )
    result = model.solve(inputs)
    tolerance = model.config["mass_conservation_tolerance_kg_s"] / 750.0
    net: dict[str, float] = {}
    for edge in topology.edges:
        q = result.edge_flows_m3s[edge.edge_id]
        net[edge.from_node] = net.get(edge.from_node, 0.0) - q
        net[edge.to_node] = net.get(edge.to_node, 0.0) + q
    skip = {"PIPELINE_RECEIPT_BOUNDARY", "DISTRIBUTION_BOUNDARY"}
    assert all(abs(v) <= tolerance for n, v in net.items() if n not in skip and ":" not in n)
    assert result.gates["G6_conservation"] == "OK"
    if mode.receiving:
        assert result.receipt_flow_m3h == pytest.approx(600.0, abs=1e-5)
        assert sum(result.tank_net_inflow_m3s.values()) * 3600 + (
            result.pump.flow_m3h if result.pump else 0.0
        ) == pytest.approx(600.0, abs=1e-5)
