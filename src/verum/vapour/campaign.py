"""A reproducible mechanical extension over healthy stored hydraulic episodes.

Each child retains its parent's split and observed signals, with a new opaque episode identifier.
Roof and fitting evidence comes only through the approval emulator, and monthly reference cases
are separate constant-condition estimates. Reduced mechanics do not feed forces into hydraulics.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from verum.api import Gateway, check_allowlist
from verum.contracts import validate
from verum.inspection.catalog import load_catalog
from verum.inspection.service import InspectionService
from verum.provenance import git_state
from verum.vapour.model import (
    TANKS,
    MechanicalFault,
    Parameters,
    cascade_child,
    reference_window,
)

KINDS = ("healthy", "seal", "fitting", "roof", "cascade")


def read_rows(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write deterministic gzip bytes with no wall-clock metadata."""
    content = "".join(json.dumps(r, sort_keys=True, allow_nan=False) + "\n" for r in rows)
    path.write_bytes(gzip.compress(content.encode(), mtime=0))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _target(rows: list[dict[str, Any]]) -> tuple[str, float]:
    """Tank with the greatest travel after the roof-hang-up ramp is established."""
    eligible = [r for r in rows if r["t_sim_s"] >= 900.0]
    if not eligible:
        raise ValueError("episode does not cover the mechanical onset")
    travel = {}
    for tank in TANKS:
        levels = {r["t_sim_s"]: r["tanks"][tank]["level_m"] for r in eligible}
        anchor = next(iter(levels.values()))
        travel[tank] = max(abs(level - anchor) for level in levels.values())
    tank = max(TANKS, key=lambda t: travel[t])
    return tank, travel[tank]


def _faults(
    episode: str, kind: str, tank: str, peak: float, rows: list[dict[str, Any]], p: Parameters
) -> list[MechanicalFault]:
    if kind == "healthy":
        return []
    kind_id = {"seal": "RIM_SEAL_DETERIORATION", "fitting": "FITTING_DAMAGE",
               "roof": "ROOF_LANDING_ABNORMAL", "cascade": "ROOF_LANDING_ABNORMAL"}[kind]
    root = MechanicalFault(f"FI-{episode}-00", kind_id, tank, 600.0, 300.0, peak,
                           "access_hatch" if kind == "fitting" else None)
    if kind != "cascade":
        return [root]
    levels = {r["t_sim_s"]: r["tanks"][tank]["level_m"] for r in rows}
    child = cascade_child(root, sorted(levels.items()), p)
    if child is None:
        raise ValueError("selected parent has insufficient tank travel for a cascade")
    return [root, child]


def _truth(episode: str, faults: list[MechanicalFault]) -> list[dict[str, Any]]:
    def param(value: float) -> dict[str, Any]:
        return {"value": value, "unit": "1", "status": "provisional",
                "evidence_tag": "SIM", "provenance_id": "D121-1.0"}

    rows = []
    for fault in faults:
        row: dict[str, Any] = {
            "schema_version": "0.5.0", "dataset": "fault_truth", "episode_id": episode,
            "fault_type": fault.fault_type, "fault_instance_id": fault.instance_id,
            "causal_parent_fault_instance_id": fault.parent_id, "asset_id": fault.tank_id,
            "onset_t_sim_s": fault.onset_s, "mechanism_status": "provisional",
            "mechanism": "synthetic_roof_hang_up_to_seal_tear" if fault.parent_id else
                         "synthetic_mechanical_damage",
            "severity_trajectory": {"type": "piecewise_linear",
                                    "time_basis": "seconds_since_onset",
                                    "knots": [[0.0, 0.0], [fault.ramp_s, fault.peak]],
                                    "interpolation": "linear", "outside_support": "hold_last"},
            "physical_parameter_modified": {"name": "mechanical_damage_fraction", "unit": "1",
                                            "baseline_value": param(0.0),
                                            "fault_value_at_severity_one": param(1.0),
                                            "mapping": "persistent linear ramp; D121"},
            "conserved_quantity_effects": [], "hidden": True,
        }
        validate("fault_truth", row)
        rows.append(row)
    return rows


def _request(number: int, action: str, tank: str) -> dict[str, Any]:
    return {
        "schema_version": "0.5.0", "dataset": "inspection_requests",
        "request_id": f"REQ-INSP-{number:05d}", "t_requested_sim_s": 1800.0,
        "action_id": action, "target_asset": tank,
        "justification": {"competing_hypotheses": ["intact", "mechanical defect"],
                          "agent_reported_information_gain_bits": 0.0,
                          "estimated_cost_usd": load_catalog().action(action).cost_usd},
        "human_approval": {"status": "PENDING"},
    }


