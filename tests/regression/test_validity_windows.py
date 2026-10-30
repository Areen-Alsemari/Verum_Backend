"""Validity windows: which events are flagged and why, per episode and per custom case.

An event is valid if its duration is at least a factor times the wave round trip of its path, and
the flagged set follows from this criterion and not from the engine. A stroke is judged only when
the flow through the valve is at least a tenth of the design flow of its path, and a branched lineup
is flagged because it has no single column. The round trips and ratios are derived by hand in the
"Validity windows" section of the verification notes.

See D22, D25, D53, D54 and D58.
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
    """No event is flagged in the clean scenarios, and their episode records list no window.
    Independent: yes, because the flagged set follows from the criterion.
    """
    s = series[sid]
    assert s.windows == [] and s.episode["validity_windows"] == []
    assert s.episode["events_evaluated"] >= 0
    assert all(d["active_validity_window_ids"] == [] for d in s.diagnostics)


def test_the_clean_scenarios_pass_by_the_hand_ratios() -> None:
    """The 10 s stroke, the 8 s set-point change and the 30 s stroke are 27.7, 22.2 and 83.1 round
    trips of the receipt path. Independent: yes, because the ratios are hand arithmetic.
    """
    assert 10.0 / RECEIPT_ROUND_TRIP == pytest.approx(27.7, abs=0.1)
    assert 8.0 / RECEIPT_ROUND_TRIP == pytest.approx(22.2, abs=0.1)
    assert 30.0 / RECEIPT_ROUND_TRIP == pytest.approx(83.1, abs=0.1)
    assert min(10.0 / RECEIPT_ROUND_TRIP, 8.0 / RECEIPT_ROUND_TRIP) > 10.0
    assert 10.0 / RECEIPT_ROUND_TRIP < 50.0  # a 10 s stroke to tank 101 fails the stroke factor
    assert 20.0 / RECEIPT_ROUND_TRIP > 50.0  # a 20 s stroke passes it


def test_the_stroke_factor_by_hand_ratios() -> None:
    """The round trips to tanks TK-102 and TK-103 are 0.42514 s and 0.48941 s, and a 10 s stroke is
    23.5 and 20.4 of them. Independent: yes, because the values are hand arithmetic.
    """
    assert RECEIVE_102_ROUND_TRIP == pytest.approx(0.42514, abs=1e-5)
    assert 10.0 / RECEIVE_102_ROUND_TRIP == pytest.approx(23.52, abs=0.01)
    assert 10.0 / RECEIVE_103_ROUND_TRIP == pytest.approx(20.43, abs=0.01)
    assert 10.0 / RECEIVE_102_ROUND_TRIP < 50.0 and 8.0 / RECEIVE_102_ROUND_TRIP > 10.0


def test_the_closing_stroke_of_s0ud_is_judged_at_an_opening_of_0p2_and_is_not_flagged(
    series: dict[str, Series],
) -> None:
    """The closing stroke of the lineup-change scenario is judged at an opening of 0.2, where the
    receipt flow is below 60 m3/h, so no window is written and the tier is analytic verification.
    Independent: yes, because the rule is the stated judging point.
    """
    s = series["S0u-D"]
    assert s.windows == []
    assert s.episode["dataset_tier"] == "analytic_verification"
    # The opening at 1200 s starts with no receipt flow, below 10 percent of 600 m3/h (D58).
    assert all(w["t_start_s"] != 1200.0 for w in s.windows)


def test_a_closing_stroke_is_not_judged_at_its_start_flow(model: HydraulicModel) -> None:
    """A 10 s closure from the full 600 m3/h writes no window, because the flow that counts is the
    flow at an opening of 0.2. Independent: yes, because the expected outcome is the judging rule.
    """
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
    """A stroke is judged only if the flow is at least 60 m3/h, a tenth of the 600 m3/h design flow
    of the receipt path. Independent: yes, because the threshold is hand arithmetic.
    """
    scenario = dataclasses.replace(load_scenario("S0-B"), duration_s=20.0)
    engine, _ = _run(model, scenario)
    assert engine._stroke_carries_flow("receipt", flow) is judged


def test_the_esd_closure_leaves_a_stroke_a_flow_collapse_and_a_dead_leg_window(
    episodes: dict[str, EpisodeResult], series: dict[str, Series]
) -> None:
    """The emergency isolation writes a valve-stroke window, a flow-collapse window and a dead-leg
    window. Independent: yes, because the expected kinds follow from the criterion.
    """
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
    """Every window has a reason from the fixed list and validates against its schema. Independent:
    yes, because the list and the schema are separate.
    """
    for w in series[sid].windows:
        assert w["reason"] in REASONS
        validate("validity_windows", w)  # raises on a violation


def test_a_short_stroke_is_flagged_by_the_duration_criterion(model: HydraulicModel) -> None:
    """A 2 s closure of the common receipt valve is 5.54 round trips and is flagged. Independent:
    yes, because the ratio is hand arithmetic.
    """
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
    """A lineup with two receipt branches open is flagged as having no rigid column. Independent:
    yes, because the expected outcome is the stated rule.
    """
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
    """The numbers of events judged and flagged per scenario equal the expected counts, and the
    dataset, the record and the outcome agree. Independent: yes, because the counts follow from the
    hand ratios.
    """
    episode = series[sid].episode
    assert episode["events_evaluated"] == EVENTS[sid]
    flagged = len(episode["validity_windows"])
    assert flagged == {"S0u-E": 3}.get(sid, 0)
