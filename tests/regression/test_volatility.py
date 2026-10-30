"""Volatility classes and the verification gate of the property scenarios.

The correlation must reproduce the tabulated constants of RVP 13, 10 and 7 within 0.1 percent and
the tabulated vapor pressures within 2 percent, and RVP 9 gives about 44 kPa at 25 C and 82 kPa at
45 C. If the gate fails, the derived classes are unresolved and raise when selected, while the
audited RVP 10 class still works. The tabulated values are transcribed from the EPA document, and
the formula is recomputed by hand. The bracketing argument is in the "Volatility classes" section of
the verification notes.

See D46.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import pytest

from verum.hydraulics import HydraulicModel
from verum.hydraulics.properties import vapor_pressure_pa
from verum.hydraulics.volatility import ap42_constants, derived_constants, run_gate
from verum.params import UnresolvedParameter


def test_the_formula_reproduces_the_rvp_10_constants() -> None:
    """The correlation gives the constants A = 11.724 and B = 5237.3 for RVP 10. Independent: yes,
    because the values are hand arithmetic.
    """
    a, b = ap42_constants(10.0)
    assert a == pytest.approx(11.724, rel=1e-3) and b == pytest.approx(5237.3, rel=1e-3)
    assert a == pytest.approx(15.64 - 1.854 * 1.732051 - (0.8742 - 0.3280 * 1.732051) * 2.302585)


def test_the_gate_passes_on_every_tabulated_point() -> None:
    """The verification gate passes on all five tabulated points, with constants within 0.01 percent
    and pressures within 1 percent. Independent: yes, because the tabulated values are transcribed
    from the EPA document.
    """
    gate = run_gate()
    assert gate.passed and gate.points == 5
    assert gate.worst_constant_error < 1e-4 and gate.worst_pressure_error < 0.01


def test_rvp_9_gives_about_44_and_82_kpa() -> None:
    """RVP 9 gives about 44 kPa at 25 C and 82 kPa at 45 C. Independent: yes, because the expected
    values are those of the decision.
    """
    model = HydraulicModel.load()
    p25 = vapor_pressure_pa("RVP_9_0", 25.0, model.config, model.fluid)
    p45 = vapor_pressure_pa("RVP_9_0", 45.0, model.config, model.fluid)
    assert p25 / 1000 == pytest.approx(44.0, abs=0.5) and p45 / 1000 == pytest.approx(82.0, abs=0.5)
    a, b = ap42_constants(9.0)
    assert p25 == pytest.approx(6894.757293 * math.exp(a - b / (1.8 * 298.15)), rel=1e-12)


def test_the_classes_are_ordered_and_the_legacy_name_is_the_rvp_10_class() -> None:
    """The vapor pressure rises with the volatility class, and the legacy reference name equals the
    RVP 10 class. Independent: yes, because only the ordering and equality are checked.
    """
    model = HydraulicModel.load()
    for t in (25.0, 35.0, 40.0, 45.0):
        p = [
            vapor_pressure_pa(c, t, model.config, model.fluid)
            for c in ("RVP_9_0", "RVP_9_5", "RVP10")
        ]
        assert p == sorted(p) and len(set(p)) == 3
        assert p[2] == vapor_pressure_pa(
            "EPA_GENERIC_RVP10_REFERENCE", t, model.config, model.fluid
        )


def test_derived_classes_lie_between_the_tabulated_rvp_7_and_rvp_10_values(root: Path) -> None:
    """The derived classes lie between the tabulated RVP 7 and RVP 10 values at 25, 35, 40 and 45 C.
    Independent: yes, because the bracketing is a necessary check and not a validation of the
    derived classes.
    """
    gate = json.loads((root / "config" / "volatility_gate.json").read_text())
    tab = {row["rvp_psi"]: row for row in gate["table_7_1_2"]}
    assert 8.3 not in tab  # the class the decision asked for is not in the edition fetched
    model = HydraulicModel.load()
    psi_to_pa = 6894.757293

    def tabulated(rvp: float, celsius: float) -> float:
        t_rankine = 1.8 * (celsius + 273.15)
        return psi_to_pa * math.exp(tab[rvp]["A"] - tab[rvp]["B_degR"] / t_rankine)

    for t in (25.0, 35.0, 40.0, 45.0):
        low, high = tabulated(7.0, t), tabulated(10.0, t)
        p90 = vapor_pressure_pa("RVP_9_0", t, model.config, model.fluid)
        p95 = vapor_pressure_pa("RVP_9_5", t, model.config, model.fluid)
        assert low < p90 < p95 < high, t


def test_a_failed_gate_leaves_the_derived_classes_unresolved(tmp_path: Path, root: Path) -> None:
    """A failed gate leaves the derived classes unresolved so that they raise when selected.
    Independent: yes, because the expected outcome is the rule that nothing replaces an unresolved
    parameter.
    """
    shutil.copytree(root / "config", tmp_path / "config")
    path = tmp_path / "config" / "volatility_gate.json"
    doc = json.loads(path.read_text())
    doc["table_7_1_2"][1]["B_degR"] *= 1.05  # a tabulated constant that the formula cannot meet
    path.write_text(json.dumps(doc))
    assert not run_gate(tmp_path / "config").passed
    for a, b in derived_constants(tmp_path / "config").values():
        assert not a.is_resolved and not b.is_resolved
    local = HydraulicModel.load(tmp_path / "config")
    with pytest.raises(UnresolvedParameter):
        vapor_pressure_pa("RVP_9_0", 25.0, local.config, local.fluid)
    with pytest.raises(UnresolvedParameter):
        vapor_pressure_pa("RVP_9_5", 25.0, local.config, local.fluid)
    assert vapor_pressure_pa("RVP10", 25.0, local.config, local.fluid) == pytest.approx(
        49200, rel=2e-3
    )
