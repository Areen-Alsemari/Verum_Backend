"""Per-stratum pumping-minimum files against the phase and NPSH screen and the engine's SG0.

Inputs: ``config/pumping_minimum_levels_{sea_level,elevated}_fd0p8.json``, the steady
solver at the atmosphere of each stratum, and short engine runs. Outputs: pass/fail.
Key assumptions:
    * Decisions D23 and D24: the files are computed at the worst-case downstream factor
      f_d = 0.8 (the largest flow, the smallest NPSH margin) for both profiles and the NPSH3
      sweep, so a level at or above the stored minimum passes the screen at every f_d in
      [0.8, 1.25], and a level just below it fails at f_d = 0.8.
    * The engine's SG0 compares the level with the stored minimum at every step and checks
      the screen with the solved flow; it must never accept a state that the screen rejects.
    * Pump domain: the delivery flow stays below 350 m3/h over the f_d range at every level.
Independence: not independent in the hydraulics. The screen is the steady solver (the same
formulas as the study that wrote the files); the test checks that the stored files, the
solver and the engine agree with each other and that the minimum is sharp.

Source: ``docs/design_decisions.md`` D7, D23, D24.
"""

from __future__ import annotations

import dataclasses
import itertools
from typing import Any

import pytest

from verum.graph import Lineup
from verum.hydraulics import (
    DeliveryBoundary,
    HydraulicModel,
    SteadyInputs,
    load_boundary_law_coefficient,
    pumping_minimum_level,
)
from verum.hydraulics.pumping_minimum import STRATUM_FILENAMES
from verum.lineups import load_lineup_table
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.scenario import load_scenario
from verum.truth import ListSink

SCENARIO = "EPA_GENERIC_RVP10_REFERENCE"
TANKS = ("TK-101", "TK-102", "TK-103")
PROFILES = ("pipe_only", "reference_fittings")
TEMPS = (25.0, 35.0, 45.0)
COEFFS = (2.5, 4.0, 6.0)
STRATA = ("sea_level", "elevated")
EPS = 0.01  # m, distance below the stored minimum
ABOVE = 0.1  # m above it: the level falls about 0.04 m in the 300 s run, so it stays above


def _status(model: HydraulicModel, tank: str, level: float, profile: str, temp: float,
            coeff: float, f_d: float) -> str:  # fmt: skip
    c = load_boundary_law_coefficient(profile).value * f_d
    inputs = SteadyInputs(
        Lineup.of({f"XV-S{tank[3:]}", "XV-PAI", "XV-PAO"}, {"P-101A"}),
        {tank: level},
        SCENARIO,
        temp,
        fitting_profile=profile,
        delivery=DeliveryBoundary(law_coefficient_m=c),
        npsh3_coefficient_m=coeff,
    )
    return model.solve(inputs).phase.status


def _minimum(stratum: str, tank: str, temp: float, profile: str, coeff: float) -> float | None:
    record = pumping_minimum_level(tank, temp, profile, coeff, None, STRATUM_FILENAMES[stratum])
    return record.value if record.status != "unresolved" else None


@pytest.mark.parametrize("stratum", STRATA)
def test_levels_at_or_above_the_stored_minimum_pass_at_every_factor(
    model: HydraulicModel, stratum: str
) -> None:
    m = model.for_stratum(stratum)
    checked = 0
    for tank, temp, profile, coeff in itertools.product(TANKS, TEMPS, PROFILES, COEFFS):
        minimum = _minimum(stratum, tank, temp, profile, coeff)
        if minimum is None:
            continue
        level = max(minimum + EPS, 1.8)
        if level > 12.0:
            continue
        for f_d in (0.8, 1.0, 1.25):
            assert _status(m, tank, level, profile, temp, coeff, f_d) == "OK", (
                stratum, tank, temp, profile, coeff, f_d,
            )  # fmt: skip
        checked += 1
    assert checked >= 40


