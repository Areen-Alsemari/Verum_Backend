"""Pumping-minimum files per (atmosphere, volatility) pair against the screen and the engine.

Inputs: the six files ``config/pumping_minimum_levels_<atmosphere>_<volatility>_fd0p8.json``
(atmosphere coastal or inland, volatility RVP_9_0, RVP_9_5 or RVP10),
the steady solver at the atmosphere and volatility of each pair, and short engine runs.
Outputs: pass/fail.
Key assumptions:
    * Decisions D24 version 2, D46 version 3 and D51: the files are computed at the worst-case
      downstream factor f_d = 0.8, for both fitting profiles, four temperatures and the NPSH3
      sweep. A level at or above the stored minimum passes the screen at every f_d in
      [0.8, 1.25]; a level just below it fails at f_d = 0.8; a cell that never passes is stored
      unresolved.
    * 60 states are sampled per file (deterministically, with a fixed stride over the cells).
    * Pass/fail is monotonic in level: once a level passes, every higher level passes.
    * The engine's SG0 compares the level with the stored minimum at every step and checks the
      screen with the solved flow; it must never accept a state that the screen rejects.
Independence: not independent in the hydraulics. The screen is the steady solver (the same
formulas as the study that wrote the files); the test checks that the stored files, the solver
and the engine agree and that the minimum is sharp and monotonic.

Source: ``docs/design_decisions.md`` D7, D24, D46, D51, D52.
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
from verum.hydraulics.pumping_minimum import stratum_filename
from verum.lineups import load_lineup_table
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.scenario import load_scenario
from verum.truth import ListSink

TANKS = ("TK-101", "TK-102", "TK-103")
PROFILES = ("pipe_only", "reference_fittings")
TEMPS = (25.0, 35.0, 40.0, 45.0)
COEFFS = (2.5, 4.0, 6.0)
ATMOSPHERES = ("coastal", "inland")
VOLATILITIES = ("RVP_9_0", "RVP_9_5", "RVP10")
PAIRS = list(itertools.product(ATMOSPHERES, VOLATILITIES))
CELLS = list(itertools.product(TANKS, TEMPS, PROFILES, COEFFS))
EPS = 0.01  # m, distance below the stored minimum
SAMPLE = CELLS[:: len(CELLS) // 60][:60]  # 60 cells, fixed stride over the 72


def _status(model: HydraulicModel, vol: str, tank: str, level: float, profile: str, temp: float,
            coeff: float, f_d: float) -> str:  # fmt: skip
    c = load_boundary_law_coefficient(profile).value * f_d
    inputs = SteadyInputs(
        Lineup.of({f"XV-S{tank[3:]}", "XV-PAI", "XV-PAO"}, {"P-101A"}),
        {tank: level},
        vol,
        temp,
        fitting_profile=profile,
        delivery=DeliveryBoundary(law_coefficient_m=c),
        npsh3_coefficient_m=coeff,
    )
    return model.solve(inputs).phase.status


def _minimum(
    atm: str, vol: str, tank: str, temp: float, profile: str, coeff: float
) -> float | None:
    record = pumping_minimum_level(tank, temp, profile, coeff, None, stratum_filename(atm, vol))
    return record.value if record.status != "unresolved" else None


@pytest.mark.parametrize(("atm", "vol"), PAIRS)
def test_sampled_states_at_or_above_the_minimum_pass_at_every_factor_and_below_fail(
    model: HydraulicModel, atm: str, vol: str
) -> None:
    m = model.for_stratum(atm)
    assert len(SAMPLE) == 60
    passed = failed = 0
    for tank, temp, profile, coeff in SAMPLE:
        minimum = _minimum(atm, vol, tank, temp, profile, coeff)
        if minimum is None:  # never passes: the top of the normal range fails
            assert _status(m, vol, tank, 12.0, profile, temp, coeff, 0.8) != "OK"
            failed += 1
            continue
        level = max(minimum + EPS, 1.8)
        if level <= 12.0:
            for f_d in (0.8, 1.0, 1.25):
                assert _status(m, vol, tank, level, profile, temp, coeff, f_d) == "OK", (
                    atm, vol, tank, temp, profile, coeff, f_d,
                )  # fmt: skip
            passed += 1
        if minimum > 1.8 + EPS:
            assert _status(m, vol, tank, minimum - EPS, profile, temp, coeff, 0.8) != "OK"
            failed += 1
    assert passed >= 20 and failed >= 5


@pytest.mark.parametrize(("atm", "vol"), PAIRS)
def test_pass_is_monotonic_in_level(model: HydraulicModel, atm: str, vol: str) -> None:
    m = model.for_stratum(atm)
    levels = [1.8 + 0.5 * k for k in range(21)]
    for tank, temp, profile, coeff in SAMPLE[::3]:
        flags = [_status(m, vol, tank, lv, profile, temp, coeff, 0.8) == "OK" for lv in levels]
        assert flags == sorted(flags), (atm, vol, tank, temp, profile, coeff)  # F...F T...T


@pytest.mark.parametrize(("atm", "vol"), PAIRS)
def test_every_file_is_complete_and_marks_never_as_unresolved(atm: str, vol: str) -> None:
    for tank, temp, profile, coeff in CELLS:
        record = pumping_minimum_level(tank, temp, profile, coeff, None, stratum_filename(atm, vol))
        assert (record.status == "unresolved") == (not record.is_resolved)
        if record.is_resolved:
            assert 1.8 <= record.value <= 12.0


def _rank(value: float | None) -> float:
    return float("inf") if value is None else value  # "never" counts as infinity


def test_volatility_and_temperature_raise_the_minimum_level() -> None:
    """Hand argument: a higher vapor pressure lowers NPSHa, so the minimum never decreases with
    temperature or with the volatility class (RVP 9.0 <= 9.5 <= 10)."""
    for atm in ATMOSPHERES:
        for tank, profile, coeff in itertools.product(TANKS, PROFILES, COEFFS):
            series = [
                [_rank(_minimum(atm, vol, tank, t, profile, coeff)) for t in TEMPS]
                for vol in VOLATILITIES
            ]
            for row in series:  # rises with temperature
                assert row == sorted(row)
            for k in range(len(TEMPS)):
                col = [row[k] for row in series]
                assert col == sorted(col)


@pytest.mark.parametrize("atm", ATMOSPHERES)
@pytest.mark.parametrize("profile", PROFILES)
def test_the_engine_rejects_below_and_accepts_above_the_stored_minimum(
    model: HydraulicModel, atm: str, profile: str
) -> None:
    """SG0 at the start with the baseline class: a level 0.01 m below the minimum is rejected,
    0.1 m above is not; in the accepted run the screen holds for the next minutes with the
    demand process on."""
    tank, temp, vol = "TK-102", 40.0, "RVP_9_0"
    minimum = _minimum(atm, vol, tank, temp, profile, 4.0)
    assert minimum is not None and 1.8 < minimum < 12.0
    base = dataclasses.replace(
        load_scenario("S0-F"),
        temperature_c=temp,
        fitting_profile=profile,
        atmosphere_stratum=atm,
        volatility_class=vol,
        duration_s=300.0,
        healthy_envelope=False,
    )
    for offset, expect_rejection in ((-EPS, True), (0.1, False)):
        scenario = dataclasses.replace(
            base, tank_levels_m={"TK-101": 9.0, "TK-102": minimum + offset, "TK-103": 5.0}
        )
        engine = Engine(
            model, load_lineup_table(model.topology), scenario, load_sim_config(), ListSink(), "EP"
        )
        outcome = engine.run()
        assert (outcome.rejection is not None) is expect_rejection, (atm, profile, offset)
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


@pytest.mark.parametrize("atm", ATMOSPHERES)
def test_the_pump_stays_inside_its_curve_over_the_factor_range(
    model: HydraulicModel, atm: str
) -> None:
    m = model.for_stratum(atm)
    limit = m.config["pump_max_flow_m3h"]
    worst = 0.0
    for tank, profile, f_d in itertools.product(TANKS, PROFILES, (0.8, 1.0, 1.25)):
        for level in (1.8, 4.0, 8.0, 12.0):
            c = load_boundary_law_coefficient(profile).value * f_d
            inputs = SteadyInputs(
                Lineup.of({f"XV-S{tank[3:]}", "XV-PAI", "XV-PAO"}, {"P-101A"}),
                {tank: level}, "RVP_9_0", 25.0, fitting_profile=profile,
                delivery=DeliveryBoundary(law_coefficient_m=c),
            )  # fmt: skip
            pump = m.solve(inputs).pump
            assert pump is not None
            worst = max(worst, pump.flow_m3h)
    assert worst < limit - 10.0
