"""Headroom screen, level envelope and receipt level rise.

The response-headroom screen is evaluated with decimal arithmetic for the documented flows and
response times, and the level classes, thresholds and receipt level rise are checked against the
contract. The expected values are derived in the "Headroom screen and level envelope" section of the
verification notes.

See D15.
"""

from __future__ import annotations

from decimal import Decimal, getcontext

import pytest

from verum.contracts import Topology
from verum.tanks import (
    HeadroomScreen,
    LevelEnvelope,
    TankGeometry,
    load_tank_geometry,
    load_tank_parameters,
)

getcontext().prec = 50
PI = Decimal("3.14159265358979323846264338327950288419716939937510")
AREA = PI * 225


@pytest.fixture(scope="module")
def envelope(topology: Topology) -> LevelEnvelope:
    return LevelEnvelope.from_tank(topology.tanks[0])


@pytest.fixture(scope="module")
def screen(envelope: LevelEnvelope) -> HeadroomScreen:
    p = load_tank_parameters()
    return HeadroomScreen.from_params(
        load_tank_geometry(),
        envelope,
        p["headroom_residual_delivery_m3"],
        p["headroom_level_allowance_m"],
    )


def _rise(flow: int, hours: int) -> Decimal:
    return (Decimal(flow * hours) + 20) / AREA + Decimal("0.05")


def test_600_for_one_hour_passes_with_the_documented_margin(screen: HeadroomScreen) -> None:
    """A receipt of 600 m3/h for one hour passes the headroom screen with a margin of 0.072879 m.
    Independent: yes, because the expected values are decimal arithmetic written in the test.
    """
    result = screen.evaluate(600, 3600)
    assert result.passes
    assert abs(result.required_rise_m - 0.927121) < 1e-6
    assert abs(result.margin_m - 0.072879) < 1e-6
    assert abs(result.required_rise_m - float(_rise(600, 1))) < 1e-9


def test_660_for_one_hour_fails_at_the_documented_height(screen: HeadroomScreen) -> None:
    """A receipt of 660 m3/h for one hour fails the screen at a required height of 14.012003 m.
    Independent: yes, because the expected values are decimal arithmetic written in the test.
    """
    result = screen.evaluate(660, 3600)
    assert not result.passes
    assert abs(result.required_height_m - 14.012003) < 1e-6
    assert abs(result.required_height_m - float(13 + _rise(660, 1))) < 1e-9


@pytest.mark.parametrize(("flow", "hours", "rise"), [(900, 1, 1.351), (600, 2, 1.776)])
def test_larger_flow_or_longer_response_fails(
    screen: HeadroomScreen, flow: float, hours: int, rise: float
) -> None:
    """A larger flow or a longer response time fails the screen with the hand-computed rise.
    Independent: yes, because the rise is recomputed with decimal arithmetic.
    """
    result = screen.evaluate(flow, hours * 3600)
    assert not result.passes
    assert abs(result.required_rise_m - float(_rise(int(flow), hours))) < 1e-9
    assert abs(result.required_rise_m - rise) < 1e-3


def test_limiting_flow_is_651_515(screen: HeadroomScreen) -> None:
    """The limiting flow for a one-hour response is 651.515 m3/h, and the margin changes sign there.
    Independent: yes, because the limit is recomputed with decimal arithmetic.
    """
    limit = screen.limiting_flow_m3h(3600)
    assert abs(limit - 651.515) < 1e-3
    assert abs(limit - float(Decimal("0.95") * AREA - 20)) < 1e-9
    assert screen.evaluate(limit, 3600).margin_m == pytest.approx(0.0, abs=1e-12)
    assert screen.evaluate(limit + 0.01, 3600).margin_m < 0


def test_configured_response_time_is_one_hour() -> None:
    """The configured response time is 3600 s. Independent: yes, because the expected value is the
    documented constant.
    """
    assert load_tank_parameters()["headroom_response_time_s"].value == 3600.0


