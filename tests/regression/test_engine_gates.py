"""Engine gates SG0 to SG3, event queue order and event landing, on short runs.

Inputs: scenario variants built from the shipped scenario files, run for a few
seconds to a few minutes. Outputs: pass/fail.
Key assumptions: a gate failure produces a rejection record naming gate, time and
parameter; nothing is silently truncated or clipped. The queue orders events by
(time, rank, sequence) with commands before valve changes.

Source: decisions D17, D20; ``VERUM_INTEGRATION_README.md`` section E.
"""

from __future__ import annotations

import dataclasses
import heapq
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.sim.config import load_sim_config
from verum.sim.engine import RANK_COMMAND, RANK_VALVE, Engine
from verum.sim.scenario import Scenario, load_scenario
from verum.truth import ListSink


def _engine(model: HydraulicModel, scenario: Scenario) -> Engine:
    return Engine(
        model,
        load_lineup_table(model.topology, model.directory),
        scenario,
        load_sim_config(),
        ListSink(),
        "EP-TEST",
    )


def test_sg3_rejects_a_healthy_scenario_that_leaves_the_level_envelope(
    model: HydraulicModel,
) -> None:
    scenario = dataclasses.replace(
        load_scenario("S0-B"), tank_levels_m={"TK-101": 11.95, "TK-102": 7.0, "TK-103": 5.0}
    )
    outcome = _engine(model, scenario).run()
    assert outcome.rejection is not None
    assert outcome.rejection["gate"] == "SG3" and outcome.rejection["parameter"] == "level[TK-101]"
    # 0.05 m x 706.86 m2 / (600/3600 m3/s) = 212 s, plus the ramp deficit of about 2 s.
    assert 210.0 < outcome.rejection["t_sim_s"] < 218.0
    assert outcome.rejection["limit"] == 12.0


def test_sg3_is_off_when_the_scenario_is_not_a_healthy_one(model: HydraulicModel) -> None:
    scenario = dataclasses.replace(
        load_scenario("S0-B"),
        tank_levels_m={"TK-101": 11.95, "TK-102": 7.0, "TK-103": 5.0},
        healthy_envelope=False,
        duration_s=300.0,
    )
    assert _engine(model, scenario).run().rejection is None


def test_sg1_rejects_a_ledger_that_stops_closing(model: HydraulicModel) -> None:
    engine = _engine(model, dataclasses.replace(load_scenario("S0-A"), duration_s=100.0))
    engine.run(until=10.0)
    engine.state.cum_received_m3 += 5.0  # an injected 5 m3 of unaccounted receipt
    outcome = engine.run()
    assert outcome.rejection is not None
    assert (
        outcome.rejection["gate"] == "SG1"
        and outcome.rejection["parameter"] == "mass_ledger_residual"
    )
    assert outcome.rejection["t_sim_s"] == 11.0
    assert outcome.rejection["value"] == pytest.approx(3750.0, rel=1e-3)


def test_sg0_rejects_when_no_level_passes_the_screen(root: Path, tmp_path: Path) -> None:
    shutil.copytree(root / "config", tmp_path / "config")
    path = tmp_path / "config" / "hydraulics.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["parameters"]["npsh3_coefficient_m"]["value"] = 6.0  # TK-102 at 45 C never passes with 6 m
    path.write_text(json.dumps(doc), encoding="utf-8")
    local = HydraulicModel.load(tmp_path / "config")
    scenario = dataclasses.replace(
        load_scenario("S0-A"), temperature_c=45.0, initial_mode="DELIVER_102_A", duration_s=60.0
    )
    outcome = _engine(local, scenario).run()
    assert (
        outcome.rejection is not None
        and outcome.rejection["gate"] == "SG0"
        and outcome.rejection["t_sim_s"] == 0.0
    )
    assert (
        outcome.rejection["parameter"]
        == "pumping_minimum_level[TK-102,45C,reference_fittings,NPSH3=6m,sea_level,f_d=0.8]"
    )
    assert "no level" in outcome.rejection["detail"] and outcome.rejection["limit"] is None


