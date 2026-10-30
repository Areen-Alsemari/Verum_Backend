"""Validity windows: which events are flagged and why, per episode and per custom case.

Inputs: the written episodes, and short custom scenarios run on the engine. Outputs:
pass/fail.
Key assumptions:
    * Decisions D22 and D53: an event is valid if its duration is at least a factor times the
      wave round trip of its path, 2 sum(L/a): 25 for a valve stroke, 10 for a set-point change,
      a flow collapse and a path closure. Hand values: receipt path to tank 101 = 0.36087 s (a
      10 s stroke is 27.7 round trips, a set-point change of 8 s is 22.2, a 30 s stroke is 83),
      to tank 102 = 2 (150/1078.2 + 80/1089.2) = 0.42514 s (a 10 s stroke is 23.5), to tank 103
      = 2 (150/1078.2 + 115/1089.2) = 0.48941 s (20.4); delivery path 0.67 s or more (a 30 s
      stroke is more than 44 round trips).
    * Decision D53 version 3 sets the stroke factor to 50, so a 10 s stroke of XV-R000 (27.7
      round trips to tank 101, 23.5 to tank 102) is flagged when the flow through the valve at its
      start is at least 10 percent of the design flow of the path (decision D58: 60 m3/h for
      the receipt path). Hence the flagged events in the shipped scenarios are the closing of
      XV-R000 at 600 s in S0u-D (flow 600 m3/h at the start) and, in S0u-E, the 10 s closure and
      the collapse of the flow under the cap. The 10 s opening of XV-R000 at 1200 s in S0u-D
      starts at zero flow and is not judged. The dead-leg window of D54 is tested in
      ``test_dead_leg_window.py``.
    * A branched lineup has no single column and is flagged ``rigid_column_unavailable``.
    * Every window carries a reason from a fixed list, and the dataset, the episode record
      and the engine outcome agree.
Independence: the round trips are hand arithmetic from the audited lengths and the screening
wave speeds; the flagged set follows from the criterion, not from the engine.

Source: ``docs/design_decisions.md`` D22 and D25.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from _series import Series
from verum.contracts import validate
from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.params import ParamValue
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.episode import EpisodeResult
from verum.sim.scenario import load_scenario
from verum.truth import ListSink

REASONS = {
    "duration_below_wave_criterion",
    "flow_collapse_within_wave_criterion",
    "path_closed_with_flow",
    "rigid_column_unavailable",
    "dead_leg_held_pressure_unvalidated",
}
RECEIPT_ROUND_TRIP = 2.0 * (150.0 / 1078.2 + 45.0 / 1089.2)
CLEAN = ["S0-A", "S0-B", "S0-C", "S0-F", "S0-G", "S0-A-inland"]
RECEIVE_102_ROUND_TRIP = 2.0 * (150.0 / 1078.2 + 80.0 / 1089.2)
RECEIVE_103_ROUND_TRIP = 2.0 * (150.0 / 1078.2 + 115.0 / 1089.2)


def _run(model: HydraulicModel, scenario: Any, cfg: Any = None) -> tuple[Engine, Any]:
    engine = Engine(
        model,
        load_lineup_table(model.topology),
        scenario,
        cfg or load_sim_config(),
        ListSink(),
        "EP-TEST",
    )
    return engine, engine.run()


@pytest.mark.parametrize("sid", CLEAN)
def test_no_event_is_flagged_in_the_clean_scenarios(series: dict[str, Series], sid: str) -> None:
    s = series[sid]
    assert s.windows == [] and s.episode["validity_windows"] == []
    assert s.episode["events_evaluated"] >= 0
    assert all(d["active_validity_window_ids"] == [] for d in s.diagnostics)


def test_the_clean_scenarios_pass_by_the_hand_ratios() -> None:
    assert 10.0 / RECEIPT_ROUND_TRIP == pytest.approx(27.7, abs=0.1)
    assert 8.0 / RECEIPT_ROUND_TRIP == pytest.approx(22.2, abs=0.1)
    assert 30.0 / RECEIPT_ROUND_TRIP == pytest.approx(83.1, abs=0.1)
    assert min(10.0 / RECEIPT_ROUND_TRIP, 8.0 / RECEIPT_ROUND_TRIP) > 10.0
    assert 10.0 / RECEIPT_ROUND_TRIP < 50.0  # a 10 s stroke to tank 101 fails the stroke factor
    assert 20.0 / RECEIPT_ROUND_TRIP > 50.0  # a 20 s stroke passes it


def test_the_stroke_factor_by_hand_ratios() -> None:
    assert RECEIVE_102_ROUND_TRIP == pytest.approx(0.42514, abs=1e-5)
    assert 10.0 / RECEIVE_102_ROUND_TRIP == pytest.approx(23.52, abs=0.01)
    assert 10.0 / RECEIVE_103_ROUND_TRIP == pytest.approx(20.43, abs=0.01)
    assert 10.0 / RECEIVE_102_ROUND_TRIP < 50.0 and 8.0 / RECEIVE_102_ROUND_TRIP > 10.0


def test_the_closing_stroke_of_s0ud_is_judged_at_an_opening_of_0p2_and_is_not_flagged(
    series: dict[str, Series],
) -> None:
    """Decision D58 version 2: the closing stroke at 600 s is judged when the opening has fallen
    to 0.2, 8 s into the stroke. By then the receipt flow is below 60 m3/h, so no window is
    written and the scenario returns to the analytic tier."""
    s = series["S0u-D"]
    assert s.windows == []
    assert s.episode["dataset_tier"] == "analytic_verification"
    # The opening at 1200 s starts with no receipt flow, below 10 percent of 600 m3/h (D58).
    assert all(w["t_start_s"] != 1200.0 for w in s.windows)


def test_a_closing_stroke_is_not_judged_at_its_start_flow(model: HydraulicModel) -> None:
    """The same 10 s closure from the full 600 m3/h writes no window: the flow that counts is the
    flow at an opening of 0.2, and it is below the 60 m3/h threshold there."""
    scenario = dataclasses.replace(
        load_scenario("S0-B"),
        duration_s=20.0,
        receipt_flow_m3h=600.0,
        receipt_setpoint_m3h=0.0,
        schedule=[{"t_s": 0.0, "command": "close_valves", "valves": ["XV-R000"]}],
    )
    _, outcome = _run(model, scenario)
    assert [w for w in outcome.windows if w.kind == "valve_stroke"] == []
    assert outcome.events_evaluated >= 1  # the stroke was judged, and found carrying no flow


@pytest.mark.parametrize(("flow", "judged"), [(59.0, False), (61.0, True)])
def test_a_stroke_is_judged_only_above_a_tenth_of_the_design_flow(
    model: HydraulicModel, flow: float, judged: bool
) -> None:
    """Hand: the design flow of the receipt path is 600 m3/h, so the threshold is 60 m3/h."""
    scenario = dataclasses.replace(load_scenario("S0-B"), duration_s=20.0)
    engine, _ = _run(model, scenario)
    assert engine._stroke_carries_flow("receipt", flow) is judged


def test_the_esd_closure_leaves_a_stroke_a_flow_collapse_and_a_dead_leg_window(
    episodes: dict[str, EpisodeResult], series: dict[str, Series]
) -> None:
    s = series["S0u-E"]
    assert sorted(w["kind"] for w in s.windows) == [
        "dead_leg_unvalidated", "flow_collapse", "valve_stroke",
    ]  # fmt: skip
    w = next(x for x in s.windows if x["kind"] == "flow_collapse")
    assert (w["element_id"], w["reason"]) == ("XV-R000", "flow_collapse_within_wave_criterion")
    assert w["round_trip_s"] == pytest.approx(RECEIPT_ROUND_TRIP, rel=1e-12)
    assert w["ratio"] < 10.0 and w["t_end_s"] > w["t_start_s"]
    listed = s.episode["validity_windows"]
    assert listed == [{k: x[k] for k in listed[0]} for x in s.windows]  # the episode lists them
    assert len(episodes["S0u-E"].outcome.windows) == 3
    active = [d for d in s.diagnostics if w["window_id"] in d["active_validity_window_ids"]]
    assert active and all(w["t_start_s"] <= d["t_sim_s"] <= w["t_end_s"] for d in active)


@pytest.mark.parametrize("sid", ["S0-A", "S0u-E", "S0u-D", "S0-G"])
def test_every_window_has_a_listed_reason_and_validates(
    series: dict[str, Series], sid: str
) -> None:
    for w in series[sid].windows:
        assert w["reason"] in REASONS
        validate("validity_windows", w)  # raises on a violation


def test_a_short_stroke_is_flagged_by_the_duration_criterion(model: HydraulicModel) -> None:
    """XV-R000 closing in 2 s: 2 / 0.36087 = 5.54 round trips, below 10."""
    cfg0 = load_sim_config()
    cfg = dataclasses.replace(
        cfg0,
        parameters={
            **cfg0.parameters,
            "stroke_time_xv_r000_s": ParamValue.selected(2.0, "s", "DESIGN", "TEST"),
        },
    )
    scenario = dataclasses.replace(
        load_scenario("S0-B"),
        duration_s=130.0,
        receipt_flow_m3h=600.0,
        receipt_setpoint_m3h=600.0,
        schedule=[{"t_s": 100.0, "command": "close_valves", "valves": ["XV-R000"]}],
    )
    _, outcome = _run(model, scenario, cfg)
    stroke = [w for w in outcome.windows if w.kind == "valve_stroke"]
    assert len(stroke) == 1
    assert stroke[0].reason == "duration_below_wave_criterion"
    assert stroke[0].ratio == pytest.approx(2.0 / RECEIPT_ROUND_TRIP, rel=1e-9)
    assert (stroke[0].t_start_s, stroke[0].t_end_s) == (100.0, 102.0)


def test_a_branched_lineup_is_flagged_as_unavailable(model: HydraulicModel) -> None:
    scenario = dataclasses.replace(
        load_scenario("S0-B"),
        initial_mode="RECEIVE_101_102",
        duration_s=100.0,
        schedule=[
            {"t_s": 0.0, "command": "receipt_setpoint", "value_m3h": 600.0},
            {"t_s": 60.0, "command": "lineup", "mode": "SWITCH_RECEIPT_HOLD"},
        ],
    )
    engine, outcome = _run(model, scenario)
    assert outcome.rejection is None and outcome.ledger["closed"]
    branched = [w for w in outcome.windows if w.kind == "branched_lineup"]
    assert len(branched) == 1
    w = branched[0]
    assert (w.reason, w.element_id, w.ratio, w.round_trip_s) == (
        "rigid_column_unavailable", "RECEIPT", None, None,
    )  # fmt: skip
    # The window ends when XV-R000 reaches the closed threshold: 60 s + 0.999 x 10 s.
    assert (w.t_start_s, w.t_end_s) == (0.0, pytest.approx(69.99))
    sink: Any = engine.sink
    models = {
        r["t_sim_s"]: r["flow_model"] for r in sink.rows["solver_diagnostics"] if r["side"] is None
    }
    assert models[10.0] == "quasi" and models[80.0] == "inactive"
    rows = sink.rows["validity_windows"]
    # Since D54 the path that has just closed also leaves a dead-leg window for E001, which holds
    # the pressure of the open path while its target is the tank side.
    assert [r["window_id"] for r in rows if r["kind"] == "branched_lineup"] == [w.window_id]
    # The 10 s closure at 60 s starts with 600 m3/h and is 27.7 round trips, below the 50 of D53.
    assert sorted(r["kind"] for r in rows) == [
        "branched_lineup", "dead_leg_unvalidated", "valve_stroke",
    ]  # fmt: skip


# Events judged against the wave criterion, counted by hand from the scenario files: a valve
# stroke on an active path and a change of the receipt set-point each count once.
#   S0-A, S0-F, S0-A-inland: none (steady delivery).
#   S0-B: the set-point 0 -> 600 at 0 s (1).  S0-G: the step 600 -> 300 at 1200 s (1).
#   S0-C: the set-point at 0 s (1).
#   S0u-D: set-point 600 -> 0 and the hold lineup at 600 s: XV-R000, XV-R101 strokes (3);
#          RECEIVE_102 and the set-point 0 -> 600 at 1200 s: XV-R000, XV-R102 strokes (3).
#   S0u-E: the two closures XV-R000, XV-R101 ordered by the protection request (2).
EVENTS = {
    "S0-A": 0, "S0-F": 0, "S0-A-inland": 0, "S0-B": 1, "S0-G": 1, "S0-C": 1, "S0u-D": 6, "S0u-E": 2,
}  # fmt: skip


@pytest.mark.parametrize("sid", sorted(EVENTS))
def test_the_number_of_events_judged_and_the_number_flagged(
    series: dict[str, Series], sid: str
) -> None:
    """Windows listed: S0u-E the 10 s closure, the collapse (a flow event) and the dead-leg
    window of D54; S0u-D none, because the 10 s closure of XV-R000 at 600 s is judged at an
    opening of 0.2 (D58 version 2), where the flow is already below 60 m3/h. The set-point
    collapse of S0u-D lasts 4.4 s, 12.2 round trips of 10 or more, and is valid.

    Hand ratios: 8 s set-point change 22.2 round trips, 10 s stroke 27.7, 30 s stroke 83.1
    (receipt); the collapse of S0u-E lasts 0.19 s, 0.51 round trips (a flow event, not a
    stroke event: the 10 s stroke itself is valid).
    """
    episode = series[sid].episode
    assert episode["events_evaluated"] == EVENTS[sid]
    flagged = len(episode["validity_windows"])
    assert flagged == {"S0u-E": 3}.get(sid, 0)
