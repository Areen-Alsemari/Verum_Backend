"""Protection threshold crossings are located inside the step.

The crossing times of the rising levels in the isolation scenario are exact by hand under a constant
receipt flow on the floating branch, and are compared with the event times and with an independent
linear interpolation of the written level series. A delivery run checks the alarm-clearing crossing.
The hand times and bounds are in the "Protection threshold crossings" section of the verification
notes.

See D26.
"""

from __future__ import annotations

import dataclasses
import gzip
import json

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


def test_the_trip_crossing_matches_hand_time_and_independent_interpolation(
    series: dict[str, Series],
) -> None:
    """The trip occurs 0.2 s after the true level reaches the threshold less the detector offset, at
    the hand time and at the interpolated time. Independent: yes, because the time is hand
    arithmetic and an interpolation of the written files.
    """
    s = series["S0u-E"]
    event = next(e for e in s.events if e["payload"].get("kind") == "HIGH_HIGH_TRIP")
    threshold = 13.0 - event["payload"]["detector_offset_m"]
    hand = (threshold - 12.3) * AREA / RATE
    t = event["t_sim_s"] - 0.2
    assert t == pytest.approx(hand, abs=1e-3)
    assert t != round(t)  # no 1 s quantisation
    assert t == pytest.approx(_interpolated(_grid_levels(s, "TK-101"), threshold, True), abs=1e-3)


def test_the_alarm_follows_the_level_transmitter_samples(
    episodes: dict[str, EpisodeResult], series: dict[str, Series]
) -> None:
    """The high alarm is raised by the first level sample at or above 12.5 m that has arrived,
    within the hand bounds. Independent: yes, because the bounds are hand arithmetic on the sample
    interval, delay and noise.
    """
    s = series["S0u-E"]
    alarm = next(e for e in s.events if e["payload"].get("kind") == "HIGH_ALARM")["t_sim_s"]
    crossing = (12.5 - 12.3) * AREA / RATE
    assert crossing == pytest.approx(848.2300, abs=1e-4)
    assert crossing <= alarm <= crossing + 9.4
    obs = [
        json.loads(line)
        for line in gzip.open(episodes["S0u-E"].directory / "observations.jsonl.gz", "rt")
    ]
    first = next(
        r for r in obs if r["tag_id"] == "LT-101" and r["value"] is not None and r["value"] >= 12.5
    )
    assert alarm == pytest.approx(first["t_available_s"], abs=1e-9)
    assert alarm != round(alarm)


def test_the_episode_record_lists_the_detector_crossing(
    episodes: dict[str, EpisodeResult], series: dict[str, Series]
) -> None:
    """The episode record lists the detector crossing with the time of the trip event. Independent:
    yes, because the check compares two written records.
    """
    listed = series["S0u-E"].episode["protection_crossings"]
    trip_event = next(
        e for e in series["S0u-E"].events if e["payload"].get("kind") == "HIGH_HIGH_TRIP"
    )
    offset = trip_event["payload"]["detector_offset_m"]
    assert [(c["tank"], c["threshold"]) for c in listed] == [("TK-101", "high_high")]
    assert listed[0]["level_m"] == pytest.approx(13.0 - offset, abs=1e-9)
    assert listed[0]["t_sim_s"] == pytest.approx(trip_event["t_sim_s"] - 0.2, abs=1e-9)
    assert episodes["S0u-E"].outcome.crossings == listed


@pytest.mark.slow
def test_the_alarm_clears_on_the_level_transmitter_after_the_level_falls(
    model: HydraulicModel,
) -> None:
    """On a falling level the alarm clears on the first arrived sample below the clearing level,
    within the same bound as for the rise. Independent: yes, because the bound is hand arithmetic.
    """
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
    crossing = _interpolated(levels, clear, False)
    t = cleared[0]["t_sim_s"]
    assert crossing <= t <= crossing + 9.4
    assert outcome.crossings == []  # no alarm threshold is located any more
