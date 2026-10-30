"""Restriction modes in the episode record, misrouting (b) eligibility and latent faults.

Inputs: fault specifications, the lineup states of a scenario and short episodes. Outputs:
pass/fail.
Key assumptions (decisions D75 and D76):
    * Misrouting (b), a valve stuck nearly closed, is eligible only on a parallel branch of the
      lineup in force at the onset: RECEIVE_101_102 opens XV-R101 and XV-R102 in parallel, so
      either is eligible; in RECEIVE_101 or DELIVER_101_A every open valve carries the whole flow,
      so none is. Misrouting (a) is as before.
    * A fault is latent if it cannot change a tag in any lineup state from its onset: the head
      fault of a stopped pump, a restriction on a closed valve, an obstruction on an open valve
      without flow, a forced opening of a valve that is already open. The label comes from the
      lineup table by hand reading (``config/lineups.json``), not from a run.
    * A latent fault changes no emitted number: the observation rows of the faulted episode equal
      those of the healthy episode of the same seed, byte for byte.
Independence: the expected labels are read from the lineup table by hand; the zero-effect test
compares two runs and does not use the labelling code.

Source: ``docs/design_decisions.md`` D74, D75, D76; ``docs/fault_models.md``.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from verum.contracts import validate
from verum.faults import FaultSet, FaultSpec, activity, check, lineup_states, violations
from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.sim.episode import run_episode
from verum.sim.scenario import load_scenario

MODES = load_lineup_table(HydraulicModel.load().topology).modes
EDGES = {"E-PA3"}
TAGS = {"PT-203"}


def states(mode: str, setpoint: float = 0.0, schedule: Any = (), onset: float = 900.0) -> Any:
    return lineup_states(mode, setpoint, schedule, MODES, onset)


def stuck(valve: str, onset: float = 900.0) -> FaultSpec:
    return FaultSpec("VALVE_MISROUTING", "open_but_stuck", valve, onset, 300.0, 0.01)


def restriction(valve: str, mode: str) -> FaultSpec:
    return FaultSpec("VALVE_RESTRICTION", "restriction", valve, 900.0, 300.0, 0.5, fault_mode=mode)


# --- D75 ----------
@pytest.mark.parametrize("valve", ["XV-R101", "XV-R102"])
def test_misrouting_b_is_eligible_on_either_valve_of_a_parallel_receipt(valve: str) -> None:
    assert violations([stuck(valve)], EDGES, TAGS, 3600.0, states("RECEIVE_101_102", 600.0)) == []


@pytest.mark.parametrize(
    ("valve", "mode"),
    [("XV-R101", "RECEIVE_101"), ("XV-S101", "DELIVER_101_A"), ("XV-PAO", "DELIVER_101_A"),
     ("XV-R103", "RECEIVE_101_102")],
)  # fmt: skip
def test_misrouting_b_is_refused_on_a_serial_valve(valve: str, mode: str) -> None:
    problems = violations([stuck(valve)], EDGES, TAGS, 3600.0, states(mode))
    assert any("not on a parallel branch" in p for p in problems), problems
    with pytest.raises(Exception, match="parallel branch"):
        check([stuck(valve)], EDGES, TAGS, 3600.0, states(mode))


def test_misrouting_b_without_a_lineup_is_refused_not_assumed() -> None:
    problems = violations([stuck("XV-R101")], EDGES, TAGS, 3600.0)
    assert any("needs the lineup" in p for p in problems)


def test_misrouting_a_is_unchanged_by_the_branch_rule() -> None:
    a = FaultSpec("VALVE_MISROUTING", "closed_but_open", "XV-S102", 900.0, 300.0, 1.0)
    assert violations([a], EDGES, TAGS, 3600.0, states("DELIVER_101_A")) == []
    assert violations([a], EDGES, TAGS, 3600.0) == []


def test_the_states_from_the_onset_follow_the_timed_commands() -> None:
    """S0u-D (hand): hold with set-point 0 from 600 s, RECEIVE_102 with 600 m3/h from 1200 s."""
    sc = load_scenario("S0u-D")
    after = lineup_states(sc.initial_mode, sc.receipt_setpoint_m3h, sc.schedule, MODES, 700.0)
    assert [(sorted(s.open_valves), s.receipt_setpoint_m3h) for s in after][0][1] == 0.0
    assert after[-1].receipt_setpoint_m3h == 600.0 and "XV-R102" in after[-1].open_valves
    assert len(after) >= 2
    before = lineup_states(sc.initial_mode, sc.receipt_setpoint_m3h, sc.schedule, MODES, 100.0)
    assert before[0].receipt_setpoint_m3h == 600.0 and "XV-R101" in before[0].open_valves


# --- D76 ----------
@pytest.mark.parametrize(
    ("spec", "mode", "setpoint", "label"),
    [
        (FaultSpec("PUMP_HEAD_DEGRADATION", "head_scale", "P-101B", 900.0, 300.0, 0.8),
         "DELIVER_101_A", 0.0, "latent"),
        (FaultSpec("PUMP_HEAD_DEGRADATION", "head_scale", "P-101A", 900.0, 300.0, 0.8),
         "DELIVER_101_A", 0.0, "active"),
        (restriction("XV-R101", "obstruction"), "DELIVER_101_A", 0.0, "latent"),  # valve closed
        (restriction("XV-R101", "position_visible"), "DELIVER_101_A", 0.0, "latent"),
        (restriction("XV-S101", "obstruction"), "DELIVER_101_A", 0.0, "active"),
        (restriction("XV-R101", "obstruction"), "RECEIVE_101", 0.0, "latent"),  # no flow
        (restriction("XV-R101", "obstruction"), "RECEIVE_101", 600.0, "active"),
        (restriction("XV-R101", "position_visible"), "RECEIVE_101", 0.0, "active"),  # contact
        (FaultSpec("VALVE_MISROUTING", "closed_but_open", "XV-S102", 900.0, 300.0, 1.0),
         "DELIVER_101_A", 0.0, "active"),
        (FaultSpec("VALVE_MISROUTING", "closed_but_open", "XV-S101", 900.0, 300.0, 1.0),
         "DELIVER_101_A", 0.0, "latent"),  # already open
        (FaultSpec("SENSOR_DRIFT", "bias", "PT-203", 900.0, None, 0.01), "IDLE", 0.0, "active"),
        (FaultSpec("PIPE_LEAK", "orifice", "E-PA3", 900.0, 300.0, 1e-4, 0.5, 0.62),
         "DELIVER_101_A", 0.0, "active"),
    ],
)  # fmt: skip
def test_the_activity_label_follows_the_lineup(
    spec: FaultSpec, mode: str, setpoint: float, label: str
) -> None:
    assert activity(spec, states(mode, setpoint)) == label


def test_a_fault_that_becomes_active_later_in_the_episode_is_active() -> None:
    b = FaultSpec("PUMP_HEAD_DEGRADATION", "head_scale", "P-101B", 900.0, 300.0, 0.8)
    schedule = [{"t_s": 1500.0, "command": "lineup", "mode": "CHANGEOVER_HOLD"}]
    assert activity(b, states("DELIVER_101_A", 0.0, schedule)) == "latent"
    schedule = [{"t_s": 1500.0, "command": "lineup", "mode": "DELIVER_101_B"}]
    assert activity(b, states("DELIVER_101_A", 0.0, schedule)) == "active"
    # After the changeover at 1500 s pump B runs at the onset (active) and pump A is stopped.
    assert activity(b, states("DELIVER_101_A", 0.0, schedule, onset=1600.0)) == "active"
    a = dataclasses.replace(b, asset_id="P-101A")
    assert activity(a, states("DELIVER_101_A", 0.0, schedule, onset=1600.0)) == "latent"


@pytest.mark.slow
def test_a_latent_fault_on_a_stopped_pump_has_no_telemetry_effect(
    model: HydraulicModel, tmp_path: Path
) -> None:
    scenario = dataclasses.replace(load_scenario("S0-A"), duration_s=3000.0)
    spec = FaultSpec("PUMP_HEAD_DEGRADATION", "head_scale", "P-101B", 900.0, 300.0, 0.7)
    healthy = run_episode("S0-A", tmp_path / "healthy", model, scenario)
    faulted = run_episode("S0-A", tmp_path / "faulted", model, scenario, FaultSet((spec,)))
    assert not faulted.rejected
    record = json.loads((faulted.directory / "episode.json").read_text())
    validate("episode", record)
    assert record["fault_activity"] == ["latent"] and record["fault_modes"] == [None]
    assert (
        faulted.file_hashes["observations.jsonl.gz"] == healthy.file_hashes["observations.jsonl.gz"]
    )
    assert (
        faulted.file_hashes["hydraulic_state.jsonl.gz"]
        == healthy.file_hashes["hydraulic_state.jsonl.gz"]
    )
    assert "fault_activity" not in json.loads((healthy.directory / "episode.json").read_text())


@pytest.mark.slow
def test_an_active_restriction_records_its_mode_and_activity(
    model: HydraulicModel, tmp_path: Path
) -> None:
    scenario = dataclasses.replace(load_scenario("S0-A"), duration_s=3000.0)
    result = run_episode(
        "S0-A", tmp_path, model, scenario, FaultSet((restriction("XV-S101", "obstruction"),))
    )
    assert not result.rejected
    record = json.loads((result.directory / "episode.json").read_text())
    assert record["fault_modes"] == ["obstruction"] and record["fault_activity"] == ["active"]
    truth = [
        json.loads(line)
        for line in __import__("gzip").open(result.directory / "fault_truth.jsonl.gz", "rt")
    ]
    assert truth[0]["mechanism"] == "restriction_obstruction"
