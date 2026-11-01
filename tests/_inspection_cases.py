"""Small builders of an evaluator directory with hand-chosen true quantities.

A row of the inspection truth has nominal values: tanks at 9 m, every edge flowing at 0.1 m3/s with
3.5 bar at its start and 3.4 bar at its end, every valve open, both pumps running and every tag at
1 with no offset. A test changes the fields it needs, so the expected outcome of an action is hand
arithmetic on those fields.
"""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
from typing import Any

from verum.contracts import load_topology
from verum.inspection.catalog import PRESSURE_TRANSMITTERS
from verum.sensors import load_sensor_config

TOPOLOGY = load_topology()
EDGES = [e.edge_id for e in TOPOLOGY.edges]
VALVES = sorted(n for n in TOPOLOGY.nodes if n.startswith("XV-"))
TAGS = [t for t, s in load_sensor_config().tags.items() if s.kind == "continuous"]
EPISODE = "EP-TESTEPISODE"
SEED = 4242
HORIZON = 3600.0


def row(t: float, side: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": "0.7.0", "dataset": "inspection_truth", "episode_id": EPISODE,
        "t_sim_s": t, "side": side,
        "tanks": {k: {"level_m": 9.0, "temperature_K": 298.15, "volume_m3": 6000.0}
                  for k in TOPOLOGY.tank_ids},
        "edges": {e: {"flow_m3s": 0.1, "p_from_pa_gauge": 350000.0, "p_to_pa_gauge": 340000.0}
                  for e in EDGES},
        "valves": {v: {"commanded_open": True, "position_frac": 1.0, "contact_open": 1}
                   for v in VALVES},
        "pumps": {p: {"run_state": "running", "speed_ratio": 1.0, "head_scale": 1.0}
                  for p in TOPOLOGY.pumps},
        "leaks": [], "faults": [],
        "tags": {t_: {"value": 9.0 if t_.startswith("LT-") else 1.0, "fault_offset": 0.0}
                 for t_ in TAGS},
        "hidden": True,
    }  # fmt: skip


def grid(step: float = 60.0, horizon: float = HORIZON) -> list[dict[str, Any]]:
    return [row(k * step) for k in range(int(horizon // step) + 1)]


def edit(rows: list[dict[str, Any]], path: str, value: Any, since: float = 0.0) -> None:
    """Set a dotted field in every row from time ``since`` on."""
    for r in rows:
        if r["t_sim_s"] >= since:
            node = r
            *parents, leaf = path.split(".")
            for key in parents:
                node = node[key]
            node[leaf] = value


def write(
    directory: Path, rows: list[dict[str, Any]], faults: list[dict[str, Any]] | None = None,
    seed: int = SEED, horizon: float = HORIZON,
) -> Path:  # fmt: skip
    """Write an evaluator directory named like an episode and return it."""
    folder = directory / EPISODE
    folder.mkdir(parents=True, exist_ok=True)
    scenario = {"scenario_id": "C000000", "seed": seed, "duration_s": horizon}
    (folder / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    for name, data in (("inspection_truth", rows), ("fault_truth", faults or [])):
        with gzip.open(folder / f"{name}.jsonl.gz", "wt", encoding="utf-8") as handle:
            handle.writelines(json.dumps(r) + "\n" for r in data)
    return folder


def fault_truth(
    asset: str, fault_type: str, onset: float, ramp: float, base: float, full: float,
    index: int = 0,
) -> dict[str, Any]:  # fmt: skip
    return {
        "fault_type": fault_type, "fault_instance_id": f"FI-{EPISODE}-{index:02d}",
        "asset_id": asset, "onset_t_sim_s": onset,
        "severity_trajectory": {"knots": [[0.0, 0.0], [ramp, 1.0]]},
        "physical_parameter_modified": {
            "baseline_value": {"value": base}, "fault_value_at_severity_one": {"value": full}
        },
    }  # fmt: skip


def request(
    number: int, action: str, target: str, t: float = 100.0, hypotheses: int = 3,
    gain: float = 1.0,
) -> dict[str, Any]:  # fmt: skip
    return {
        "schema_version": "0.5.0", "dataset": "inspection_requests",
        "request_id": f"REQ-INSP-{number:05d}", "t_requested_sim_s": t, "action_id": action,
        "target_asset": target,
        "justification": {
            "competing_hypotheses": [f"hypothesis {i}" for i in range(hypotheses)],
            "agent_reported_information_gain_bits": gain, "estimated_cost_usd": 100.0,
        },
        "human_approval": {"status": "PENDING"},
    }  # fmt: skip


def clone(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return copy.deepcopy(rows)


__all__ = ["PRESSURE_TRANSMITTERS"]
