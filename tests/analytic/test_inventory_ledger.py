"""Inventory ledger: closure, receipt and delivery cases, and a leak counted once.

Prescribed flows drive the ledgers without hydraulics. The inventory and level changes are derived
by hand, injected errors (a double subtraction, an unbalanced step) must be detected, and a property
test checks the closure residual against the round-off bound. The values are in the "Inventory
ledger" section of the verification notes.

See D6.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from verum.contracts import load_fluid_contract
from verum.ledger import LedgerError, NetworkLedger, TankFlows, TankLedger, closure_tolerance
from verum.tanks import TankGeometry, load_tank_geometry

RHO = load_fluid_contract().properties["rho_kg_m3"].value
TANKS = {"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0}


@pytest.fixture(scope="module")
def geometry() -> TankGeometry:
    return load_tank_geometry()


def _network(geometry: TankGeometry) -> NetworkLedger:
    return NetworkLedger(
        {k: TankLedger(k, RHO * geometry.volume_m3(h, RHO)) for k, h in TANKS.items()}
    )


def test_density_comes_from_the_fluid_contract() -> None:
    """The density used by the ledger tests is the contract value of 750 kg/m3. Independent: yes,
    because the expected value is the contract constant.
    """
    assert RHO == 750.0


def test_closed_system_stays_closed(geometry: TankGeometry) -> None:
    """A system with no flows keeps its levels and has a zero residual. Independent: yes, because
    the expected value is zero.
    """
    ledger = _network(geometry)
    before = ledger.levels_m(geometry, RHO)
    for _ in range(3600):
        ledger.step(0.0, 0.0, {k: TankFlows() for k in TANKS})
    assert ledger.levels_m(geometry, RHO) == before
    assert ledger.liquid_closure().residual_kg == 0.0
    assert ledger.total_closure().closed and ledger.liquid_closure().closed


def test_receipt_of_600_m3_in_one_hour(geometry: TankGeometry) -> None:
    """A receipt of 600 m3 in one hour adds 450000 kg and raises the level by 0.848826 m.
    Independent: yes, because the values are hand arithmetic.
    """
    ledger = _network(geometry)
    per_step = RHO * 600 / 3600  # 125 kg per second
    for _ in range(3600):
        ledger.step(per_step, 0.0, {"TK-101": TankFlows(mass_in_kg=per_step)})
    tank = ledger.tanks["TK-101"]
    bound = ledger.liquid_closure().tolerance_kg
    assert abs((tank.liquid_kg - tank.initial_liquid_kg) - 450000.0) < bound
    assert abs((tank.level_m(geometry, RHO) - 9.0) - 0.848826) < 1e-6
    assert ledger.liquid_closure().closed and ledger.total_closure().closed
    assert ledger.levels_m(geometry, RHO)["TK-102"] == pytest.approx(7.0, abs=1e-9)


def test_concurrent_600_in_and_300_out(geometry: TankGeometry) -> None:
    """Receiving 600 m3/h while delivering 300 m3/h leaves a net 225000 kg and a level rise of
    0.424413 m. Independent: yes, because the values are hand arithmetic.
    """
    ledger = _network(geometry)
    q_in, q_out = RHO * 600 / 3600, RHO * 300 / 3600
    for _ in range(3600):
        ledger.step(q_in, q_out, {"TK-101": TankFlows(mass_in_kg=q_in, mass_out_kg=q_out)})
    tank = ledger.tanks["TK-101"]
    bound = ledger.liquid_closure().tolerance_kg
    assert abs((tank.liquid_kg - tank.initial_liquid_kg) - 225000.0) < bound
    assert abs(tank.volume_m3(RHO) - geometry.volume_m3(9.0, RHO) - 300.0) < 1e-9
    assert abs((tank.level_m(geometry, RHO) - 9.0) - 0.424413) < 1e-6
    assert ledger.liquid_closure().closed


def test_leak_mass_leaves_the_network_once(geometry: TankGeometry) -> None:
    """A leak of 5 m3 removes 3750 kg from the network once. Independent: yes, because the values
    are hand arithmetic.
    """
    ledger = _network(geometry)
    leak_per_step = RHO * 5 / 3600  # 5 m3 over the hour, 3750 kg
    received = RHO * 600 / 3600
    for _ in range(3600):
        ledger.step(
            received,
            0.0,
            {"TK-101": TankFlows(mass_in_kg=received - leak_per_step)},
            pipe_spill_kg=leak_per_step,
        )
    assert math.isclose(ledger.spill_kg, 3750.0, rel_tol=1e-12)
    tank = ledger.tanks["TK-101"]
    # Differences of masses near 5e6 kg accumulate round-off over 3600 steps; the
    # run's own bound (about 1e-4 kg) is the admissible error.
    bound = ledger.liquid_closure().tolerance_kg
    assert abs((tank.liquid_kg - tank.initial_liquid_kg) - 446250.0) < bound
    assert ledger.liquid_closure().closed and ledger.total_closure().closed


def test_subtracting_the_leak_twice_is_detected(geometry: TankGeometry) -> None:
    """A leak that is removed from the tank inflow twice makes the closure fail. Independent: yes,
    because the error is injected and the expectation is a failed closure.
    """
    ledger = _network(geometry)
    leak_per_step = RHO * 5 / 3600
    received = RHO * 600 / 3600
    for _ in range(3600):
        # A 5 m3 leak recorded once as a spill but removed from the tank inflow twice.
        ledger.step(
            received,
            0.0,
            {"TK-101": TankFlows(mass_in_kg=received - 2 * leak_per_step)},
            pipe_spill_kg=leak_per_step,
        )
    closure = ledger.liquid_closure()
    assert not closure.closed
    assert abs(closure.residual_kg - 3750.0) < 1e-3


def test_a_pipe_leak_and_a_tank_leak_are_two_sinks_that_each_leave_once(
    geometry: TankGeometry,
) -> None:
    """A pipe leak and a tank leak are two sinks that each leave the network once. Independent: yes,
    because the totals are hand arithmetic.
    """
    ledger = _network(geometry)
    leak_per_step = RHO * 5 / 3600
    received = RHO * 600 / 3600
    for _ in range(3600):
        ledger.step(
            received,
            0.0,
            {"TK-101": TankFlows(mass_in_kg=received - leak_per_step, leak_kg=leak_per_step)},
            pipe_spill_kg=leak_per_step,
        )
    assert abs(ledger.spill_kg - 7500.0) < 1e-6
    assert ledger.liquid_closure().closed


def test_a_leak_at_the_tank_is_counted_in_the_spill_total(geometry: TankGeometry) -> None:
    """A leak at a tank is counted in the spill total, so 10 kg lost in a pipe and 4 kg at a tank
    give 14 kg. Independent: yes, because the values are hand arithmetic.
    """
    ledger = _network(geometry)
    ledger.step(100.0, 0.0, {"TK-101": TankFlows(mass_in_kg=100.0 - 10.0)}, pipe_spill_kg=10.0)
    ledger.step(0.0, 0.0, {"TK-102": TankFlows(leak_kg=4.0)})
    # 10 kg lost in a pipe and 4 kg lost at a tank: 14 kg leave once, and the
    # network balance 100 - 14 - (90 - 4) closes.
    assert ledger.spill_kg == 14.0
    assert ledger.liquid_closure().residual_kg == 0.0
    assert ledger.total_closure().residual_kg == 0.0
    assert ledger.tanks["TK-102"].liquid_kg == ledger.tanks["TK-102"].initial_liquid_kg - 4.0


def test_liquid_only_and_total_product_definitions_differ_by_phase_change(
    geometry: TankGeometry,
) -> None:
    """Evaporation moves mass from liquid to vapor, so the liquid-only inventory falls and the total
    product is unchanged. Independent: yes, because the values are hand arithmetic.
    """
    ledger = _network(geometry)
    ledger.step(0.0, 0.0, {"TK-101": TankFlows(evaporation_kg=1000.0)})
    tank = ledger.tanks["TK-101"]
    # Evaporation moves 1000 kg from liquid to vapor; the total is unchanged.
    assert tank.liquid_kg == tank.initial_liquid_kg - 1000.0
    assert tank.vapor_kg == 1000.0
    assert tank.total_kg == tank.initial_liquid_kg
    assert tank.liquid_residual_kg() == 0.0 and tank.total_residual_kg() == 0.0
    assert ledger.liquid_closure().closed and ledger.total_closure().closed
    # Vapor leaving the tank is a loss for the total but not for the liquid statement.
    ledger.step(0.0, 0.0, {"TK-101": TankFlows(vapor_out_kg=400.0)})
    assert tank.vapor_kg == 600.0
    assert ledger.total_closure().closed
    assert ledger.total_closure().residual_kg == pytest.approx(0.0, abs=1e-9)


def test_evaporation_is_not_subtracted_twice_from_the_total(geometry: TankGeometry) -> None:
    """The total-product ledger does not subtract evaporation, and a naive double subtraction would
    be off by the evaporated mass. Independent: yes, because the wrong value is computed by hand.
    """
    ledger = _network(geometry)
    ledger.step(0.0, 0.0, {"TK-101": TankFlows(evaporation_kg=1000.0)})
    t = ledger.tanks["TK-101"]
    wrong = (t.total_kg - t.initial_liquid_kg) - (-t.totals.evaporation)  # naive double subtraction
    assert wrong == 1000.0
    assert t.total_residual_kg() == 0.0


def test_unbalanced_prescribed_flows_are_detected(geometry: TankGeometry) -> None:
    """Flows that do not balance make the closure fail with the residual of 5 kg. Independent: yes,
    because the residual is the injected imbalance.
    """
    ledger = _network(geometry)
    ledger.step(125.0, 0.0, {"TK-101": TankFlows(mass_in_kg=120.0)})
    assert not ledger.liquid_closure().closed
    assert ledger.liquid_closure().residual_kg == pytest.approx(5.0)


def test_closure_tolerance_formula() -> None:
    """The closure tolerance equals (n - 1) 2^-53 times the sum of the absolute terms. Independent:
    yes, because the expected values are hand arithmetic.
    """
    assert closure_tolerance([1.0, 2.0, -3.0]) == pytest.approx(12 * 2.0**-53, rel=1e-15)
    assert closure_tolerance([5.0]) == 0.0
    assert closure_tolerance([]) == 0.0
    assert closure_tolerance([1.0] * 11) == pytest.approx(10 * 2.0**-53 * 11, rel=1e-15)


def test_tolerance_is_computed_per_run_and_grows_with_the_run(geometry: TankGeometry) -> None:
    """The tolerance is computed for each run and grows with the number of terms. Independent: yes,
    because only the ordering is checked.
    """
    short, long = _network(geometry), _network(geometry)
    for steps, ledger in ((10, short), (1000, long)):
        for _ in range(steps):
            ledger.step(1.0, 0.0, {"TK-101": TankFlows(mass_in_kg=1.0)})
    assert 0 < short.liquid_closure().tolerance_kg < long.liquid_closure().tolerance_kg


def test_tolerance_is_small_enough_to_detect_a_gram(geometry: TankGeometry) -> None:
    """After an hour of steps the tolerance is below a gram, so an added gram is detected.
    Independent: yes, because the added mass is injected.
    """
    ledger = _network(geometry)
    for _ in range(3600):
        ledger.step(125.0, 0.0, {"TK-101": TankFlows(mass_in_kg=125.0)})
    assert ledger.liquid_closure().tolerance_kg < 1e-3
    ledger.step(0.001, 0.0, {})
    assert not ledger.liquid_closure().closed


@settings(max_examples=100, deadline=None)
@given(
    flows=st.lists(
        st.tuples(
            st.floats(0, 500),
            st.floats(0, 500),
            st.floats(0, 5),
            st.floats(0, 5),
        ),
        min_size=1,
        max_size=200,
    )
)
def test_residual_stays_within_the_bound_for_arbitrary_flows(
    flows: list[tuple[float, float, float, float]],
) -> None:
    """For arbitrary non-negative flows the closure residual stays within the round-off bound.
    Independent: yes, because the bound is the stated rule and the flows are random.
    """
    ledger = NetworkLedger({"TK-101": TankLedger("TK-101", 1.0e6)})
    for q_in, q_out, spill, evap in flows:
        ledger.step(
            q_in + spill,
            q_out,
            {"TK-101": TankFlows(mass_in_kg=q_in, mass_out_kg=q_out, evaporation_kg=evap)},
            pipe_spill_kg=spill,
        )
    # Evaporation is a sink for the liquid statement and an internal transfer
    # for the total, so both statements close for any prescribed flows.
    assert ledger.liquid_closure().closed
    assert ledger.total_closure().closed


@pytest.mark.parametrize(
    "flows",
    [
        {"mass_in_kg": -1.0},
        {"mass_out_kg": math.nan},
        {"leak_kg": -0.1},
        {"evaporation_kg": -5.0},
        {"vapor_out_kg": -5.0},
    ],
)
def test_negative_or_non_finite_flows_are_rejected(flows: dict[str, float]) -> None:
    """Negative or non-finite flows are rejected. Independent: yes, because the expected outcome is
    the validation rule.
    """
    with pytest.raises(LedgerError):
        TankFlows(**flows)


def test_a_step_cannot_make_an_inventory_negative() -> None:
    """A step that would make a liquid or vapor inventory negative is rejected and changes nothing.
    Independent: yes, because the expected outcome is the validation rule.
    """
    tank = TankLedger("TK-101", 100.0)
    with pytest.raises(LedgerError):
        tank.apply(TankFlows(mass_out_kg=101.0))
    with pytest.raises(LedgerError):
        tank.apply(TankFlows(vapor_out_kg=1.0))
    assert tank.liquid_kg == 100.0


def test_unknown_tank_and_negative_boundary_masses_are_rejected(geometry: TankGeometry) -> None:
    """An unknown tank or a negative boundary mass is rejected. Independent: yes, because the
    expected outcome is the validation rule.
    """
    ledger = _network(geometry)
    with pytest.raises(LedgerError):
        ledger.step(0.0, 0.0, {"TK-999": TankFlows()})
    with pytest.raises(LedgerError):
        ledger.step(-1.0, 0.0, {})
