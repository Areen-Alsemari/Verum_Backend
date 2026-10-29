"""Atmospheric pressure comes from configuration; the site-pressure sensitivity file.

Inputs: ``config/hydraulics.json``, the source tree, ``config/pumping_minimum_levels*.json``.
Outputs: pass/fail.
Key assumptions:
    * No source file contains the sea-level atmosphere as a literal; every use reads
      the ``atmosphere_pa_abs`` parameter.
    * The site table (94300 Pa) is a sensitivity run, labelled as an estimate for a
      site near 600 m elevation whose elevation is to be confirmed by the team. It
      is a separate file and never overwrites the sea-level table.
    * Changing the atmosphere shifts absolute pressures and NPSHa by exactly the
      pressure difference (and the difference divided by rho g for NPSHa).
Independence: the shift identities are hand arithmetic; the stored-level checks use
the production solver and confirm the study file only.

Source: decision D7 (version 2.0), D11; ``revised/02_hydraulic_model.md`` section 4.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from _hydraulic_cases import TANKS, delivery_case
from verum.hydraulics import HydraulicModel, pumping_minimum_level
from verum.hydraulics.pumping_minimum import SITE_PRESSURE_FILENAME
from verum.params import ParamValue

SITE_PA = 94300.0
LABEL = (
    "sensitivity for a site near 600 m elevation, standard-atmosphere estimate, "
    "elevation from memory, to be confirmed by the team"
)


def _site_model(model: HydraulicModel) -> HydraulicModel:
    params = dict(model.config.parameters)
    params["atmosphere_pa_abs"] = ParamValue.selected(SITE_PA, "Pa", "SIM", "TEST")
    return HydraulicModel(
        model.topology,
        model.geometry,
        model.fluid,
        dataclasses.replace(model.config, parameters=params),
    )


def test_no_source_file_hard_codes_the_coastal_atmosphere(root: Path) -> None:
    pattern = re.compile(r"101325|101\.325|1\.01325")
    hits = [
        p.as_posix()
        for p in (root / "src").rglob("*.py")
        if pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert hits == []


def test_the_atmosphere_is_a_configured_parameter(model: HydraulicModel) -> None:
    record = model.config.record("atmosphere_pa_abs")
    assert record.value == 101325.0 and record.status == "provisional" and record.provenance_id


def test_a_lower_atmosphere_shifts_pressures_and_npsha_by_the_difference(
    model: HydraulicModel,
) -> None:
    sea = model.solve(delivery_case("TK-102", 7.0))
    site = _site_model(model).solve(delivery_case("TK-102", 7.0))
    delta = 101325.0 - SITE_PA
    assert sea.pump is not None and site.pump is not None
    assert site.pump.flow_m3h == sea.pump.flow_m3h  # hydraulics do not depend on the atmosphere
    assert sea.phase.min_abs_pressure_pa is not None and site.phase.min_abs_pressure_pa is not None
    assert sea.phase.min_abs_pressure_pa - site.phase.min_abs_pressure_pa == pytest.approx(
        delta, abs=1e-6
    )
    assert sea.phase.npsha_m is not None and site.phase.npsha_m is not None
    assert sea.phase.npsha_m - site.phase.npsha_m == pytest.approx(
        delta / (750.0 * 9.80665), rel=1e-9
    )
    tap = "PUMP_SUCTION_TEE"
    assert site.to_abs(site.tap_pressures_pa_gauge[tap]) == pytest.approx(
        sea.to_abs(sea.tap_pressures_pa_gauge[tap]) - delta, abs=1e-6
    )


def test_the_site_file_is_a_separate_labelled_sensitivity(root: Path) -> None:
    site = json.loads((root / "config" / SITE_PRESSURE_FILENAME).read_text(encoding="utf-8"))
    assert site["label"] == LABEL
    assert site["atmosphere_pa_abs"] == SITE_PA
    sea = json.loads((root / "config" / "pumping_minimum_levels.json").read_text(encoding="utf-8"))
    assert "label" not in sea and "atmosphere_pa_abs" not in sea
    assert site["levels"] != sea["levels"]


COMBINATIONS = [
    (t, s, p, c)
    for t in TANKS
    for s in (25.0, 35.0, 45.0)
    for p in ("pipe_only", "reference_fittings")
    for c in (2.5, 4.0, 6.0)
]


@pytest.mark.parametrize(("tank", "temp", "profile", "coeff"), COMBINATIONS)
def test_site_levels_are_never_lower_than_coastal_and_match_the_solver(
    model: HydraulicModel, tank: str, temp: float, profile: str, coeff: float
) -> None:
    site_model = _site_model(model)
    sea = pumping_minimum_level(tank, temp, profile, coeff)
    site = pumping_minimum_level(tank, temp, profile, coeff, filename=SITE_PRESSURE_FILENAME)
    if sea.is_resolved:
        assert not site.is_resolved or site.value >= sea.value - 1e-9
    if not site.is_resolved:
        status = site_model.solve(
            delivery_case(tank, 12.0, profile=profile, temperature_c=temp, npsh3=coeff)
        ).phase.status
        assert status != "OK"
        return
    ok = site_model.solve(
        delivery_case(tank, site.value, profile=profile, temperature_c=temp, npsh3=coeff)
    )
    assert ok.phase.status == "OK"
    if site.value > 1.8:
        low = site_model.solve(
            delivery_case(tank, site.value - 2e-4, profile=profile, temperature_c=temp, npsh3=coeff)
        )
        assert low.phase.status != "OK"