def test_fifteen_minute_normal_screen_fits_between_alarm_and_high_high(
    screen: HeadroomScreen, envelope: LevelEnvelope
) -> None:
    """The 15-minute screen at 600 m3/h raises the level by 0.2905 m, which fits between the high
    alarm and high-high levels. Independent: yes, because the rise is hand arithmetic.
    """
    seconds = load_tank_parameters()["normal_response_time_s"].value
    rise = screen.evaluate(600, seconds).required_rise_m
    assert abs(rise - 0.290501) < 1e-6
    assert rise < envelope.high_high_m - envelope.high_alarm_m == 0.5


LEVEL_CASES = [
    (1.79, "below_minimum"),
    (1.8, "normal"),
    (12.0, "normal"),
    (12.01, "above_working_maximum"),
    (12.49, "above_working_maximum"),
    (12.5, "high_alarm"),
    (12.99, "high_alarm"),
    (13.0, "high_high"),
    (13.99, "high_high"),
    (14.0, "critical"),
    (15.0, "critical"),
]


@pytest.mark.parametrize(("level", "expected"), LEVEL_CASES)
def test_level_classes_at_the_thresholds(
    envelope: LevelEnvelope, level: float, expected: str
) -> None:
    """Each level class changes exactly at its threshold, with the threshold in the higher class.
    Independent: yes, because the expected classes follow from the contract thresholds.
    """
    assert envelope.classify(level) == expected


def test_envelope_values_come_from_the_contract(envelope: LevelEnvelope) -> None:
    """The envelope thresholds equal the contract values. Independent: yes, because the expected
    values are literals from the contract.
    """
    assert (
        envelope.minimum_m, envelope.working_maximum_m, envelope.high_alarm_m,
        envelope.high_high_m, envelope.critical_m,
    ) == (1.8, 12, 12.5, 13, 14)  # fmt: skip
    assert envelope.available_headroom_m == 1


def test_all_three_tanks_share_the_envelope(topology: Topology) -> None:
    """All three tanks have the same level envelope. Independent: yes, because the check compares
    the tank records with each other.
    """
    assert len({LevelEnvelope.from_tank(t) for t in topology.tanks}) == 1


def test_receipt_level_rise_of_600_m3(topology: Topology) -> None:
    """A receipt of 600 m3 raises the level by 0.848826 m, both from the area and from the volume
    curve on the floating branch. Independent: yes, because the value is decimal arithmetic.
    """
    geometry = load_tank_geometry()
    assert abs(geometry.level_rise_m(600) - 0.848826) < 1e-6
    assert abs(geometry.level_rise_m(600) - float(Decimal(600) / AREA)) < 1e-12
    # On the floating branch the volume-based rise equals the area-based rise.
    h0 = 9.0
    v1 = geometry.volume_m3(h0, 750.0) + 600
    assert abs(geometry.level_m(v1, 750.0) - h0 - 0.848826) < 1e-6


def test_tank_diameter_in_configuration_matches_the_contract(topology: Topology) -> None:
    """The configured shell diameter equals the diameter in the topology contract. Independent: yes,
    because the two sources are compared with each other.
    """
    configured = load_tank_parameters()["shell_diameter_m"].value
    assert all(t.dimensions_m["diameter_m"] == configured for t in topology.tanks)


def test_unordered_thresholds_are_rejected() -> None:
    """Thresholds that are not in increasing order are rejected. Independent: yes, because the
    expected outcome is the validation rule.
    """
    with pytest.raises(ValueError):
        LevelEnvelope(1.8, 12.5, 12.0, 13, 14)


def test_negative_inputs_are_rejected(screen: HeadroomScreen) -> None:
    """A negative flow or a non-positive response time is rejected. Independent: yes, because the
    expected outcome is the validation rule.
    """
    with pytest.raises(ValueError):
        screen.evaluate(-1, 3600)
    with pytest.raises(ValueError):
        screen.limiting_flow_m3h(0)


def test_geometry_type_is_shared(screen: HeadroomScreen) -> None:
    """The screen uses the same tank geometry type as the rest of the package. Independent: yes,
    because only the type is checked.
    """
    assert isinstance(screen.geometry, TankGeometry)
