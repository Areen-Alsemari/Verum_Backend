"""Short engine runs with an injected fault, shared by the fault tests.

A run uses a shipped scenario with its duration shortened, healthy twins use the same seed, and the
faults are given directly because the eligibility validator is tested separately, so tests can use
short onsets. The helpers return the engine, its rows and its outcome and write no files.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from verum.faults import FaultSet, FaultSpec
from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine, EpisodeOutcome
from verum.sim.scenario import load_scenario
from verum.truth import ListSink


def leak(
    edge: str, area: float, onset: float, ramp: float, x: float = 0.5, cd: float = 0.62
) -> FaultSet:
    return FaultSet((FaultSpec("PIPE_LEAK", "orifice", edge, onset, ramp, area, x, cd),))


def engine(
    model: HydraulicModel,
    scenario_id: str,
    duration: float,
    faults: FaultSet | None = None,
    state: Any = None,
    sink: ListSink | None = None,
    **scenario_fields: Any,
) -> Engine:
    scenario = dataclasses.replace(
        load_scenario(scenario_id), duration_s=duration, **scenario_fields
    )
    return Engine(
        model, load_lineup_table(model.topology), scenario, load_sim_config(), sink or ListSink(),
        "EP-TEST", state, faults,
    )  # fmt: skip


def run(
    model: HydraulicModel, scenario_id: str, duration: float, faults: FaultSet | None = None,
    **scenario_fields: Any,
) -> tuple[Engine, EpisodeOutcome]:  # fmt: skip
    e = engine(model, scenario_id, duration, faults, **scenario_fields)
    return e, e.run()


def edge_series(e: Engine, edge: str, key: str = "flow_m3s") -> dict[float, float]:
    """Grid rows (no pre-event twin) of an edge payload field by time."""
    sink: Any = e.sink
    return {
        r["t_sim_s"]: r["payload"].get(key, 0.0)
        for r in sink.rows["hydraulic_state"]
        if r["record_type"] == "edge_state" and r["element_id"] == edge and r["side"] != "pre_event"
    }
