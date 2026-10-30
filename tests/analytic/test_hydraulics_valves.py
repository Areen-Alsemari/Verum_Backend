"""A partly closed valve in the steady network.

A half-open receipt valve raises the source pressure by the extra loss of the valve, a closed valve
removes the path, and a nearly closed valve makes the supply cap bind. The hand value of the
pressure rise is derived in the "Partly closed valve" section of the verification notes.

See D4 and D19.
"""

from __future__ import annotations

import pytest

from _hydraulic_cases import receipt_case
from verum.graph import Lineup
from verum.hydraulics import HydraulicModel, ReceiptBoundary, SteadyInputs

AREA200 = 3.141592653589793 * 0.20274**2 / 4


def _case(model: HydraulicModel, alpha: float | None, flow: float = 600.0) -> SteadyInputs:
    base = receipt_case(
        ("TK-101",), receipt=ReceiptBoundary(flow_m3h=flow), profile="reference_fittings"
    )
    positions = {} if alpha is None else {"XV-R101": alpha}
    return SteadyInputs(**{**base.__dict__, "valve_positions": positions})


def test_half_open_valve_raises_the_source_pressure_by_the_hand_value(
    model: HydraulicModel,
) -> None:
    """A half-open valve raises the source pressure by (K(0.5) - K_open) v^2 / (2 g) of head, about
    49 kPa. Independent: yes, because the value is hand arithmetic.
    """
    open_p = model.solve(_case(model, None)).source_pressure_pa_gauge
    half_p = model.solve(_case(model, 0.5)).source_pressure_pa_gauge
    assert open_p is not None and half_p is not None
    v = (600 / 3600) / AREA200
    expected = 750.0 * 9.80665 * (5.0 - 0.1) * v * v / (2 * 9.80665)
    assert half_p - open_p == pytest.approx(expected, rel=2e-3)
    assert expected / 1000 == pytest.approx(48.98, abs=0.05)


def test_fully_open_position_equals_no_position(model: HydraulicModel) -> None:
    """A valve position of 1.0 gives exactly the same result as no position. Independent: yes,
    because the expected outcome is equality.
    """
    a = model.solve(_case(model, None)).source_pressure_pa_gauge
    b = model.solve(_case(model, 1.0)).source_pressure_pa_gauge
    assert a == b


def test_throttling_raises_the_pressure_monotonically_as_the_valve_closes(
    model: HydraulicModel,
) -> None:
    """The source pressure rises monotonically as the valve closes. Independent: yes, because only
    the direction is checked.
    """
    pressures = [
        model.solve(_case(model, a)).source_pressure_pa_gauge
        for a in (1.0, 0.8, 0.6, 0.4, 0.2, 0.1)
    ]
    assert all(p is not None for p in pressures)
    values = [p for p in pressures if p is not None]
    assert all(b > a for a, b in zip(values, values[1:], strict=False))


def test_a_nearly_closed_valve_is_cap_limited(model: HydraulicModel) -> None:
    """A nearly closed valve makes the source pressure reach the 10 barg cap and the flow fall below
    600 m3/h. Independent: yes, because the cap is the stated constant.
    """
    result = model.solve(_case(model, 0.01))
    assert result.receipt_clipped and result.source_pressure_pa_gauge == pytest.approx(
        1.0e6, rel=1e-9
    )
    assert 0.0 < result.receipt_flow_m3h < 600.0


def test_a_closed_valve_removes_the_receipt_path(model: HydraulicModel) -> None:
    """A closed tank inlet valve leaves no path to any tank. Independent: yes, because the expected
    outcome follows from the lineup.
    """
    lineup = Lineup.of({"XV-R000"})  # the tank inlet valve is closed: no path to any tank
    result = model.solve(
        SteadyInputs(
            lineup,
            {"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0},
            "EPA_GENERIC_RVP10_REFERENCE",
            25.0,
        )
    )
    assert result.receipt_flow_m3h == 0.0 and result.source_pressure_pa_gauge is None
