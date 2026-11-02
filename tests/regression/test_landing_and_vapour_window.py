"""Liquid-heel conservation and complete routine-window input boundaries.

References are published EPA equations, source coefficients and independent ideal-gas arithmetic.
Synthetic fixture classifications test software and do not select Verum's missing hardware.
"""

from __future__ import annotations

import copy
import math
from typing import Any

import pytest

from verum.params import ParamValue, UnresolvedParameter
from verum.vapour.landing import heel_landing_episode, landing_daily_expansion
from verum.vapour.window import estimate_window


def p(value: float, unit: str) -> ParamValue:
    return ParamValue.selected(value, unit, "SIM", "literal-software-test")


def record(value: float, unit: str) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "status": "provisional",
        "evidence_tag": "SIM",
        "provenance_id": "literal-software-test",
    }


def landing() -> dict[str, Any]:
    return dict(
        diameter=p(10.0, "m"),
        vapour_height=p(1.0, "m"),
        heel_volume=p(10.0, "m3"),
        liquid_density=p(750.0, "kg/m3"),
        idle_time=p(86400.0, "s"),
        daily_expansion=p(0.1, "1/day"),
        prior_pressure=p(30000.0, "Pa_abs"),
        atmosphere=p(101325.0, "Pa_abs"),
        prior_temperature=p(300.0, "K"),
        prior_molecular_mass=p(66.0, "kg/kmol"),
        heel="full",
        normal_supported_landing=True,
        freely_vented=True,
        maintained=True,
        refill_completed=True,
        incoming_pressure=p(30000.0, "Pa_abs"),
        incoming_temperature=p(300.0, "K"),
        incoming_molecular_mass=p(66.0, "kg/kmol"),
    )


def saturated() -> float:
    # Direct ideal-gas calculation with the independently converted published gas constant.
    r_si = 10.731 * 6894.757293168 * 0.3048**3 / (0.45359237 * (5 / 9))
    return 30000.0 * (math.pi * 10**2 / 4) * 66.0 / (r_si * 300.0)


def test_daily_expansion_uses_explicit_thermal_and_vapour_pressure_spans() -> None:
    """Equation 1-5 combines fractional thermal expansion and the fractional pressure change.

    Independent: yes, because the two ratios and source upper bound are computed separately.
    """
    result = landing_daily_expansion(
        p(300.0, "K"), p(6.0, "K"), p(30000.0, "Pa_abs"), p(1000.0, "Pa"), p(101325.0, "Pa_abs")
    )
    assert result.value == pytest.approx(0.02 + 1000.0 / 71325.0)
    assert (
        landing_daily_expansion(
            p(300.0, "K"),
            p(600.0, "K"),
            p(30000.0, "Pa_abs"),
            p(1000.0, "Pa"),
            p(101325.0, "Pa_abs"),
        ).value
        == 1.0
    )
    with pytest.raises(UnresolvedParameter):
        landing_daily_expansion(
            p(300.0, "K"),
            ParamValue.unresolved("K", "weather unknown"),
            p(30000.0, "Pa_abs"),
            p(1000.0, "Pa"),
            p(101325.0, "Pa_abs"),
        )


def test_heel_landing_matches_ideal_gas_and_published_saturation_factors() -> None:
    """One day uses n KE KS and a full-heel refilling saturation of 0.6.

    Independent: yes, because ideal-gas mass and the source expressions are calculated separately.
    """
    result = heel_landing_episode(**landing())
    ks = min(0.6, 1 / (1 + 0.053 * (30000 / 6894.757293168) / 0.3048))
    assert result["standing_idle_kg"] == pytest.approx(0.1 * ks * saturated())
    assert result["filling_kg"] == pytest.approx(0.6 * saturated())
    assert result["arrival_kg"] == pytest.approx(0.45 * saturated())
    assert result["generated_kg"] == pytest.approx(0.15 * saturated())
    assert result["facility_qualified"] is False
    assert result["uncertainty"]["status"] == "unresolved"


