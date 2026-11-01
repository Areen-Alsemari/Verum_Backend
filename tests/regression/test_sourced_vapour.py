"""AP-42 published-example checks and explicit applicability boundaries.

The worked example is a different tank from Verum and verifies equations, not site calibration.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from verum.params import ParamValue, UnresolvedParameter
from verum.vapour.campaign import generate
from verum.vapour.model import MechanicalFault, Parameters, cascade_child, reference_window
from verum.vapour.routine import (
    RoutineFactors,
    cumulative_fall,
    seam_factor,
    standing_components_kg,
    uncontrolled_fitting_factor,
    withdrawal_kg,
)


def p(value: float, unit: str) -> ParamValue:
    return ParamValue.selected(value, unit, "SIM", "literal-test-fixture")


def test_epa_example_four_normal_components_match_published_results() -> None:
    """Example 4 gives 136.5, 231.8 and 3961.9 lb/yr for withdrawal, rim and fittings.

    Independent: yes, because these targets are published EPA Example 4 results.
    """
    factors = RoutineFactors()
    diameter = p(70 * .3048, "m")
    mw = p(62., "kg/kmol")
    # Algebraic inverse of P*=r/(1+sqrt(1-r))^2 supplies the published rounded P*=0.178.
    ratio = 4 * .178 / (1 + .178)**2
    fitting_rows = [(2, "hatch_unbolted_ungasketed"),
                    (1, "automatic_float_well_unbolted_ungasketed"),
                    (1, "pipe_column_fabric_sleeve"), (1, "ladder_well_gasketed"),
                    (20, "adjustable_ifr_leg_sleeve_under_12in"),
                    (1, "slotted_guidepole_gasketed"), (1, "vacuum_breaker_weighted_gasketed")]
    result = standing_components_kg(
        p(ratio * 101325., "Pa_abs"), p(101325., "Pa_abs"), mw, p(1., "1"), diameter,
        p(.3, "lbmol/(ft yr)"), [(p(n, "1"), key) for n, key in fitting_rows],
        p(0., "lbmol/yr"), factors, maintained=True, freely_vented=True,
        continuously_floating=True,
    )
    density = p(5.6 * .45359237 / .003785411784, "kg/m3")
    working = withdrawal_kg(p(1735 * .3048, "m"), diameter, density,
                            p(math.pi * .3048, "m"), "light_rust", factors)
    assert working / .45359237 == pytest.approx(136.5, abs=.1)
    assert result["rim_kg"] / .45359237 == pytest.approx(231.8, abs=.1)
    # The source sums these factors to 359.2, then prints/uses rounded FF=359.
    rounding_delta_lb = .2 * .178 * 62
    assert result["fitting_kg"] / .45359237 == pytest.approx(359.2 * .178 * 62, abs=1e-8)
    assert result["fitting_kg"] / .45359237 - rounding_delta_lb == pytest.approx(3961.9, abs=.1)
    corrected_total = (working + result["standing_components_kg"]) / .45359237 - rounding_delta_lb
    assert corrected_total == pytest.approx(4330.2, abs=.2)
    assert result["uncertainty"]["status"] == "unresolved"
    assert result["facility_qualified"] is False


def test_concurrent_receipt_does_not_turn_gross_discharge_into_withdrawal_loss() -> None:
    """Withdrawal follows cumulative level decreases, retaining separate draw-down cycles.

    Independent: yes, because the literal series decreases by 1 m and then 0.5 m.
    """
    assert cumulative_fall([(0., 9.), (10., 8.), (20., 9.), (30., 8.5)]) == 1.5
    assert cumulative_fall([(0., 9.), (10., 9.), (20., 9.5)]) == 0.
    with pytest.raises(ValueError):
        cumulative_fall([(10., 9.), (0., 8.)])


def test_unmatched_fitting_and_honeycomb_seam_are_not_imputed() -> None:
    """Unknown construction raises; full contact alone cannot select welded or bolted seams.

    Independent: yes, because neither input specifies an EPA equipment class.
    """
    factors = RoutineFactors()
    with pytest.raises(UnresolvedParameter):
        factors.value("suspension_group")
    with pytest.raises(UnresolvedParameter):
        seam_factor("honeycomb", p(10., "m"), p(100., "m2"), p(10., "m"), factors)
    assert factors.value("fixed_hanger_no_opening") == 0.
    ratio = factors.value("hatch_unbolted_gasketed") / factors.value("hatch_bolted_gasketed")
    assert ratio == 19.375


def test_uncontrolled_correlation_requires_its_published_geometry_and_control_domain() -> None:
    """A 100-square-inch exposed area uses 0.27 A^0.86 only with sufficient well height.

    Independent: yes, because the reference substitutes the source's published constants directly.
    """
    factors = RoutineFactors()
    area = p(100 * .0254**2, "m2")
    assert uncontrolled_fitting_factor(area, p(.3048, "m"), factors,
                                      uncontrolled=True) == pytest.approx(.27 * 100**.86)
    with pytest.raises(UnresolvedParameter):
        uncontrolled_fitting_factor(area, p(.3, "m"), factors, uncontrolled=True)
    with pytest.raises(ValueError):
        uncontrolled_fitting_factor(area, p(.4, "m"), factors, uncontrolled=False)


def test_bolted_seams_follow_actual_length_and_area() -> None:
    """For a circular 10-foot deck and 100-foot seams, Kd Sd D² is 0.14 times 400/pi.

    Independent: yes, because the expected expression follows the published seam definition.
    """
    factors = RoutineFactors()
    actual = seam_factor("bolted", p(100 * .3048, "m"),
                         p(math.pi * (10 * .3048)**2 / 4, "m2"),
                         p(10 * .3048, "m"), factors)
    assert actual == pytest.approx(.14 * 400 / math.pi)
    missing = ParamValue.unresolved("m", "panel dimensions unavailable")
    with pytest.raises(UnresolvedParameter):
        seam_factor("bolted", missing, p(1., "m2"), p(1., "m"), factors)


def test_routine_factors_do_not_predict_damaged_or_landed_tanks() -> None:
    """Routine factors refuse damaged materials, inadequate ventilation and a landed roof.

    Independent: yes, because EPA's scope excludes these uses of the normal floating equations.
    """
    factors = RoutineFactors()
    args: tuple[Any, ...] = (p(1., "Pa_abs"), p(2., "Pa_abs"), p(66., "kg/kmol"), p(1., "1"),
            p(30., "m"), p(.6, "lbmol/(ft yr)"), [], p(0., "lbmol/yr"), factors)
    for flags in ((False, True, True), (True, False, True), (True, True, False)):
        with pytest.raises(ValueError):
            standing_components_kg(*args, maintained=flags[0], freely_vented=flags[1],
                                   continuously_floating=flags[2])


def test_legacy_damage_and_cascade_models_require_explicit_research_opt_in(tmp_path: Path) -> None:
    """Legacy travel and emission proxies cannot silently create a physical training dataset.

    Independent: yes, because the default call must fail before producing an output directory.
    """
    factors = Parameters()
    parent = MechanicalFault("root", "ROOF_LANDING_ABNORMAL", "TK-101", 600., 300., 1.)
    with pytest.raises(UnresolvedParameter):
        cascade_child(parent, [(900., 9.), (1000., 8.)], factors)
    with pytest.raises(UnresolvedParameter):
        reference_window(298.15, 30., 30., 0., 0., factors)
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="research"):
        generate(tmp_path / "base", output, 5)
    assert not output.exists()