def test_sg0_pumping_minimum_boundary_at_the_stored_level(model: HydraulicModel) -> None:
    # 35 C, reference fittings, NPSH3 = 4 m: the stored minimum of TK-101 (sea level, f_d = 0.8)
    # is 3.639 m. At 3.68 m the level stays above it for the 60 s run (it falls about 0.007 m);
    # at 3.60 m it is below at the start.
    scenario = dataclasses.replace(
        load_scenario("S0-A"),
        temperature_c=35.0,
        tank_levels_m={"TK-101": 3.68, "TK-102": 7.0, "TK-103": 5.0},
        healthy_envelope=False,
        duration_s=60.0,
    )
    assert _engine(model, scenario).run().rejection is None
    below = dataclasses.replace(
        scenario, tank_levels_m={"TK-101": 3.60, "TK-102": 7.0, "TK-103": 5.0}
    )
    outcome = _engine(model, below).run()
    assert (
        outcome.rejection is not None
        and outcome.rejection["t_sim_s"] == 0.0
        and outcome.rejection["gate"] == "SG0"
    )


def test_rejection_stops_the_run_at_the_failing_step(model: HydraulicModel) -> None:
    outcome = _engine(model, load_scenario("REJ-2")).run()
    assert outcome.rejection is not None
    assert outcome.final_t <= outcome.rejection["t_sim_s"] + 1.0
    assert outcome.final_t < 3600.0


def test_the_queue_orders_by_time_then_rank_then_sequence(model: HydraulicModel) -> None:
    engine = _engine(model, load_scenario("S0-A"))
    state = engine.state
    state.queue.clear()
    engine._push(state, 5.0, RANK_VALVE, "valve_end", "a")  # noqa: SLF001
    engine._push(state, 5.0, RANK_COMMAND, "command", "c1")  # noqa: SLF001
    engine._push(state, 3.0, RANK_VALVE, "threshold", "b")  # noqa: SLF001
    engine._push(state, 5.0, RANK_COMMAND, "command", "c2")  # noqa: SLF001
    order = [heapq.heappop(state.queue)[3:] for _ in range(4)]
    assert order == [("threshold", "b"), ("command", "c1"), ("command", "c2"), ("valve_end", "a")]


def test_steps_end_exactly_on_event_times(model: HydraulicModel) -> None:
    scenario = dataclasses.replace(load_scenario("S0u-D"), duration_s=640.0)
    engine = _engine(model, scenario)
    sink: Any = engine.sink
    engine.run()
    times = {r["t_sim_s"] for r in sink.rows["events"]}
    state_times = {r["t_sim_s"] for r in sink.rows["hydraulic_state"] if r["side"] == "pre_event"}
    assert {600.0, 609.99, 610.0, 629.97, 630.0} <= times
    assert times <= state_times  # every event instant has a pre-event and a post-event row


def test_a_pump_cannot_be_stopped_by_a_lineup_command(model: HydraulicModel) -> None:
    scenario = dataclasses.replace(
        load_scenario("S0-A"),
        schedule=[{"t_s": 10.0, "command": "lineup", "mode": "CHANGEOVER_HOLD"}],
        duration_s=60.0,
    )
    with pytest.raises(ValueError, match="pump"):
        _engine(model, scenario).run()


def test_a_direct_receipt_switch_is_refused_by_the_lineup_controller(model: HydraulicModel) -> None:
    from verum.lineups import TransitionRejected

    scenario = dataclasses.replace(
        load_scenario("S0u-D"),
        schedule=[{"t_s": 10.0, "command": "lineup", "mode": "RECEIVE_102"}],
        duration_s=60.0,
    )
    with pytest.raises(TransitionRejected):
        _engine(model, scenario).run()
