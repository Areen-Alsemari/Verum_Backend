"""Headroom screen, level envelope and receipt level rise.

Inputs: the topology contract, ``config/tank_geometry.json`` and decimal
arithmetic written in this module. Outputs: pass/fail.

Derivation of the expected values (independent of the package code), with
A = 225 pi = 706.858347058 m2, V_post = 20 m3, dh = 0.05 m, HH = 13 m, CH = 14 m
(available headroom 1 m):
    rise(Q, t) = (Q t + V_post) / A + dh
    600 m3/h, 1 h : (600 + 20) / A + 0.05 = 0.877121 + 0.05 = 0.927121 m
                    margin 1 - 0.927121 = 0.072879 m
    660 m3/h, 1 h : (660 + 20) / A + 0.05 = 1.012003 m -> required height 14.012003 m, fails
    900 m3/h, 1 h : (900 + 20) / A + 0.05 = 1.351 m, fails
    600 m3/h, 2 h : (1200 + 20) / A + 0.05 = 1.776 m, fails
    limiting flow for 1 h: Q = (0.95 A - 20) m3/h = 651.515 m3/h
    normal/high screen, 15 min at 600 m3/h: (150 + 20) / A + 0.05 = 0.290501 m
    receipt level rise: 600 m3 / A = 0.848826 m
Same-formula note: the rise expression is the definition of screen E7 and is
the same expression as in the implementation; the independent parts are the
decimal arithmetic, the literal values from the audited document, and the
pass/fail outcomes.

Source: ``revised/01_facility_tanks_topology.md`` section 5 (E6, E7) and
sections 6.1 and 6.4.
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
    result = screen.evaluate(600, 3600)
    assert result.passes
    assert abs(result.required_rise_m - 0.927121) < 1e-6
    assert abs(result.margin_m - 0.072879) < 1e-6
    assert abs(result.required_rise_m - float(_rise(600, 1))) < 1e-9


def test_660_for_one_hour_fails_at_the_documented_height(screen: HeadroomScreen) -> None:
    result = screen.evaluate(660, 3600)
    assert not result.passes
    assert abs(result.required_height_m - 14.012003) < 1e-6
    assert abs(result.required_height_m - float(13 + _rise(660, 1))) < 1e-9


@pytest.mark.parametrize(("flow", "hours", "rise"), [(900, 1, 1.351), (600, 2, 1.776)])
def test_larger_flow_or_longer_response_fails(
    screen: HeadroomScreen, flow: float, hours: int, rise: float
) -> None:
    result = screen.evaluate(flow, hours * 3600)
    assert not result.passes
    assert abs(result.required_rise_m - float(_rise(int(flow), hours))) < 1e-9
    assert abs(result.required_rise_m - rise) < 1e-3


def test_limiting_flow_is_651_515(screen: HeadroomScreen) -> None:
    limit = screen.limiting_flow_m3h(3600)
    assert abs(limit - 651.515) < 1e-3
    assert abs(limit - float(Decimal("0.95") * AREA - 20)) < 1e-9
    assert screen.evaluate(limit, 3600).margin_m == pytest.approx(0.0, abs=1e-12)
    assert screen.evaluate(limit + 0.01, 3600).margin_m < 0


def test_configured_response_time_is_one_hour() -> None:
    assert load_tank_parameters()["headroom_response_time_s"].value == 3600.0


def test_fifteen_minute_normal_screen_fits_between_alarm_and_high_high(
    screen: HeadroomScreen, envelope: LevelEnvelope
) -> None:
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
    assert envelope.classify(level) == expected


def test_envelope_values_come_from_the_contract(envelope: LevelEnvelope) -> None:
    assert (
        envelope.minimum_m, envelope.working_maximum_m, envelope.high_alarm_m,
        envelope.high_high_m, envelope.critical_m,
    ) == (1.8, 12, 12.5, 13, 14)  # fmt: skip
    assert envelope.available_headroom_m == 1


def test_all_three_tanks_share_the_envelope(topology: Topology) -> None:
    assert len({LevelEnvelope.from_tank(t) for t in topology.tanks}) == 1


def test_receipt_level_rise_of_600_m3(topology: Topology) -> None:
    geometry = load_tank_geometry()
    assert abs(geometry.level_rise_m(600) - 0.848826) < 1e-6
    assert abs(geometry.level_rise_m(600) - float(Decimal(600) / AREA)) < 1e-12
    # On the floating branch the volume-based rise equals the area-based rise.
    h0 = 9.0
    v1 = geometry.volume_m3(h0, 750.0) + 600
    assert abs(geometry.level_m(v1, 750.0) - h0 - 0.848826) < 1e-6


def test_tank_diameter_in_configuration_matches_the_contract(topology: Topology) -> None:
    configured = load_tank_parameters()["shell_diameter_m"].value
    assert all(t.dimensions_m["diameter_m"] == configured for t in topology.tanks)


def test_unordered_thresholds_are_rejected() -> None:
    with pytest.raises(ValueError):
        LevelEnvelope(1.8, 12.5, 12.0, 13, 14)


def test_negative_inputs_are_rejected(screen: HeadroomScreen) -> None:
    with pytest.raises(ValueError):
        screen.evaluate(-1, 3600)
    with pytest.raises(ValueError):
        screen.limiting_flow_m3h(0)


def test_geometry_type_is_shared(screen: HeadroomScreen) -> None:
    assert isinstance(screen.geometry, TankGeometry)
