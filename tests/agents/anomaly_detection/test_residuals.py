"""Tests for the four topology residuals on small synthetic windows with hand-worked values."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from _anomaly_cases import healthy, parameters, signals_for
from verum.agents.anomaly_detection import residuals
from verum.agents.anomaly_detection.parameters import Parameters
from verum.agents.anomaly_detection.residuals import ResidualResult

pytestmark = pytest.mark.fast


def compute(values: Mapping[str, float | None], tmp_path: Path) -> dict[str, ResidualResult]:
    """Residuals of a synthetic window, keyed by residual name."""
    params = parameters(tmp_path)
    return {r.key: r for r in residuals.compute_residuals(signals_for(values), params)}


def fired(found: dict[str, ResidualResult], params: Parameters) -> set[str]:
    """Residuals that are above their own threshold."""
    return {
        k: r for k, r in found.items()
        if r.z is not None and r.z > params.residual_thresholds[k]
    }.keys() & set(found)  # fmt: skip


def test_a_healthy_window_gives_zero_for_every_residual(tmp_path: Path) -> None:
    """With round parameters and inputs built to fit them, every residual is exactly zero.

    Independent: yes, because the inputs are worked out by hand from the stated coefficients.
    """
    found = compute(healthy("A"), tmp_path)
    assert {k: r.z for k, r in found.items()} == {"R1": 0.0, "R2": 0.0, "R3": 0.0, "R4": 0.0}
    assert all(r.value == pytest.approx(0.0, abs=1e-9) for r in found.values())  # float rounding


@pytest.mark.parametrize(
    ("tag", "shift", "key"),
    [("LT-101", 0.001, "R1"), ("PT-201", 1.0, "R2"), ("PT-203", 1.0, "R3"), ("PT-001", 0.5, "R4")],
)
def test_each_residual_fires_when_a_tag_only_it_reads_moves(
    tag: str, shift: float, key: str, tmp_path: Path
) -> None:
    """A tag read by a single residual moves that residual and no other.

    Independent: yes, because the expected value follows from the stated coefficients by hand.
    """
    params = parameters(tmp_path)
    values = healthy("A")
    values[tag] = (values[tag] or 0.0) + shift
    found = {r.key: r for r in residuals.compute_residuals(signals_for(values), params)}
    assert fired(found, params) == {key}
    others = [r for k, r in found.items() if k != key]
    assert all(r.z == 0.0 for r in others if r.state == residuals.COMPUTED)


def test_the_residuals_have_the_physical_sign(tmp_path: Path) -> None:
    """A lower delivery flow gives a positive mass imbalance; a lower pump discharge a negative R2.

    Independent: yes, because the signs follow from the definitions written in the plan.
    """
    leak_like = healthy("A") | {"FT-201": FLOW_DROP}
    low_head = healthy("A") | {"PT-202A": healthy("A")["PT-202A"] - 1.0}
    assert compute(leak_like, tmp_path)["R1"].value == pytest.approx(400.0 - FLOW_DROP)
    assert compute(low_head, tmp_path)["R2"].value == pytest.approx(-1.0)


FLOW_DROP = 380.0


def test_tank_filling_balances_the_flow_difference(tmp_path: Path) -> None:
    """Receipt 20 m3/h above delivery is no imbalance when the three tanks gain 20 m3/h.

    Independent: yes, because 20 / (3 x 700 x 3600) per tank is worked out by hand.
    """
    slope = 20.0 / (3 * 700.0 * 3600.0)
    values = healthy("A") | {"FT-201": 380.0}
    values |= {"LT-101": slope, "LT-102": slope, "LT-103": slope}
    assert compute(values, tmp_path)["R1"].value == pytest.approx(0.0, abs=1e-9)
    emptying = values | {"LT-101": -slope, "LT-102": -slope, "LT-103": -slope}
    assert compute(emptying, tmp_path)["R1"].value == pytest.approx(40.0)


def test_a_move_inside_the_dead_zone_gives_zero(tmp_path: Path) -> None:
    """A residual smaller than one scale unit is not counted.

    Independent: yes, because the scale of the mass balance is 2.0 in the test parameters.
    """
    values = healthy("A") | {"FT-001": 401.5}
    found = compute(values, tmp_path)
    assert found["R1"].value == pytest.approx(1.5) and found["R1"].z == 0.0


def test_beyond_the_dead_zone_the_value_is_in_scale_units(tmp_path: Path) -> None:
    """A residual of 8 with scale 2 and a dead zone of one scale gives exactly 3.

    Independent: yes, because (8 - 2) / 2 is worked out by hand.
    """
    values = healthy("A") | {"FT-001": 408.0}
    assert compute(values, tmp_path)["R1"].z == pytest.approx(3.0)


def test_the_state_specific_pump_fit_is_used_when_it_exists(tmp_path: Path) -> None:
    """Pump A uses its own fit (intercept 5.5), not the pooled one (5.0).

    Independent: yes, because the two fits differ by 0.5 and the window is built for the first.
    """
    found = compute(healthy("A"), tmp_path)
    assert found["R2"].value == 0.0
    moved = healthy("A") | {"PT-202A": healthy("A")["PT-202A"] + 0.5}
    assert compute(moved, tmp_path)["R2"].value == pytest.approx(0.5)
    assert compute(healthy("B"), tmp_path)["R2"].value == 0.0


def test_no_pump_running_gives_only_r1_and_r4(tmp_path: Path) -> None:
    """With neither pump on, R2 and R3 do not apply and R1 and R4 are computed.

    Independent: yes, because the rule is stated in the plan and checked on a window with both off.
    """
    values = healthy("A") | {"P-101A": 0.0, "P-101B": 0.0}
    found = compute(values, tmp_path)
    assert found["R1"].state == found["R4"].state == residuals.COMPUTED
    assert found["R2"].state == found["R3"].state == residuals.NOT_APPLICABLE
    assert found["R2"].z is None and found["R2"].reasons == ("no pump is running",)


def test_both_pumps_running_makes_the_pump_residuals_unknown(tmp_path: Path) -> None:
    """Both pumps on was never seen in fitting, so R2 and R3 are unknown, not zero.

    Independent: yes, because the expected state follows from the rule in the module docstring.
    """
    found = compute(healthy("A") | {"P-101B": 1.0}, tmp_path)
    assert found["R2"].state == found["R3"].state == residuals.UNKNOWN
    assert found["R2"].z is None
    assert "both pumps" in found["R2"].reasons[0]


def test_a_missing_tag_makes_only_the_residuals_that_read_it_unknown(tmp_path: Path) -> None:
    """Without FT-001, R1 and R4 are unknown; R2 and R3 are still computed.

    Independent: yes, because the dependencies are listed in the plan.
    """
    found = compute(healthy("A") | {"FT-001": None}, tmp_path)
    assert (found["R1"].state, found["R4"].state) == (residuals.UNKNOWN, residuals.UNKNOWN)
    assert found["R1"].z is None and found["R4"].value is None
    assert "FT-001" in found["R1"].reasons[0]
    assert found["R2"].state == found["R3"].state == residuals.COMPUTED


def test_a_missing_pump_tag_makes_the_pump_residuals_unknown(tmp_path: Path) -> None:
    """The run state needs both pump tags; without one, R2 and R3 are unknown.

    Independent: yes, because the rule is stated in the plan.
    """
    found = compute(healthy("A") | {"P-101B": None}, tmp_path)
    assert found["R2"].state == found["R3"].state == residuals.UNKNOWN
    assert "P-101B" in found["R2"].reasons[0]
    assert found["R1"].state == found["R4"].state == residuals.COMPUTED


def test_an_unusable_unit_or_value_is_unknown(tmp_path: Path) -> None:
    """A wrong unit, a non-finite value or a boolean where a number is expected is unusable.

    Independent: yes, because each case is written out.
    """
    params = parameters(tmp_path)
    base = signals_for(healthy("A"))

    def run(edit: Any) -> dict[str, ResidualResult]:
        signals = [dict(s) for s in base]
        edit(signals)
        return {r.key: r for r in residuals.compute_residuals(signals, params)}

    unit = run(lambda s: s[0].update(unit="bar"))
    assert unit["R1"].state == residuals.UNKNOWN and "unit" in unit["R1"].reasons[0]
    nan = run(lambda s: s[0].update(mean=float("nan")))
    assert nan["R1"].state == residuals.UNKNOWN
    flag = run(lambda s: s[0].update(mean=True))
    assert flag["R1"].state == residuals.UNKNOWN
    absent = run(lambda s: s.pop(0))
    assert absent["R1"].reasons[0] == "FT-001: tag not in the request"


@pytest.mark.parametrize(("raw", "expected"), [(True, 1.0), (False, 0.0), (1, 1.0), (0.0, 0.0)])
def test_run_states_accept_booleans_and_zero_one_numbers(
    raw: object, expected: float, tmp_path: Path
) -> None:
    """A run state is a boolean or exactly 0 or 1; anything else is unusable.

    Independent: yes, because the accepted forms are listed in the test.
    """
    params = parameters(tmp_path)
    signals = signals_for(healthy("A"))
    next(s for s in signals if s["tag_id"] == "P-101A")["latest_value"] = raw
    assert residuals.read_window(signals, params)["P-101A"].value == expected
    next(s for s in signals if s["tag_id"] == "P-101A")["latest_value"] = 0.5
    assert residuals.read_window(signals, params)["P-101A"].value is None


def test_the_window_score_is_the_largest_computed_residual_only(tmp_path: Path) -> None:
    """Unknown and not-applicable residuals never enter the maximum; none computed gives None.

    Independent: yes, because the values are worked out by hand.
    """
    values = healthy("A") | {"FT-001": 408.0, "PT-203": healthy("A")["PT-203"] + 1.0}
    found = list(compute(values, tmp_path).values())
    assert residuals.window_score(found) == pytest.approx(19.0)
    assert residuals.window_score([r for r in found if r.state != residuals.COMPUTED]) is None
    blank = compute({k: None for k in healthy("A")}, tmp_path)
    assert residuals.window_score(list(blank.values())) is None
