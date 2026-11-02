"""Paired roof-boundary references with real simulated process and inspection coverage.

Parent selection uses declared operating modes and original splits, never measured outcomes.
The rigid constraint changes the coupled liquid geometry; it does not assert material failure.
All attempted cases and workflow outcomes remain recorded without outcome-based replacement.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

from verum.api import Gateway, check_allowlist
from verum.contracts.paths import config_dir
from verum.hydraulics import HydraulicModel
from verum.inspection.catalog import Catalog, load_catalog
from verum.inspection.service import InspectionService
from verum.params import ParamValue
from verum.provenance import config_hash, git_state
from verum.sim.episode import run_episode
from verum.sim.scenario import parse_scenario
from verum.tanks import load_tank_geometry
from verum.tanks.hangup import RoofHangup
from verum.training.dataset import digest, source_digest
from verum.training.truth import load_episode_truth


def select_parents(source: Path) -> list[dict[str, Any]]:
    """Choose one existing healthy parent per available split/delivering-tank cell."""
    manifest = json.loads((source / "evaluator/manifest.json").read_text())
    candidates: dict[tuple[str, str], list[tuple[bool, str, dict[str, Any]]]] = {}
    for row in manifest["episodes"]:
        if (
            row["status"] != "completed"
            or row["kind"] != "healthy"
            or row["tier"] != "analytic_verification"
        ):
            continue
        path = source / "evaluator/episodes" / row["episode_id"] / "scenario.json"
        if source_digest(path) != row["files"][path.relative_to(source).as_posix()]:
            raise ValueError("parent scenario changed")
        document = json.loads(path.read_text())
        mode = document["initial"]["mode"]
        if "DELIVER_" not in mode:
            continue
        tank = "TK-" + mode.split("DELIVER_", 1)[1].split("_", 1)[0]
        if mode.startswith("RECEIVE_" + tank[-3:]):
            continue
        if any(command["command"] == "lineup" for command in document["schedule"]):
            continue
        key = row["split"], tank
        rank = hashlib.sha256(row["episode_id"].encode()).hexdigest()
        candidates.setdefault(key, []).append(
            (
                not mode.startswith("DELIVER_"),
                rank,
                {"record": row, "scenario": document, "tank_id": tank},
            )
        )
    return [min(items, key=lambda item: item[:2])[2] for _, items in sorted(candidates.items())]


def coverage_duration(catalog: Catalog, requested: ParamValue) -> float:
    """Cover worst-case approval, scheduling, performance and result publication in seconds."""
    if requested.unit != "s" or requested.value < 0:
        raise ValueError("request time must be nonnegative seconds")
    overhead = sum(
        catalog.param("workflow", key)
        for key in ("approval_delay_max_s", "scheduling_delay_max_s", "result_delay_s")
    )
    return float(math.ceil(requested.value + overhead + catalog.action("ACT-INSP-05").duration_s))


def _run_reference(job: tuple[dict[str, Any], bool, Path, dict[str, Any]]) -> dict[str, Any]:
    parent, constrained, output, contract = job
    record, tank = parent["record"], parent["tank_id"]
    catalog = load_catalog()
    requested = ParamValue.from_mapping(contract["parameters"]["request_time_s"])
    document = dict(parent["scenario"])
    document["scenario_id"] = "ROOF-REFERENCE-" + record["episode_id"]
    document["duration_s"] = coverage_duration(catalog, requested)
    scenario = parse_scenario(document)
    model = HydraulicModel.load()
    roof = RoofHangup(load_tank_geometry(), scenario.tank_levels_m[tank], model.rho, model.g)
    result = run_episode(
        scenario.scenario_id,
        output / "evaluator/episodes",
        model,
        scenario,
        fault_timing_profile="observation_window",
        roof_constraints={tank: roof} if constrained else None,
        roof_gas_boundary=contract["gas_boundary"] if constrained else None,
    )
    common = {
        "parent_episode_id": record["episode_id"],
        "split": record["split"],
        "tank_id": tank,
        "kind": "held_boundary" if constrained else "floating_control",
        "training_qualified": False,
        "physical_failure_label": None,
        "secondary_failure_label": None,
        "source_scenario_sha256": record["files"][
            f"evaluator/episodes/{record['episode_id']}/scenario.json"
        ],
    }
    if result.rejected:
        return common | {"status": "rejected", "rejection": result.outcome.rejection}
    if not result.outcome.ledger["closed"]:
        raise ValueError("reference liquid ledger does not close")
    ident, directory = result.episode_id, result.directory
    visible = output / "agent_visible/episodes" / ident
    visible.mkdir(parents=True)
    shutil.move(directory / "observations.jsonl.gz", visible / "observations.jsonl.gz")
    truth = load_episode_truth(directory)
    if len(truth) != int(constrained):
        raise ValueError("reference fault track differs from the prescribed boundary")
    service = InspectionService(directory)
    gateway = Gateway(visible, service)
    request = {
        "schema_version": "0.5.0",
        "dataset": "inspection_requests",
        "request_id": "REQ-INSP-00001",
        "t_requested_sim_s": requested.value,
        "action_id": "ACT-INSP-05",
        "target_asset": tank,
        "justification": {
            "competing_hypotheses": ["inventory consistent", "inventory differs"],
            "agent_reported_information_gain_bits": 0.0,
            "estimated_cost_usd": catalog.action("ACT-INSP-05").cost_usd,
        },
        "human_approval": {"status": "PENDING"},
    }
    gateway.submit_request(request, requested.value)
    rec = service.record(request["request_id"])
    clock = rec.timeline.t_visible_s if rec.timeline.approved else rec.timeline.t_decision_s
    if rec.cancellation is not None:
        clock = rec.cancellation[0]
    view = gateway.results(clock)
    check_allowlist(view)
    replay = [
        {
            "request": request,
            "timeline": asdict(rec.timeline),
            "cancellation": rec.cancellation,
            "result": view["inspection_results"][0],
        }
    ]
    (directory / "inspection_replay.json").write_text(json.dumps(replay, indent=2) + "\n")
    labels = common | {
        "episode_id": ident,
        "status": "completed",
        "tier": "restricted_benchmark" if constrained else "analytic_verification",
        "faults": [
            {
                "instance_id": f["fault_instance_id"],
                "fault_type": f["fault_type"],
                "asset_id": f["asset_id"],
                "onset_s": f["onset_t_sim_s"],
                "class": "unaudited",
            }
            for f in truth
        ],
    }
    (directory / "labels.json").write_text(json.dumps(labels, indent=2) + "\n")
    local_hashes = {
        p.name: digest(p)
        for p in directory.iterdir()
        if p.is_file() and p.name != "MANIFEST.sha256"
    }
    (directory / "MANIFEST.sha256").write_text(
        "".join(f"{expected}  {name}\n" for name, expected in sorted(local_hashes.items()))
    )
    files = {
        p.relative_to(output).as_posix(): source_digest(p)
        for folder in (directory, visible)
        for p in folder.iterdir()
        if p.is_file()
    }
    return labels | {
        "files": files,
        "liquid_ledger_closed": True,
        "duration_s": scenario.duration_s,
        "inspection_records": len(replay),
    }


def build_roof_reference(source: Path, output: Path, *, workers: int = 1) -> dict[str, Any]:
    """Generate every prospectively selected control/constraint pair without replacing outcomes."""
    if output.exists() or output.resolve().is_relative_to(source.resolve()) or workers < 1:
        raise ValueError("a new external output directory and positive worker count are required")
    commit, dirty = git_state()
    if dirty:
        raise ValueError("reference generation requires a committed source tree")
    contract_path = config_dir() / "extensions/roof_reference_v1.json"
    contract = json.loads(contract_path.read_text())
    parents = select_parents(source)
    if not parents:
        raise ValueError("no eligible withdrawal reference parents")
    output.mkdir(parents=True)
    (output / "BUILDING.json").write_text('{"complete": false}\n')
    jobs = [
        (parent, constrained, output, contract)
        for parent in parents
        for constrained in (False, True)
    ]
    records = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for record in pool.map(_run_reference, jobs):
            records.append(record)
            print(f"{len(records)}/{len(jobs)} reference attempts recorded", flush=True)
    manifest = {
        "schema_version": "1.0.0",
        "dataset": "coupled_roof_reference",
        "code_commit": commit,
        "config_hash": config_hash(),
        "source_manifest_sha256": digest(source / "evaluator/manifest.json"),
        "contract_sha256": digest(contract_path),
        "contract": contract,
        "sampling_protocol": "one_parent_per_available_split_withdrawal_tank_cell",
        "hidden": True,
        "physical_training_qualified": False,
        "episodes": records,
        "attempts": len(jobs),
        "rejected_attempts": sum(r["status"] == "rejected" for r in records),
    }
    target = output / "evaluator/manifest.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    (output / "BUILDING.json").unlink()
    return manifest
