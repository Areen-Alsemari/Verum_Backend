"""Episode runner: release check, engine run, record files and manifest.

The episode record lists the atmosphere stratum, the validity windows and the protection threshold
crossings, and is hidden truth. The dataset tier is analytic verification, or restricted benchmark
for an episode with a flagged validity window, and the release gate fails closed. The episode
identifier derives from the seed, the scenario and the configuration hash, so equal inputs write
identical files. A rejected episode keeps only its records so that it cannot be mistaken for data.

See D20, D24 to D26, D37 and D73.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verum.contracts import ContractError, validate
from verum.faults import FaultSet, activity, fault_truth_rows, instance_ids, lineup_states
from verum.faults import check as check_faults
from verum.faults.validate import TIMING_PROFILES
from verum.gates import assert_release_allowed
from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.provenance import canonical_json, config_hash, episode_id, git_state, lockfile_hash
from verum.sensors import observe_episode
from verum.sensors.specs import load_sensor_config
from verum.sim.config import SimConfig, load_sim_config
from verum.sim.engine import Engine, EpisodeOutcome
from verum.sim.inspection import write_inspection_truth
from verum.sim.scenario import Scenario, load_scenario
from verum.truth import DirectorySink, file_hashes

SOLVER_VERSION = "path-dynamics-radau-1"
TIER = "analytic_verification"
RESTRICTED_TIER = "restricted_benchmark"


def tier_of(outcome: EpisodeOutcome) -> str:
    """Decision D37: an episode with a flagged validity window is restricted, except that a
    dead-leg window no emitted tag reads does not restrict it (D150)."""
    return RESTRICTED_TIER if any(w.restricts for w in outcome.windows) else TIER


@dataclass(frozen=True)
class EpisodeResult:
    episode_id: str
    directory: Path
    outcome: EpisodeOutcome
    wall_clock_s: float
    file_hashes: dict[str, str]

    @property
    def rejected(self) -> bool:
        return self.outcome.rejection is not None


def episode_document(
    scenario: Scenario,
    cfg: SimConfig,
    model: HydraulicModel,
    episode: str,
    chash: str,
    status: str,
    outcome: EpisodeOutcome,
    fault_ids: list[str] | None = None,
    fault_notes: dict[str, list[Any]] | None = None,
) -> dict[str, Any]:
    levels = scenario.tank_levels_m
    document: dict[str, Any] = {
        "schema_version": "0.7.0",
        "dataset": "episode",
        "episode_id": episode,
        "scenario_id": scenario.scenario_id,
        "seed": scenario.seed,
        "config_hash": chash,
        "lockfile_hash": lockfile_hash(),
        "solver_version": SOLVER_VERSION,
        "dataset_tier": tier_of(outcome),
        "step_size_s": cfg["time_step_s"],
        "duration_s": scenario.duration_s,
        "temperature_c": scenario.temperature_c,
        "fitting_profile": scenario.fitting_profile,
        "healthy_envelope": scenario.healthy_envelope,
        "fluid_density_kg_m3": model.rho,
        "initial_tank_levels_m": dict(levels),
        "tolerances": {
            "mass_conservation_kg_s": model.config["mass_conservation_tolerance_kg_s"],
            "newton_flow_m3s": model.config["newton_flow_tolerance_m3s"],
            "level_accuracy_m": cfg["level_accuracy_target_m"],
        },
        "atmosphere_stratum": scenario.atmosphere_stratum,
        "volatility_class": scenario.volatility_class,
        "atmosphere_pa_abs": model.for_stratum(scenario.atmosphere_stratum).patm,
        "demand_process": scenario.demand_process,
        "events_evaluated": outcome.events_evaluated,
        "fault_instance_ids": fault_ids or [],
        "validity_windows": [w.as_row() for w in outcome.windows],
        "protection_crossings": outcome.crossings,
        "pipe_inventory_constant": True,
        "status": status,
        "hidden": True,
    }
    if fault_ids and fault_notes:  # decisions D74 and D76; healthy episodes keep their record
        document["fault_modes"] = fault_notes["modes"]
        document["fault_activity"] = fault_notes["activity"]
    if scenario.variability_profile == "v2":  # absent for off and v1, which stay as they were
        document["variability_profile"] = "v2"
        document["demand_regimes"] = outcome.regimes
        document["demand_regime_redraws"] = outcome.regime_redraws
    return document


def run_episode(
    scenario_id: str,
    out_dir: Path,
    model: HydraulicModel | None = None,
    scenario: Scenario | None = None,
    faults: FaultSet | None = None,
    max_faults: int = 1,
    min_separation_s: float = 0.0,
    *,
    fault_timing_profile: str = "legacy",
) -> EpisodeResult:
    if fault_timing_profile not in TIMING_PROFILES:
        raise ContractError(f"unknown fault timing profile: {fault_timing_profile}")
    assert_release_allowed(TIER)
    model = model or HydraulicModel.load()
    cfg = load_sim_config(model.directory)
    scenario = scenario or load_scenario(scenario_id, model.directory)
    sensors = load_sensor_config(model.directory)
    continuous = [t for t, spec in sensors.tags.items() if spec.kind == "continuous"]
    table = load_lineup_table(model.topology, model.directory)
    notes: dict[str, list[Any]] | None = None
    if faults is not None and faults.specs:
        edges = [e.edge_id for e in model.topology.edges]
        states = lineup_states(
            scenario.initial_mode, scenario.receipt_setpoint_m3h, scenario.schedule,
            table.modes, faults.specs[0].onset_s,
        )  # fmt: skip
        contexts = {spec.asset_id: lineup_states(
            scenario.initial_mode, scenario.receipt_setpoint_m3h, scenario.schedule,
            table.modes, spec.onset_s,
        ) for spec in faults.specs}
        check_faults(
            faults.specs,
            edges,
            continuous,
            scenario.duration_s,
            states,
            max_faults,
            min_separation_s,
            fault_timing_profile,
            contexts,
        )
        notes = {"modes": [s.fault_mode for s in faults.specs], "activity": []}
        for spec in faults.specs:  # each fault is judged in the lineup in force from its own onset
            own = lineup_states(
                scenario.initial_mode, scenario.receipt_setpoint_m3h, scenario.schedule,
                table.modes, spec.onset_s,
            )  # fmt: skip
            notes["activity"].append(activity(spec, own))
    chash = config_hash(model.directory)
    identity = scenario.scenario_id
    if fault_timing_profile != "legacy":
        identity = canonical_json({
            "scenario": scenario.scenario_id, "fault_timing_profile": fault_timing_profile,
            "fault_specs": [spec.as_record() for spec in faults.specs] if faults else [],
        })
    episode = episode_id(scenario.seed, identity, chash)
    sink = DirectorySink(out_dir / episode)
    engine = Engine(model, table, scenario, cfg, sink, episode, faults=faults)
    start = time.perf_counter()
    outcome = engine.run()
    wall = time.perf_counter() - start
    status = "rejected" if outcome.rejection else "completed"
    if outcome.rejection:
        sink.discard_data()
        record = {
            "schema_version": "0.7.0",
            "dataset": "simulation_rejected",
            "episode_id": episode,
            "scenario_id": scenario.scenario_id,
            **outcome.rejection,
            "hidden": True,
        }
        validate("simulation_rejected", record)
        sink.write_json("simulation_rejected.json", record)
    assert_release_allowed(tier_of(outcome))  # the tier actually produced is asked as well
    specs = faults.specs if faults is not None else ()
    ids = [] if outcome.rejection else instance_ids(episode, specs)  # never label a rejected run
    if not outcome.rejection:
        for row in fault_truth_rows(episode, specs):
            validate("fault_truth", row)
            sink.write("fault_truth", row)
    document = episode_document(scenario, cfg, model, episode, chash, status, outcome, ids, notes)
    validate("episode", document)
    sink.write_json("episode.json", document)
    commit, dirty = git_state()
    sink.write_json("provenance.json", {"git_commit": commit, "git_dirty": dirty})
    hashes = sink.finalize()
    if not outcome.rejection:
        if fault_timing_profile != "legacy":
            window = {
                "schema_version": "1.0.0", "hidden": True,
                "fault_timing_profile": fault_timing_profile,
                "left_censored_fault_instance_ids": [
                    ident for ident, spec in zip(ids, specs, strict=True)
                    if spec.onset_s == 0 and spec.ramp_s is None and spec.peak_severity > 0
                ],
                "interpretation": "Initial faults were present when observation began; "
                                  "their historical onset is not known.",
            }
            (out_dir / episode / "fault_window.json").write_text(
                json.dumps(window, sort_keys=True), encoding="utf-8"
            )
        hook = None
        if faults is not None and faults.specs:
            spans = {
                t: sensors.tags[t].range_hi - sensors.tags[t].range_lo  # type: ignore[operator]
                for t in continuous
            }
            hook = faults.sensor_hook(spans)
        observe_episode(out_dir / episode, hook=hook)  # agent-visible rows, next to the truth
        write_inspection_truth(out_dir / episode, faults, model.directory)
        hashes = file_hashes(out_dir / episode)
    return EpisodeResult(episode, out_dir / episode, outcome, wall, hashes)