@pytest.mark.parametrize("stratum", STRATA)
def test_levels_just_below_the_stored_minimum_fail_at_the_worst_case_factor(
    model: HydraulicModel, stratum: str
) -> None:
    m = model.for_stratum(stratum)
    sharp = 0
    for tank, temp, profile, coeff in itertools.product(TANKS, TEMPS, PROFILES, COEFFS):
        minimum = _minimum(stratum, tank, temp, profile, coeff)
        if minimum is None or minimum <= 1.8 + EPS:
            continue
        assert _status(m, tank, minimum - EPS, profile, temp, coeff, 0.8) != "OK"
        sharp += 1
    assert sharp >= 30


@pytest.mark.parametrize("stratum", STRATA)
def test_a_combination_without_a_passing_level_is_stored_unresolved(stratum: str) -> None:
    """45 C with NPSH3 6 m never passes for TK-102 and TK-103: the record is unresolved."""
    for tank in ("TK-102", "TK-103"):
        assert _minimum(stratum, tank, 45.0, "reference_fittings", 6.0) is None


@pytest.mark.parametrize("stratum", STRATA)
@pytest.mark.parametrize("profile", PROFILES)
def test_the_engine_rejects_below_and_accepts_above_the_stored_minimum(
    model: HydraulicModel, stratum: str, profile: str
) -> None:
    """SG0 at the start: a level 0.01 m below the minimum is rejected, 0.1 m above is not;
    in the accepted run the screen holds at the start and for the next minutes, with the
    demand process on and the OU factor moving the flow."""
    tank, temp = "TK-102", 35.0
    minimum = _minimum(stratum, tank, temp, profile, 4.0)
    assert minimum is not None and 1.8 < minimum < 12.0
    base = dataclasses.replace(
        load_scenario("S0-F"),
        temperature_c=temp,
        fitting_profile=profile,
        atmosphere_stratum=stratum,
        duration_s=300.0,
        healthy_envelope=False,
    )
    for offset, expect_rejection in ((-EPS, True), (ABOVE, False)):
        scenario = dataclasses.replace(
            base, tank_levels_m={"TK-101": 9.0, "TK-102": minimum + offset, "TK-103": 5.0}
        )
        engine = Engine(
            model, load_lineup_table(model.topology), scenario, load_sim_config(), ListSink(),
            "EP-STRATUM",
        )  # fmt: skip
        outcome = engine.run()
        assert (outcome.rejection is not None) is expect_rejection, (stratum, profile, offset)
        if expect_rejection:
            assert outcome.rejection is not None and outcome.rejection["gate"] == "SG0"
            assert outcome.rejection["t_sim_s"] == 0.0
        else:
            sink: Any = engine.sink
            states = {
                r["payload"]["phase_validity_status"]
                for r in sink.rows["hydraulic_state"]
                if r["record_type"] == "pump_state" and r["element_id"] == "P-101A"
            }
            assert states == {"OK"}


@pytest.mark.parametrize("stratum", STRATA)
def test_the_pump_stays_inside_its_curve_over_the_factor_range(
    model: HydraulicModel, stratum: str
) -> None:
    m = model.for_stratum(stratum)
    limit = m.config["pump_max_flow_m3h"]
    worst = 0.0
    for tank, profile, f_d in itertools.product(TANKS, PROFILES, (0.8, 1.0, 1.25)):
        for level in (1.8, 4.0, 8.0, 12.0):
            c = load_boundary_law_coefficient(profile).value * f_d
            inputs = SteadyInputs(
                Lineup.of({f"XV-S{tank[3:]}", "XV-PAI", "XV-PAO"}, {"P-101A"}),
                {tank: level}, SCENARIO, 25.0, fitting_profile=profile,
                delivery=DeliveryBoundary(law_coefficient_m=c),
            )  # fmt: skip
            pump = m.solve(inputs).pump
            assert pump is not None
            worst = max(worst, pump.flow_m3h)
    assert worst < limit - 10.0  # a margin of at least 10 m3/h at f_d = 0.8, 12 m, TK-101