def _episode(
    base: Path, output: Path, parent: dict[str, Any], kind: str, peak: float, p: Parameters
) -> dict[str, Any]:
    source = base / "evaluator" / "episodes" / parent["episode_id"]
    rows = read_rows(source / "inspection_truth.jsonl.gz")
    # A cascade needs travel on the selected tank; choose using evaluator quantities only.
    tank, _ = _target(rows)
    identity = json.dumps([parent["episode_id"], kind, peak, tank, p.hash])
    episode = "EP-" + hashlib.sha256(identity.encode()).hexdigest()[:12].upper()
    agent = output / "agent_visible" / "episodes" / episode
    evaluator = output / "evaluator" / "episodes" / episode
    for folder in (agent, evaluator):
        folder.mkdir(parents=True)
    faults = _faults(episode, kind, tank, peak, rows, p)
    for row in rows:
        row["episode_id"] = episode
    write_rows(evaluator / "inspection_truth.jsonl.gz", rows)
    write_rows(evaluator / "fault_truth.jsonl.gz", [])
    write_rows(evaluator / "mechanical_fault_truth.jsonl.gz", _truth(episode, faults))
    observations = read_rows(base / "agent_visible" / "episodes" / parent["episode_id"] /
                             "observations.jsonl.gz")
    for row in observations:
        row["episode_id"] = episode
    write_rows(agent / "observations.jsonl.gz", observations)
    scenario = json.loads((source / "scenario.json").read_text())
    (evaluator / "scenario.json").write_text(json.dumps(scenario, sort_keys=True))
    sidecar = {"schema_version": "1.0.0", "hidden": True, "parameter_hash": p.hash,
               "faults": [asdict(f) for f in faults]}
    (evaluator / "mechanical_faults.json").write_text(json.dumps(sidecar, sort_keys=True))
    service = InspectionService(evaluator)
    snapshots = []
    gateway = Gateway(agent, service)
    for i, action in enumerate(("ACT-INSP-01", "ACT-INSP-06"), 1):
        request = _request(i, action, tank)
        service.submit(request, 1800.0)
        timeline = service.record(request["request_id"]).timeline
        before = gateway.results(timeline.t_visible_s - 0.001)
        check_allowlist(before)
        if any(r["workflow_status"] == "performed" and r["request_id"] == request["request_id"]
               for r in before["inspection_results"]):
            raise AssertionError("inspection result visible before delivery")
        after = gateway.results(timeline.t_visible_s)
        check_allowlist(after)
        snapshots.append({"action_id": action, "visible_s": timeline.t_visible_s,
                          "request": service.requests(timeline.t_visible_s)[-1],
                          "result": service.results(timeline.t_visible_s)[-1]})
    (evaluator / "inspection_replay.json").write_text(json.dumps(snapshots, sort_keys=True))
    temperature = float(rows[-1]["tanks"][tank]["temperature_K"])
    seal = max((f.peak for f in faults if f.fault_type == "RIM_SEAL_DETERIORATION"), default=0.)
    fit = max((f.peak for f in faults if f.fault_type == "FITTING_DAMAGE"), default=0.)
    window = reference_window(temperature, 30.0, 30.0, seal, fit, p,
                              "access_hatch" if fit else None)
    (evaluator / "vapour_reference_window.json").write_text(json.dumps(window, sort_keys=True))
    labels = {"episode_id": episode, "parent_episode_id": parent["episode_id"],
              "split": parent["split"], "kind": kind, "peak": peak, "tank_id": tank,
              "dataset_tier": "restricted_benchmark", "faults": [asdict(f) for f in faults],
              "limitations": ["reduced_mechanics_no_hydraulic_force_feedback",
                              "not_for_physical_fault_training",
                              "monthly_reference_not_episode_loss"]}
    (evaluator / "labels.json").write_text(json.dumps(labels, sort_keys=True))
    return labels | {"files": {str(path.relative_to(output)): digest(path)
                               for folder in (agent, evaluator)
                               for path in sorted(folder.iterdir()) if path.is_file()}}


def generate(base: Path, output: Path, n: int) -> dict[str, Any]:
    """Generate a new extension directory; refuse overwrites and retain parent split membership."""
    if output.exists() or n < 5 or n % 5:
        raise ValueError("output must be new and n must be a positive multiple of five")
    manifest_path = base / "evaluator" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    parents = [e for e in manifest["episodes"] if e["status"] == "completed" and
               e["kind"] == "healthy" and e["tier"] == "analytic_verification"]
    if not parents:
        raise ValueError("campaign has no eligible healthy parents")
    p = Parameters()
    selected = []
    for parent in parents:
        path = base / "evaluator" / "episodes" / parent["episode_id"]
        _, travel = _target(read_rows(path / "inspection_truth.jsonl.gz"))
        if travel >= p["seal_tear_displacement_m"]:
            selected.append(parent)
        if len(selected) == n // 5:
            break
    if len(selected) < n // 5:
        raise ValueError("not enough distinct healthy parents with travel for the cascade design")
    episodes = []
    # Blocks share a healthy parent and therefore its split; no child crosses a split.
    for block in range(n // 5):
        parent = selected[block]
        peak = (0.25, 0.5, 1.0)[block % 3]
        for kind in KINDS:
            episodes.append(_episode(base, output, parent, kind, peak, p))
    result = {"schema_version": "1.0.0", "dataset": "mechanical_extension", "hidden": True,
              "base_manifest_sha256": digest(manifest_path), "parameter_hash": p.hash,
              "code_commit": git_state()[0], "episodes": episodes}
    (output / "evaluator" / "manifest.json").write_text(json.dumps(result, sort_keys=True))
    return result
