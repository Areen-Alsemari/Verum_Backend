"""Buoyancy, liquid displacement and hydraulic response of a supported roof during withdrawal.

The reference calculations follow volume conservation and Archimedes' force balance. Structural
rupture and field failure probabilities are deliberately not supplied by these tests.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from verum.contracts import ContractError
from verum.hydraulics import HydraulicModel
from verum.inspection.truth import Truth
from verum.lineups import load_lineup_table
from verum.params import ParamValue, UnresolvedParameter
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.episode import run_episode
from verum.sim.scenario import load_scenario
from verum.tanks import load_tank_geometry
from verum.tanks.hangup import RoofHangup
from verum.training import load_episode_truth
from verum.truth import ListSink, read_rows


def test_volume_and_support_load_follow_independent_force_and_volume_balances() -> None:
    """Half immersion transfers half the weight to the support and preserves calibration.

    Independent: yes, because the expected force and volume are direct geometric balances.
    """
    base = load_tank_geometry()
    roof = RoofHangup(base, 9., 750., 9.80665)
    draft = 20. / 750.
    level = 9. - draft / 2
    expected_volume = base.area_m2 * level - base.deck_area_m2 * draft / 2
    assert roof.calibration.volume_m3(level, 750.) == pytest.approx(expected_volume)
    assert roof.calibration.level_m(expected_volume, 750.) == pytest.approx(level)
    assert roof.support_reaction_n(level) == pytest.approx(roof.weight_n / 2, rel=1e-10)
    assert roof.support_reaction_n(9. - 2 * draft) == pytest.approx(roof.weight_n)
    assert roof.calibration.volume_m3(9., 750.) == pytest.approx(base.volume_m3(9., 750.))
    with pytest.raises(UnresolvedParameter):
        roof.capacity_margin_n(level, ParamValue.unresolved("N", "support strength not supplied"))
    with pytest.raises(ValueError):
        roof.support_reaction_n(9.1)


def run(model: HydraulicModel, constraint: bool) -> tuple[Engine, Any]:
    base = load_tank_geometry()
    scenario = dataclasses.replace(load_scenario("S0-A"), duration_s=30., demand_process=False,
                                   variability_profile="off")
    roof = {"TK-101": RoofHangup(base, 9., model.rho, model.g)} if constraint else None
    engine = Engine(model, load_lineup_table(model.topology), scenario, load_sim_config(),
                    ListSink(), "EP-ROOF-TEST", roof_constraints=roof)
    return engine, engine.run()


@pytest.mark.slow
def test_hung_roof_changes_actual_level_and_head_without_a_liquid_mass_sink() -> None:
    """A held-up deck changes measured hydraulic state while both runs retain a closed mass ledger.

    Independent: yes, because volume and conservation are checked directly.
    """
    model = HydraulicModel.load()
    healthy, healthy_outcome = run(model, False)
    constrained, outcome = run(model, True)
    assert outcome.rejection is None and healthy_outcome.rejection is None
    assert outcome.ledger["closed"] is True
    levels = constrained._levels(outcome.final_volumes)
    healthy_levels = healthy._levels(healthy_outcome.final_volumes)
    assert levels["TK-101"] < healthy_levels["TK-101"] - 0.01
    roof = constrained.roof_constraints["TK-101"]
    assert levels["TK-101"] == pytest.approx(
        outcome.final_volumes["TK-101"] / roof.base_geometry.area_m2, abs=1e-8
    )
    assert roof.support_reaction_n(levels["TK-101"]) == pytest.approx(roof.weight_n)
    rows: Any = constrained.sink.rows  # type: ignore[attr-defined]
    network = [row for row in rows["mass_ledger"] if row["scope"] == "network"]
    assert network and all(row["closed"] is True for row in network)
    assert all(abs(row["residual_kg"]) <= row["tolerance_kg"] for row in network)
    assert all(row["closed"] is None for row in rows["mass_ledger"]
               if row["scope"] != "network")


@pytest.mark.slow
def test_rising_liquid_leaves_the_declared_roof_model_domain() -> None:
    """A receipt into a constrained roof is rejected rather than clipped into a plausible trace.

    Independent: yes, because the prescribed inflow increases the liquid above the fixed anchor.
    """
    model = HydraulicModel.load()
    scenario = dataclasses.replace(load_scenario("S0-B"), duration_s=30.)
    roof = RoofHangup(load_tank_geometry(), scenario.tank_levels_m["TK-101"], model.rho, model.g)
    engine = Engine(model, load_lineup_table(model.topology), scenario, load_sim_config(),
                    ListSink(), "EP-ROOF-RECEIPT", roof_constraints={"TK-101": roof})
    result = engine.run()
    assert result.rejection is not None
    assert result.rejection["parameter"] == "roof_domain[TK-101]"


@pytest.mark.slow
def test_coupled_geometry_survives_step_refinement_and_checkpoint_restart() -> None:
    """The roof emergence corner is stable under a smaller time step and checkpoint continuation.

    Independent: yes, because separate grids and a fresh engine must preserve the same solution.
    """
    model = HydraulicModel.load()
    coarse, outcome = run(model, True)
    cfg = load_sim_config()
    parameters = dict(cfg.parameters)
    parameters["time_step_s"] = ParamValue.from_mapping({
        "value": .5, "unit": "s", "status": "provisional", "evidence_tag": "DESIGN",
        "provenance_id": "VERUM-DD-D122-v1.0-refinement",
    })
    fine = Engine(model, coarse.table, coarse.scenario,
                  dataclasses.replace(cfg, parameters=parameters), ListSink(), "EP-ROOF-TEST",
                  roof_constraints=coarse.roof_constraints)
    refined = fine.run()
    assert refined.rejection is None
    assert abs(fine._levels(refined.final_volumes)["TK-101"] -
               coarse._levels(outcome.final_volumes)["TK-101"]) <= cfg["level_accuracy_target_m"]
    first = Engine(model, coarse.table, coarse.scenario, cfg, ListSink(), "EP-ROOF-TEST",
                   roof_constraints=coarse.roof_constraints)
    first.run(until=10.)
    saved = first.checkpoint()
    marks = {key: len(rows) for key, rows in first.sink.rows.items()}  # type: ignore[attr-defined]
    continuous = first.run()
    restarted = Engine(model, coarse.table, coarse.scenario, cfg, ListSink(), "EP-ROOF-TEST",
                       state=saved, roof_constraints=coarse.roof_constraints)
    continued = restarted.run()
    assert continued.final_volumes == continuous.final_volumes
    assert continued.ledger == continuous.ledger
    for key, rows in first.sink.rows.items():  # type: ignore[attr-defined]
        assert rows[marks[key]:] == restarted.sink.rows[key]  # type: ignore[attr-defined]


@pytest.mark.slow
def test_episode_producer_keeps_roof_identity_truth_and_sensor_response(tmp_path: Path) -> None:
    """A native episode records the initial restraint and its censored history without an overlay.

    Independent: yes, because canonical identifiers and the physical volume relation are checked.
    """
    model = HydraulicModel.load()
    scenario = dataclasses.replace(load_scenario("S0-A"), duration_s=30., demand_process=False,
                                   variability_profile="off")
    roof = RoofHangup(load_tank_geometry(), 9., model.rho, model.g)
    with pytest.raises(ContractError, match="gas boundary"):
        run_episode(scenario.scenario_id, tmp_path, model, scenario,
                    fault_timing_profile="observation_window", roof_constraints={"TK-101": roof})
    result = run_episode(scenario.scenario_id, tmp_path, model, scenario,
                         fault_timing_profile="observation_window",
                         roof_constraints={"TK-101": roof},
                         roof_gas_boundary="pressure_equalized_reference")
    assert not result.rejected and result.outcome.ledger["closed"] is True
    truth = load_episode_truth(result.directory)
    assert len(truth) == 1 and truth[0]["fault_type"] == "ROOF_LANDING_ABNORMAL"
    assert truth[0]["causal_parent_fault_instance_id"] is None
    episode = json.loads((result.directory / "episode.json").read_text())
    assert episode["dataset_tier"] == "restricted_benchmark"
    assert episode["fault_instance_ids"] == [truth[0]["fault_instance_id"]]
    window = json.loads((result.directory / "fault_window.json").read_text())
    assert window["left_censored_fault_instance_ids"] == episode["fault_instance_ids"]
    reader = Truth(result.directory)
    state = reader.state(30.)
    tank = state["tanks"]["TK-101"]
    assert tank["level_m"] == pytest.approx(tank["volume_m3"] / roof.base_geometry.area_m2)
    assert state["faults"][0]["fault_instance_id"] == truth[0]["fault_instance_id"]
    assert "roof_constraints.json" in result.file_hashes
    constraints = json.loads((result.directory / "roof_constraints.json").read_text())
    assert constraints["gas_boundary"] == "pressure_equalized_reference"
    assert "fault_window.json" in result.file_hashes
    with pytest.raises(UnresolvedParameter):
        reader.state(31.)
    healthy = run_episode(scenario.scenario_id, tmp_path, model, scenario,
                          fault_timing_profile="observation_window")
    assert not healthy.rejected and healthy.episode_id != result.episode_id
    assert load_episode_truth(healthy.directory) == []
    assert Truth(healthy.directory).horizon_s == 30.
    observed = []
    for episode_result in (result, healthy):
        observed.append({r["t_sim_s"]: r["value"]
                         for r in read_rows(episode_result.directory, "observations")
                         if r["tag_id"] == "LT-101" and r["value"] is not None})
    common = sorted(t for t in observed[0].keys() & observed[1].keys() if t >= 10.)
    assert common and observed[1][common[-1]] - observed[0][common[-1]] > .01


def test_vacuum_adds_area_times_pressure_load_without_inventing_a_failure() -> None:
    """A prescribed 100 Pa differential adds 100 times deck area to the downward support demand.

    Independent: yes, because pressure force is the integral of uniform pressure over deck area.
    """
    model = HydraulicModel.load()
    roof = RoofHangup(load_tank_geometry(), 9., model.rho, model.g)
    top = ParamValue.selected(101325., "Pa_abs", "SIM", "pressure-load-test")
    bottom = ParamValue.selected(101225., "Pa_abs", "SIM", "pressure-load-test")
    load = roof.support_load_with_pressure_n(8., top, bottom)
    assert load == pytest.approx(roof.weight_n + 100 * roof.base_geometry.deck_area_m2)
    assert roof.support_load_with_pressure_n(8., top, top) == pytest.approx(roof.weight_n)
    with pytest.raises(ValueError):
        roof.support_load_with_pressure_n(8., bottom, top)
    with pytest.raises(UnresolvedParameter):
        roof.support_load_with_pressure_n(
            8., top, ParamValue.unresolved("Pa_abs", "vent model open"))
