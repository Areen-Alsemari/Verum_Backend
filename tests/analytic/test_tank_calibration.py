"""Tank calibration of liquid volume against level and density: reference volumes, continuity and
round trips.

Expected volumes are evaluated with 50-digit decimals and compared with the package and with the
documented figures, and hypothesis checks the round trips over the density and deck-mass ranges of
the sensitivity screen. The branch expressions and the reference values are derived in the "Tank
calibration" section of the verification notes.
"""

from __future__ import annotations

import math
from decimal import Decimal, getcontext

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from verum.params import ParamValue, UnresolvedParameter
from verum.tanks import TankGeometry, load_tank_geometry, load_tank_parameters

getcontext().prec = 50
PI = Decimal("3.14159265358979323846264338327950288419716939937510")
RHO = 750.0

DOCUMENT_VOLUMES = {
    1.8: 1253.870575,
    5.0: 3515.817286,
    7.0: 4929.533980,
    9.0: 6343.250674,
    12.0: 8463.825715,
    13.0: 9170.684062,
    14.0: 9877.542409,
}


def _expected(level: str, rho: str = "750", areal_mass: str = "20") -> Decimal:
    area = PI * Decimal(225)
    deck_area = PI * Decimal("220.5225")
    draft = Decimal(areal_mass) / Decimal(rho)
    h = Decimal(level)
    support = Decimal("1.5")
    immersion = min(max(h - support, Decimal(0)), draft)
    return area * h - deck_area * immersion


@pytest.fixture(scope="module")
def geometry() -> TankGeometry:
    return load_tank_geometry()


@pytest.mark.parametrize("level", sorted(DOCUMENT_VOLUMES))
def test_reference_volumes_match_decimal_derivation_and_document(
    geometry: TankGeometry, level: float
) -> None:
    """The volumes at the reference levels match the decimal derivation and the documented figures
    to 1e-6 m3. Independent: yes, because the arithmetic is decimal against floating point and the
    document values are literals.
    """
    value = geometry.volume_m3(level, RHO)
    assert abs(value - float(_expected(str(level)))) < 1e-6
    assert abs(value - DOCUMENT_VOLUMES[level]) < 1e-6


def test_deck_draft_and_displacement_at_750(geometry: TankGeometry) -> None:
    """At 750 kg/m3 the deck draft, displacement and mass equal the hand values. Independent: yes,
    because the values are hand arithmetic.
    """
    # d = 20 / 750 = 0.0266666667 m ; V_disp = 692.791865951 * d = 18.474449759 m3
    assert abs(geometry.draft_m(RHO) - 0.026666667) < 1e-9
    assert abs(geometry.displacement_m3(RHO) - 18.474449759) < 1e-9
    assert abs(geometry.deck_mass_kg() - 13855.837319) < 1e-6


def test_areas_match_the_closed_form(geometry: TankGeometry) -> None:
    """The shell and deck areas equal the closed-form values. Independent: yes, because the values
    are hand arithmetic.
    """
    assert abs(geometry.area_m2 - 706.858347) < 1e-6
    assert abs(geometry.deck_area_m2 - 692.791866) < 1e-6


def test_liftoff_and_floating_levels(geometry: TankGeometry) -> None:
    """The lift-off level is 1.5 m and the floating level is 1.526667 m. Independent: yes, because
    the values are hand arithmetic.
    """
    assert geometry.lift_off_level_m() == 1.5
    assert abs(geometry.floating_level_m(RHO) - 1.526666667) < 1e-9


def test_volume_is_continuous_at_both_branch_points(geometry: TankGeometry) -> None:
    """The volume is continuous at the lift-off and floating levels. Independent: yes, because only
    continuity is checked.
    """
    lift = geometry.lift_off_level_m()
    float_level = geometry.floating_level_m(RHO)
    for point in (lift, float_level):
        below = geometry.volume_m3(point - 1e-9, RHO)
        above = geometry.volume_m3(point + 1e-9, RHO)
        assert abs(above - below) < 2 * geometry.area_m2 * 1e-9 + 1e-9
    # Closed-form value at lift-off: V = A * z_s (nothing displaced yet).
    assert abs(geometry.volume_m3(lift, RHO) - float(PI * 225 * Decimal("1.5"))) < 1e-9


def test_volume_is_strictly_increasing_on_a_fine_grid(geometry: TankGeometry) -> None:
    """The volume increases strictly with level on a grid of 1 mm. Independent: yes, because only
    monotonicity is checked.
    """
    levels = [i * 0.001 for i in range(0, 15001)]
    volumes = [geometry.volume_m3(h, RHO) for h in levels]
    assert all(b > a for a, b in zip(volumes, volumes[1:], strict=False))


def test_slope_is_area_above_floating_and_net_area_in_transition(geometry: TankGeometry) -> None:
    """The slope of the volume is the shell area above the floating level and the net area in the
    transition. Independent: yes, because the slopes are hand values.
    """
    # dV/dh = A on the landed and floating branches, A - A_d while the deck is immersing.
    dh = 1e-4
    assert (
        abs((geometry.volume_m3(5 + dh, RHO) - geometry.volume_m3(5, RHO)) / dh - geometry.area_m2)
        < 1e-6
    )
    mid = 1.5 + 0.01
    slope = (geometry.volume_m3(mid + 1e-6, RHO) - geometry.volume_m3(mid, RHO)) / 1e-6
    assert abs(slope - (geometry.area_m2 - geometry.deck_area_m2)) < 1e-3


