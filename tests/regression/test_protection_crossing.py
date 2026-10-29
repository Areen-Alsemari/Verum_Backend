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
    """The trip is decided on the detector: it asserts when the true level is the trip level
    minus the detector offset and the trip follows 0.2 s later (decision D33)."""
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
    """Decision D40: HIGH_ALARM is raised by the first level sample at or above 12.5 m that has
    arrived. Hand bounds: not before the true level reaches 12.5 m at 848.2300 s; at most one
    sample interval (5 s) + comms 0.2 s + the lag delay (1 s x the level is 0.24 mm behind: 1 s)
    + noise of three sigma (0.75 mm = 3.2 s) later, i.e. before 857.6 s. The alarm is
    the t_available of the first LT-101 observation at or above 12.5 m (same draws)."""
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
    """Delivery from 12.6 m: the level falls through 12.5 m minus the hysteresis; the alarm
    clears on the first arrived sample below that level, between the true crossing and the
    crossing + 5 s + 0.2 s + 1 s lag + 3.2 s noise (the same bound as for the rise)."""
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
