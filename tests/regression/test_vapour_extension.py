"""Closed-form tests of the reduced mechanical and vapour extension.

The checks establish numerical and bookkeeping behaviour, not field emission or damage validity.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from verum.inspection.assets import load_assets
from verum.inspection.catalog import load_catalog
from verum.inspection.models import fitting_check, rim_survey
from verum.vapour.model import (
    MechanicalFault,
    Parameters,
    cascade_child,
    mechanical_state,
    pressure_function,
    reference_window,
    roof_regime,
    validate_graph,
)


def test_pressure_function_and_rim_mass_have_independent_numeric_references() -> None:
    """A pressure ratio of three quarters gives one third and the rim conversion uses lb to kg.

    Independent: yes, because the reference substitutes table constants into the source equation.
    """
    assert pressure_function(75000.0, 100000.0) == pytest.approx(1 / 3)
    p = Parameters()
    result = reference_window(298.15, 30.0, 30.0, 0.0, 0.0, p)
    pv = 6894.757293 * math.exp(11.724 - 5237.3 / (1.8 * 298.15))
    ratio = pv / 101325.0
    pressure = ratio / (1 + math.sqrt(1 - ratio)) ** 2
    expected = 0.6 * (30.0 / 0.3048) * pressure * 66 * 0.45359237 * 30 / 365
    assert result["rim_kg"] == pytest.approx(expected)
    assert result["is_observation"] is False
    assert "not_facility_total" in result["applicability_flags"]


def test_fitting_damage_changes_one_fitting_and_seal_damage_only_the_rim() -> None:
    """One damaged hatch adds its own baseline factor while seal damage doubles only the rim.

    Independent: yes, because the ratios follow the declared one-to-two synthetic multiplier.
    """
    p = Parameters()
    base = reference_window(298.15, 30.0, 30.0, 0.0, 0.0, p)
    seal = reference_window(298.15, 30.0, 30.0, 1.0, 0.0, p)
    fitting = reference_window(298.15, 30.0, 30.0, 0.0, 1.0, p, "access_hatch")
    assert seal["rim_kg"] == pytest.approx(2 * base["rim_kg"])
    assert seal["fitting_kg"] == base["fitting_kg"]
    assert fitting["rim_kg"] == base["rim_kg"]
    assert fitting["fitting_kg"] / base["fitting_kg"] == pytest.approx(
        (1.6 + 2.8 + 2 * 6.2 + 6 * 1.0 + 1.6) / (1.6 + 2.8 + 2 * 6.2 + 6 * 1.0)
    )
    twice = reference_window(298.15, 30.0, 60.0, 0.0, 0.0, p)
    assert twice["component_sum_kg"] == pytest.approx(2 * base["component_sum_kg"])


def test_invalid_windows_phases_and_missing_fittings_are_refused() -> None:
    """Short windows, invalid absolute pressures and unnamed damaged fittings cannot produce mass.

    Independent: yes, because each case violates a declared input domain.
    """
    p = Parameters()
    for vapour, atmosphere in ((1.0, 0.0), (-1.0, 1.0), (1.0, 1.0), (math.nan, 1.0)):
        with pytest.raises(ValueError):
            pressure_function(vapour, atmosphere)
    for temperature, days in ((298.15, 1.0), (250.0, 30.0), (math.nan, 30.0)):
        with pytest.raises(ValueError):
            reference_window(temperature, 30.0, days, 0.0, 0.0, p)
    with pytest.raises(ValueError):
        reference_window(298.15, 30.0, 30.0, 0.0, 1.0, p)
    with pytest.raises(ValueError):
        MechanicalFault("x", "FITTING_DAMAGE", "TK-101", 600.0, 300.0, 1.0, "roof_leg")


def test_cascade_requires_actual_travel_and_has_a_persistent_secondary_fault() -> None:
    """A hung roof tears its seal only after the selected relative-travel threshold is crossed.

    Independent: yes, because the sample levels bracket the declared 0.05 m threshold.
    """
    p = Parameters()
    parent = MechanicalFault("parent", "ROOF_LANDING_ABNORMAL", "TK-101", 600.0, 300.0, 1.0)
    assert cascade_child(parent, [(900.0, 9.0), (960.0, 9.01)], p) is None
    child = cascade_child(parent, [(900.0, 9.0), (960.0, 9.01), (1020.0, 9.1)], p)
    assert child is not None and child.onset_s == 1020.0 and child.parent_id == "parent"
    validate_graph([parent, child])
    before = mechanical_state([parent, child], 1000.0, p)["TK-101"]
    after = mechanical_state([parent, child], 1320.0, p)["TK-101"]
    later = mechanical_state([parent, child], 9000.0, p)["TK-101"]
    assert before["rim_gap_m"] == 0.0
    assert after["rim_gap_m"] == later["rim_gap_m"] == 0.02
    with pytest.raises(ValueError):
        validate_graph([child])
    with pytest.raises(ValueError):
        validate_graph([parent, parent])


def test_normal_roof_landing_is_a_regime_without_an_injected_failure() -> None:
    """The geometric support transition does not create a fault on an intact tank.

    Independent: yes, because the support height is 1.5 m and the draft is 20/750 m.
    """
    p = Parameters()
    assert roof_regime(1.4, p) == "landed"
    assert roof_regime(1.51, p) == "transition"
    assert roof_regime(1.6, p) == "floating"
    assert mechanical_state([], 2000.0, p)["TK-101"]["rim_gap_m"] == 0.0


def test_inspections_use_mechanical_truth_and_keep_model_limits_visible() -> None:
    """Seal and fitting defects change their corresponding inspection metrics and categories.

    Independent: yes, because full severity gives 20 mm and a nonzero seating-defect code.
    """
    faults = [MechanicalFault("seal", "RIM_SEAL_DETERIORATION", "TK-101", 600., 300., 1.),
              MechanicalFault("fit", "FITTING_DAMAGE", "TK-102", 600., 300., 1., "access_hatch")]
    state = {"mechanical": mechanical_state(faults, 1200.0, Parameters())}
    catalog, assets = load_catalog(), load_assets()
    rim = rim_survey(catalog, assets, state, "TK-101", np.random.default_rng(7))
    fitting = fitting_check(catalog, assets, state, "TK-102", np.random.default_rng(7))
    assert rim.true["true_value"] == 20.0 and rim.category == "CRITICAL_DEFECT"
    assert fitting.value == 1.0 and fitting.category == "CRITICAL_DEFECT"
    assert rim.evidence == fitting.evidence == "low_confidence"