@pytest.mark.parametrize(
    ("level", "state"),
    [
        (0.0, "landed"),
        (1.0, "landed"),
        (1.5, "landed"),
        (1.51, "transition"),
        (1.5266, "transition"),
        (1.5266666667, "floating"),
        (1.8, "floating"),
        (14.0, "floating"),
    ],
)
def test_roof_state(geometry: TankGeometry, level: float, state: str) -> None:
    """The roof is landed, in transition or floating at the expected levels. Independent: yes,
    because the states follow from the lift-off and floating levels.
    """
    assert geometry.roof_state(level, RHO) == state


def test_round_trip_over_a_grid(geometry: TankGeometry) -> None:
    """Converting a level to a volume and back returns the level to 1e-9 m on a fine grid.
    Independent: yes, because the property is a round trip.
    """
    for i in range(0, 15001):
        h = i * 0.001
        assert abs(geometry.level_m(geometry.volume_m3(h, RHO), RHO) - h) < 1e-9


def test_inverse_hits_each_branch(geometry: TankGeometry) -> None:
    """The inverse gives the expected level on the landed, transition and floating branches.
    Independent: yes, because the levels are hand values.
    """
    assert abs(geometry.level_m(1000.0, RHO) - 1000.0 / geometry.area_m2) < 1e-12  # landed
    assert abs(geometry.level_m(6343.250674, RHO) - 9.0) < 1e-9  # floating
    v_mid = geometry.volume_m3(1.51, RHO)  # transition
    assert abs(geometry.level_m(v_mid, RHO) - 1.51) < 1e-9


@settings(max_examples=300, deadline=None)
@given(
    rho=st.floats(650, 800),
    areal_mass=st.floats(10, 40),
    level=st.floats(0, 15),
)
def test_round_trip_level_volume_level(rho: float, areal_mass: float, level: float) -> None:
    """For random density and deck mass a level survives the round trip through volume. Independent:
    yes, because the property is a round trip.
    """
    g = _geometry(areal_mass)
    assert abs(g.level_m(g.volume_m3(level, rho), rho) - level) < 1e-9


@settings(max_examples=300, deadline=None)
@given(rho=st.floats(650, 800), areal_mass=st.floats(10, 40), volume=st.floats(0, 10500))
def test_round_trip_volume_level_volume(rho: float, areal_mass: float, volume: float) -> None:
    """For random density and deck mass a volume survives the round trip through level. Independent:
    yes, because the property is a round trip.
    """
    g = _geometry(areal_mass)
    assert abs(g.volume_m3(g.level_m(volume, rho), rho) - volume) < 1e-8


@settings(max_examples=300, deadline=None)
@given(
    rho=st.floats(650, 800),
    areal_mass=st.floats(10, 40),
    a=st.floats(0, 15),
    b=st.floats(0, 15),
)
def test_strictly_monotonic_for_any_density_and_mass(
    rho: float, areal_mass: float, a: float, b: float
) -> None:
    """For random density and deck mass the volume is strictly increasing in level. Independent:
    yes, because only monotonicity is checked.
    """
    g = _geometry(areal_mass)
    low, high = sorted((a, b))
    if high - low > 1e-6:
        assert g.volume_m3(high, rho) > g.volume_m3(low, rho)


@settings(max_examples=200, deadline=None)
@given(rho=st.floats(650, 800), areal_mass=st.floats(10, 40))
def test_displacement_equals_deck_mass_over_density(rho: float, areal_mass: float) -> None:
    """The displaced volume equals the deck mass divided by the density. Independent: yes, because
    the identity follows from flotation.
    """
    g = _geometry(areal_mass)
    assert math.isclose(g.displacement_m3(rho), g.deck_mass_kg() / rho, rel_tol=1e-12)


def _geometry(areal_mass: float) -> TankGeometry:
    p = load_tank_parameters()
    return TankGeometry.from_params(
        p["shell_diameter_m"],
        p["deck_diameter_m"],
        p["roof_support_height_m"],
        ParamValue.selected(areal_mass, "kg/m2", "SIM", "TEST-SWEEP"),
    )


def test_density_must_be_positive(geometry: TankGeometry) -> None:
    """A zero, negative or non-finite density is rejected. Independent: yes, because the expected
    outcome is the validation rule.
    """
    for rho in (0.0, -1.0, math.inf, math.nan):
        with pytest.raises(ValueError):
            geometry.volume_m3(5.0, rho)


def test_negative_level_or_volume_is_rejected(geometry: TankGeometry) -> None:
    """A negative level or volume is rejected. Independent: yes, because the expected outcome is the
    validation rule.
    """
    with pytest.raises(ValueError):
        geometry.volume_m3(-0.1, RHO)
    with pytest.raises(ValueError):
        geometry.level_m(-1.0, RHO)


def test_unresolved_parameter_stops_construction() -> None:
    """An unresolved geometry parameter stops the construction of the tank geometry. Independent:
    yes, because the expected outcome is the rule that nothing replaces an unresolved parameter.
    """
    p = load_tank_parameters()
    with pytest.raises(UnresolvedParameter):
        TankGeometry.from_params(
            p["shell_diameter_m"],
            p["deck_diameter_m"],
            ParamValue.unresolved("m", "support height not selected"),
            p["roof_areal_mass_kg_m2"],
        )


def test_configuration_entries_are_provisional_design_values_with_provenance() -> None:
    """Every tank parameter is provisional, tagged as a design value and carries its provenance
    identifier. Independent: yes, because the expected values are the stated status and tag.
    """
    for name, record in load_tank_parameters().items():
        assert (record.status, record.evidence_tag) == ("provisional", "DESIGN"), name
        assert record.provenance_id == "VERUM-M1-R1.2", name