def test_depleted_heel_is_not_counted_again_as_an_arrival_loss() -> None:
    """A one-gram heel caps standing loss and leaves only incoming-generated vapours.

    Independent: yes, because the available prior mass is explicitly 0.001 kg.
    """
    args = landing() | {"heel_volume": p(0.001 / 750, "m3"), "idle_time": p(86400e6, "s")}
    result = heel_landing_episode(**args)
    assert result["standing_idle_kg"] == pytest.approx(0.001)
    assert result["arrival_kg"] == 0.0
    assert result["total_kg"] == pytest.approx(0.001 + 0.15 * saturated())


def test_change_of_service_uses_incoming_properties_only_for_generated_vapour() -> None:
    """Halving incoming vapour pressure halves only the generated component.

    Independent: yes, because ideal-gas mass is linear in the specified partial pressure.
    """
    result = heel_landing_episode(**(landing() | {"incoming_pressure": p(15000.0, "Pa_abs")}))
    assert result["arrival_kg"] == pytest.approx(0.45 * saturated())
    assert result["generated_kg"] == pytest.approx(0.075 * saturated())


def test_partial_day_and_partial_heel_are_distinct_from_refilling() -> None:
    """Six hours prorates idle loss; an unfinished landing has no fabricated filling estimate.

    Independent: yes, because the source allows daily idle loss multiplied by 6/24.
    """
    args = landing() | {"idle_time": p(21600.0, "s"), "heel": "partial", "refill_completed": False}
    result = heel_landing_episode(**args)
    ks = min(0.5, 1 / (1 + 0.053 * (30000 / 6894.757293168) / 0.3048))
    assert result["standing_idle_kg"] == pytest.approx(0.25 * 0.1 * ks * saturated())
    assert result["filling_kg"] is None and result["total_kg"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"normal_supported_landing": False},
        {"freely_vented": False},
        {"maintained": False},
        {"maintained": "false"},
        {"refill_completed": "false"},
        {"prior_pressure": p(101325.0, "Pa_abs")},
        {"daily_expansion": p(1.1, "1/day")},
        {"prior_temperature": p(0.0, "K")},
        {"diameter": p(10.0, "ft")},
    ],
)
def test_landing_applicability_and_units_fail_closed(change: dict[str, Any]) -> None:
    """Invalid regimes, pressures, temperatures, expansion and units cannot produce estimates.

    Independent: yes, because each input violates a stated applicability or dimensional condition.
    """
    with pytest.raises(ValueError):
        heel_landing_episode(**(landing() | change))


def test_unknown_heel_and_incoming_properties_remain_unresolved() -> None:
    """A drain-dry roof needs another method and refilling needs actual incoming properties.

    Independent: yes, because no physical input is supplied for either requested extension.
    """
    for change in (
        {"heel": "drain_dry"},
        {"incoming_pressure": None},
        {"daily_expansion": ParamValue.unresolved("1/day", "weather unknown")},
    ):
        with pytest.raises(UnresolvedParameter):
            heel_landing_episode(**(landing() | change))


