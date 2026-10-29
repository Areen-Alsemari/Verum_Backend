"""Volatility classes and the verification gate of decision D46 version 3.

Inputs: ``config/volatility_classes.json``, ``config/volatility_gate.json`` (tabulated points of
Table 7.1-2 and the worked example of the US EPA AP-42 chapter 7.1, June 2026 edition) and the
property scenarios. Outputs: pass/fail.
Key assumptions:
    * The correlation reproduces the tabulated constants of RVP 13, 10 and 7 within 0.1 percent
      and the tabulated true vapor pressures (Table 7.1-2 at 60 F, 519.67 R, and the worked
      example at 528.37 R) within 2 percent. The edition fetched tabulates three gasoline
      classes, not the eight named in the decision; five of the named classes (7.8, 8.3, 11.5,
      13.5, 15) are not in it, which is recorded as a deviation.
    * RVP 9 gives about 44 kPa at 25 C and 82 kPa at 45 C (the expected values of the decision).
    * If the gate fails, the derived classes are unresolved and raise when selected; the audited
      RVP 10 class still works.
Independence: the tabulated values are transcribed from the EPA document; the formula and its
evaluation are recomputed here by hand arithmetic (natural logarithm of 10 is 2.302585).

Source: ``docs/design_decisions.md`` D46 version 3.
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
    """Hand: S^0.5 = 1.732051; A = 15.64 - 3.211 - (0.8742 - 0.5681) x 2.302585 = 11.724 and
    B = 8742 - 1804.8 - (1049 - 310.7) x 2.302585 = 5237.3."""
    a, b = ap42_constants(10.0)
    assert a == pytest.approx(11.724, rel=1e-3) and b == pytest.approx(5237.3, rel=1e-3)
    assert a == pytest.approx(15.64 - 1.854 * 1.732051 - (0.8742 - 0.3280 * 1.732051) * 2.302585)


def test_the_gate_passes_on_every_tabulated_point() -> None:
    gate = run_gate()
    assert gate.passed and gate.points == 5
    assert gate.worst_constant_error < 1e-4 and gate.worst_pressure_error < 0.01


def test_rvp_9_gives_about_44_and_82_kpa() -> None:
    model = HydraulicModel.load()
    p25 = vapor_pressure_pa("RVP_9_0", 25.0, model.config, model.fluid)
    p45 = vapor_pressure_pa("RVP_9_0", 45.0, model.config, model.fluid)
    assert p25 / 1000 == pytest.approx(44.0, abs=0.5) and p45 / 1000 == pytest.approx(82.0, abs=0.5)
    a, b = ap42_constants(9.0)
    assert p25 == pytest.approx(6894.757293 * math.exp(a - b / (1.8 * 298.15)), rel=1e-12)


def test_the_classes_are_ordered_and_the_legacy_name_is_the_rvp_10_class() -> None:
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


def test_a_failed_gate_leaves_the_derived_classes_unresolved(tmp_path: Path, root: Path) -> None:
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
