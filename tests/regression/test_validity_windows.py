"""Validity windows: which events are flagged and why, per episode and per custom case.

Inputs: the written episodes, and short custom scenarios run on the engine. Outputs:
pass/fail.
Key assumptions:
    * Decision D22: an event is valid if its duration is at least 10 wave round trips of
      its path, 2 sum(L/a). Hand values: receipt path to a tank 101 = 0.36087 s (valve
      stroke of 10 s is 27.7 round trips, a set-point change of 8 s is 22.2, a 30 s stroke
      is 83), delivery path 0.67 s or more (a 30 s stroke is more than 44 round trips).
    * Hence the only flagged event in the shipped scenarios is the collapse of the flow when
      XV-R000 closes under the cap (S0u-E): the stroke lasts long enough, the flow does not.
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
}
RECEIPT_ROUND_TRIP = 2.0 * (150.0 / 1078.2 + 45.0 / 1089.2)
CLEAN = ["S0-A", "S0-B", "S0-C", "S0u-D", "S0-F", "S0-G", "S0-A-elev"]


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


def test_the_esd_closure_leaves_exactly_one_flagged_window(
    episodes: dict[str, EpisodeResult], series: dict[str, Series]
) -> None:
    s = series["S0u-E"]
    assert [w["kind"] for w in s.windows] == ["flow_collapse"]
    w = s.windows[0]
    assert (w["element_id"], w["reason"]) == ("XV-R000", "flow_collapse_within_wave_criterion")
    assert w["round_trip_s"] == pytest.approx(RECEIPT_ROUND_TRIP, rel=1e-12)
    assert w["ratio"] < 10.0 and w["t_end_s"] > w["t_start_s"]
    listed = s.episode["validity_windows"]
    assert listed == [{k: w[k] for k in listed[0]}]  # the episode record lists the same window
    assert len(episodes["S0u-E"].outcome.windows) == 1
    active = [d for d in s.diagnostics if d["active_validity_window_ids"]]
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
    assert [r["window_id"] for r in rows] == [w.window_id]