def window() -> dict[str, Any]:
    return {
        "tank_id": "TK-101",
        "maintained": True,
        "freely_vented": True,
        "constant_conditions": True,
        "roof_follows_liquid": True,
        "property_profile": "literal-software-test-only",
        "level_interpolation": "piecewise_linear",
        "window_start_utc": "2026-01-01T00:00:00Z",
        "window_end_utc": "2026-01-31T00:00:00Z",
        "level_samples_s_m": [[0.0, 9.0], [86400.0 * 15, 8.0], [86400.0 * 30, 9.0]],
        "seam_construction": "welded",
        "seam_basis": "synthetic unit-test choice only",
        "rim_classification": "mechanical_shoe_rim_secondary",
        "rim_fit_class": "average",
        "rim_basis": "synthetic unit-test choice only",
        "shell_condition": "light_rust",
        "parameters": {
            "maximum_level_interval": record(86400.0 * 15, "s"),
            "liquid_density": record(750.0, "kg/m3"),
            "vapour_pressure": record(30000.0, "Pa_abs"),
            "atmosphere": record(101325.0, "Pa_abs"),
            "vapour_molecular_mass": record(66.0, "kg/kmol"),
            "seam_length": {
                "value": None,
                "unit": "m",
                "status": "unresolved",
                "evidence_tag": "OPEN",
                "unresolved_reason": "welded test",
            },
        },
        "fittings": [
            {
                "group": group,
                "count": record(n, "1"),
                "classification": key,
                "basis": "synthetic unit-test choice only",
            }
            for group, n, key in (
                ("access_hatch", 1, "hatch_bolted_gasketed"),
                ("gauge_well", 1, "automatic_float_well_bolted_gasketed"),
                ("vacuum_breaker", 2, "vacuum_breaker_weighted_gasketed"),
            )
        ]
        + [
            {
                "group": "suspension",
                "count": record(6.0, "1"),
                "classification": "uncontrolled_well",
                "uncontrolled": True,
                "exposed_area": record(0.01, "m2"),
                "well_height": record(0.4, "m"),
                "basis": "synthetic unit-test choice only",
            }
        ],
    }


def test_complete_window_has_independent_standing_and_actual_withdrawal_terms() -> None:
    """The 30-day standing terms and a 1 m cumulative fall are calculated separately.

    Independent: yes, because expected terms follow the source equations in customary units.
    """
    result = estimate_window(window())
    ratio = 30000.0 / 101325.0
    pstar = ratio / (1 + math.sqrt(1 - ratio)) ** 2
    extra = 6 * 0.27 * (0.01 / 0.0254**2) ** 0.86
    expected_standing = (
        (0.6 * 30 / 0.3048 + 1.6 + 2.8 + 2 * 6.2 + extra) * pstar * 66 * 0.45359237 * 30 / 365
    )
    expected_working = math.pi * 30 * 0.0015 * 0.158987294928 / (1000 * 0.3048**2) * 750
    assert result["standing_components_kg"] == pytest.approx(expected_standing)
    assert result["withdrawal_kg"] == pytest.approx(expected_working)
    assert result["total_kg"] == pytest.approx(expected_standing + expected_working)
    assert result["recorded_level_fall_m"] == 1.0
    assert result["facility_qualified"] is False
    changed = copy.deepcopy(window())
    changed["fittings"][3]["exposed_area"] = record(0.02, "m2")
    assert estimate_window(changed)["input_sha256"] != result["input_sha256"]


@pytest.mark.parametrize(
    "case",
    [
        "short",
        "incomplete",
        "no_openings",
        "landed",
        "sparse",
        "wrong_class",
        "closed",
        "missing_basis",
        "wrong_end",
    ],
)
def test_window_rejects_incomplete_inventory_and_inapplicable_regimes(case: str) -> None:
    """Missing openings, unsupported classifications and incompatible windows fail closed.

    Independent: yes, because each case independently violates the fixed inventory or method scope.
    """
    doc = window()
    if case == "short":
        doc["window_end_utc"] = "2026-01-02T00:00:00Z"
    if case == "incomplete":
        doc["fittings"].pop()
    if case == "no_openings":
        doc["fittings"][3]["classification"] = "fixed_hanger_no_opening"
    if case == "landed":
        doc["level_samples_s_m"][1][1] = 1.5
    if case == "sparse":
        doc["parameters"]["maximum_level_interval"] = record(1.0, "s")
    if case == "wrong_class":
        doc["fittings"][0]["classification"] = "vacuum_breaker_weighted_gasketed"
    if case == "closed":
        doc["freely_vented"] = False
    if case == "missing_basis":
        doc["rim_basis"] = ""
    if case == "wrong_end":
        doc["level_samples_s_m"][-1][0] -= 1
    with pytest.raises((ValueError, UnresolvedParameter)):
        estimate_window(doc)
