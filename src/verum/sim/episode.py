"""Episode runner: release check, engine run, record files and manifest.

Inputs: a scenario identifier and an output directory. Outputs: a directory with the
truth files, ``episode.json``, ``provenance.json``, ``simulation_rejected.json`` (if
rejected) and a hash manifest; and an ``EpisodeResult``.
Key assumptions:
    * The episode record lists the atmosphere stratum, the validity windows and the
      protection threshold crossings (decisions D24 to D26); it is hidden truth.
    * The dataset tier is ``analytic_verification``, or ``restricted_benchmark`` for an
      episode that lists a flagged validity window (decision D37). The release gate is asked
      first for the former and again for the tier actually produced; it fails closed.
    * The episode identifier is derived from the seed, the scenario and the
      configuration hash; two runs with the same inputs write identical files.
    * A completed episode gets its observation rows (``verum.sensors``) after the truth is
      final; they are written next to the truth and listed in the manifest.
    * A rejected episode keeps only its records: the truth files are removed so that
      a rejected run cannot be mistaken for data.
    * ``provenance.json`` carries the git commit; the deterministic episode record
      does not.

Source: ``VERUM_INTEGRATION_README.md`` section E (rejected candidates are stored as
such); ``docs/design_decisions.md`` D20, D24, D25, D26, D37.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verum.contracts import validate
from verum.gates import assert_release_allowed
from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.provenance import config_hash, episode_id, git_state, lockfile_hash
from verum.sensors import observe_episode
from verum.sim.config import SimConfig, load_sim_config
from verum.sim.engine import Engine, EpisodeOutcome
from verum.sim.scenario import Scenario, load_scenario
from verum.truth import DirectorySink, file_hashes

SOLVER_VERSION = "path-dynamics-radau-1"
TIER = "analytic_verification"
RESTRICTED_TIER = "restricted_benchmark"


def tier_of(outcome: EpisodeOutcome) -> str:
    """Decision D37: an episode with a flagged validity window is restricted."""
    return RESTRICTED_TIER if outcome.windows else TIER


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
) -> dict[str, Any]:
    levels = scenario.tank_levels_m
    return {
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
        "validity_windows": [w.as_row() for w in outcome.windows],
        "protection_crossings": outcome.crossings,
        "pipe_inventory_constant": True,
        "status": status,
        "hidden": True,
    }


def run_episode(
    scenario_id: str,
    out_dir: Path,
    model: HydraulicModel | None = None,
    scenario: Scenario | None = None,
) -> EpisodeResult:
    assert_release_allowed(TIER)
    model = model or HydraulicModel.load()
    cfg = load_sim_config(model.directory)
    scenario = scenario or load_scenario(scenario_id, model.directory)
    chash = config_hash(model.directory)
    episode = episode_id(scenario.seed, scenario.scenario_id, chash)
    sink = DirectorySink(out_dir / episode)
    engine = Engine(
        model, load_lineup_table(model.topology, model.directory), scenario, cfg, sink, episode
    )
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
    document = episode_document(scenario, cfg, model, episode, chash, status, outcome)
    validate("episode", document)
    sink.write_json("episode.json", document)
    commit, dirty = git_state()
    sink.write_json("provenance.json", {"git_commit": commit, "git_dirty": dirty})
    hashes = sink.finalize()
    if not outcome.rejection:
        observe_episode(out_dir / episode)  # agent-visible rows, written next to the truth
        hashes = file_hashes(out_dir / episode)
    return EpisodeResult(episode, out_dir / episode, outcome, wall, hashes)
