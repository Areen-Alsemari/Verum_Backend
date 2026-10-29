"""Protection threshold crossings are located inside the step (decision D26).

Inputs: the S0u-E episode (rising crossings at 12.5 m and 13 m) and a delivery run that
lowers a tank through the alarm-clearing level. Outputs: pass/fail.
Key assumptions:
    * Under a constant receipt flow on the floating branch the level rises linearly, so the
      crossing time is exact by hand: t = (threshold - 12.3 m) x 706.858347 m2 / (1/6 m3/s).
      Hence 848.2300 s for 12.5 m and 2968.8051 s for 13 m.
    * The independent interpolation reads the written level series at the integer seconds on
      both sides of the event and interpolates linearly; its error is below 1 microsecond for
      these smooth series (second derivative of the level about 2e-10 m/s2 for the delivery).
    * An event time is not a multiple of the 1 s grid (no quantisation) and the error is
      below 1 ms.
Independence: hand arithmetic and a linear interpolation of the written files; neither uses
the engine's root finding.

Source: ``docs/design_decisions.md`` D26.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from _series import Series
from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.protection import load_protection_config
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.episode import EpisodeResult
from verum.sim.scenario import load_scenario
from verum.truth import ListSink

AREA = 706.858347
RATE = 600.0 / 3600.0  # m3/s


def _interpolated(levels: dict[float, float], threshold: float, rising: bool) -> float:
    times = sorted(levels)
    for a, b in zip(times, times[1:], strict=False):
        la, lb = levels[a], levels[b]
        if (la < threshold <= lb) if rising else (la >= threshold > lb):
            return a + (threshold - la) / (lb - la) * (b - a)
    raise AssertionError("no crossing in the series")


def _grid_levels(s: Series, tank: str) -> dict[float, float]:
    return {t: lv for t, side, lv, _v, _f in s.tank[tank] if side is None}


@pytest.mark.parametrize(("kind", "threshold"), [("HIGH_ALARM", 12.5), ("HIGH_HIGH_TRIP", 13.0)])
def test_rising_crossings_match_hand_time_and_independent_interpolation(
    series: dict[str, Series], kind: str, threshold: float
) -> None:
    s = series["S0u-E"]
    event = next(e for e in s.events if e["payload"].get("kind") == kind)
    hand = (threshold - 12.3) * AREA / RATE
    t = event["t_sim_s"]
    assert t == pytest.approx(hand, abs=1e-3)
    assert t != round(t)  # no 1 s quantisation
    assert t == pytest.approx(_interpolated(_grid_levels(s, "TK-101"), threshold, True), abs=1e-3)
    level = next(r for r in s.tank["TK-101"] if r[0] == t and r[1] == "post_event")[2]
    assert level == pytest.approx(threshold, abs=1e-6)


def test_the_episode_record_lists_the_located_crossings(
    episodes: dict[str, EpisodeResult], series: dict[str, Series]
) -> None:
    listed = series["S0u-E"].episode["protection_crossings"]
    assert [(c["tank"], c["threshold"], c["level_m"]) for c in listed] == [
        ("TK-101", "high_alarm", 12.5),
        ("TK-101", "high_high", 13.0),
    ]
    events = {
        e["payload"]["kind"]: e["t_sim_s"]
        for e in series["S0u-E"].events
        if e["payload"].get("kind") in ("HIGH_ALARM", "HIGH_HIGH_TRIP")
    }
    assert [c["t_sim_s"] for c in listed] == [events["HIGH_ALARM"], events["HIGH_HIGH_TRIP"]]
    assert episodes["S0u-E"].outcome.crossings == listed


@pytest.mark.slow
def test_a_falling_crossing_clears_the_alarm_on_the_located_time(model: HydraulicModel) -> None:
    """Delivery from 12.6 m: the alarm clears when the level falls through 12.5 m minus the
    hysteresis; the located time agrees with the interpolation of the written levels."""
    config = load_protection_config(model.topology, "TK-101", model.directory)
    clear = config.alarm_clear_m
    assert 12.0 < clear < 12.5
    scenario = dataclasses.replace(
        load_scenario("S0-A"),
        duration_s=3000.0,
        healthy_envelope=False,
        tank_levels_m={"TK-101": 12.6, "TK-102": 7.0, "TK-103": 5.0},
    )
    sink = ListSink()
    engine = Engine(
        model, load_lineup_table(model.topology), scenario, load_sim_config(), sink, "EP-FALL"
    )
    outcome = engine.run()
    assert outcome.rejection is None
    cleared = [r for r in sink.rows["events"] if r["payload"].get("kind") == "ALARM_CLEARED"]
    assert len(cleared) == 1
    levels: dict[float, float] = {
        r["t_sim_s"]: r["payload"]["level_m"]
        for r in sink.rows["hydraulic_state"]
        if r["record_type"] == "tank_state" and r["element_id"] == "TK-101" and r["side"] is None
    }
    t = cleared[0]["t_sim_s"]
    assert t == pytest.approx(_interpolated(levels, clear, False), abs=1e-3)
    assert t != round(t)
    assert outcome.crossings[0]["threshold"] == "alarm_clear"
    inside: Any = [r for r in sink.rows["hydraulic_state"] if r["t_sim_s"] == t and r["side"]]
    assert inside  # the event instant has its pre-event and post-event rows
