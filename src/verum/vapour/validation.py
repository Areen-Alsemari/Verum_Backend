"""Integrity and interface checks for the mechanical dataset extension.

The validator compares every copied observation with its healthy parent, verifies all file hashes
and fault graphs, and replays the approval workflow. Numerical agreement checks implementation
consistency and does not establish field validity for reduced mechanics or vapour estimates.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from verum.api import Gateway, check_allowlist
from verum.contracts import validate
from verum.inspection.service import InspectionService
from verum.vapour.campaign import _request, digest, read_rows
from verum.vapour.model import MechanicalFault, Parameters, cascade_child, validate_graph


def validate_extension(base: Path, root: Path) -> dict[str, Any]:
    """Validate every extension record, returning a machine-readable restricted-tier report."""
    manifest = json.loads((root / "evaluator" / "manifest.json").read_text())
    source_path = base / "evaluator" / "manifest.json"
    if digest(source_path) != manifest["base_manifest_sha256"]:
        raise ValueError("source manifest differs from the generation input")
    parents = {e["episode_id"]: e for e in json.loads(source_path.read_text())["episodes"]
               if e["status"] == "completed"}
    p = Parameters()
    if p.hash != manifest["parameter_hash"]:
        raise ValueError("extension parameter hash mismatch")
    ids: set[str] = set()
    file_count = row_count = result_count = causal_edges = 0
    kinds: Counter[str] = Counter()
    splits: Counter[str] = Counter()
    observed_files: set[str] = set()
    for episode in manifest["episodes"]:
        ident = episode["episode_id"]
        if ident in ids:
            raise ValueError("duplicate extension identifier")
        ids.add(ident)
        parent = parents[episode["parent_episode_id"]]
        if episode["split"] != parent["split"] or episode["dataset_tier"] != "restricted_benchmark":
            raise ValueError("split or dataset tier mismatch")
        for rel, expected in episode["files"].items():
            path = (root / rel).resolve()
            if not path.is_relative_to(root.resolve()) or digest(path) != expected:
                raise ValueError(f"invalid file or hash: {rel}")
            observed_files.add(rel)
            file_count += 1
        evaluator = root / "evaluator" / "episodes" / ident
        agent = root / "agent_visible" / "episodes" / ident
        original = read_rows(base / "agent_visible" / "episodes" / parent["episode_id"] /
                             "observations.jsonl.gz")
        copied = read_rows(agent / "observations.jsonl.gz")
        if len(original) != len(copied):
            raise ValueError("observation count changed")
        for source, child in zip(original, copied, strict=True):
            if child != source | {"episode_id": ident}:
                raise ValueError("mechanical extension changed a SCADA signal")
            row_count += 1
        # Validate all distinct tag/quality shapes; all rows above must match source values exactly.
        representatives = {(r["tag_id"], r["quality_flag"], r["availability_status"]): r
                           for r in copied}
        for row in representatives.values():
            validate("observation", row)
        faults = [MechanicalFault(**f) for f in episode["faults"]]
        validate_graph(faults)
        truth = read_rows(evaluator / "mechanical_fault_truth.jsonl.gz")
        if {r["fault_instance_id"] for r in truth} != {f.instance_id for f in faults}:
            raise ValueError("mechanical truth does not match the fault specification")
        for row in truth:
            validate("fault_truth", row)
        if episode["kind"] in ("cascade", "cascade_trial"):
            rows = read_rows(evaluator / "inspection_truth.jsonl.gz")
            tank = episode["tank_id"]
            levels = {r["t_sim_s"]: r["tanks"][tank]["level_m"] for r in rows}
            expected_child = cascade_child(faults[0], sorted(levels.items()), p,
                                           allow_legacy_simulation=True)
            expected_faults = [faults[0]] if expected_child is None else [faults[0], expected_child]
            if faults != expected_faults:
                raise ValueError("cascade child does not follow the travel rule")
            if episode["kind"] == "cascade" and expected_child is None:
                raise ValueError("legacy cascade case has no secondary failure")
            if episode["kind"] == "cascade_trial":
                expected_outcome = "not_triggered" if expected_child is None else "triggered"
                if episode["cascade_outcome"] != expected_outcome:
                    raise ValueError("cascade trial outcome differs from the physical rule")
            causal_edges += expected_child is not None
        service = InspectionService(
            evaluator, allow_extrapolated_research=manifest.get("sampling_protocol") is None
        )
        gateway = Gateway(agent, service)
        replay = json.loads((evaluator / "inspection_replay.json").read_text())
        for index, snapshot in enumerate(replay, 1):
            request = _request(index, snapshot["action_id"], episode["tank_id"])
            gateway.submit_request(request, 1800.0)
            t = snapshot["visible_s"]
            before = gateway.results(t - 0.001)
            current = gateway.results(t)
            check_allowlist(before)
            check_allowlist(current)
            if current["inspection_results"][-1] != snapshot["result"]:
                raise ValueError("inspection replay differs from stored result")
            previous_result = before["inspection_results"][-1]
            if "findings" in previous_result:
                raise ValueError("findings are exposed before delivery")
            result_count += 1
        window = json.loads((evaluator / "vapour_reference_window.json").read_text())
        if window["is_observation"] is not False or window["window_days"] < 30:
            raise ValueError("invalid reference-window applicability")
        masses = [window[k] for k in ("rim_kg", "fitting_kg", "seam_proxy_kg")]
        if not all(math.isfinite(x) and x >= 0 for x in masses):
            raise ValueError("invalid reference mass")
        if not math.isclose(sum(masses), window["component_sum_kg"], rel_tol=1e-12):
            raise ValueError("reference component accounting does not close")
        kinds[episode["kind"]] += 1
        splits[episode["split"]] += 1
    actual = {str(f.relative_to(root)) for branch in ("agent_visible", "evaluator")
              for f in (root / branch).rglob("*") if f.is_file() and
              f != root / "evaluator" / "manifest.json"}
    if actual != observed_files:
        raise ValueError("manifest does not list the exact generated file inventory")
    return {"status": "passed_restricted_synthetic_checks", "episodes": len(ids),
            "files_verified": file_count, "observation_rows_compared": row_count,
            "inspection_workflows_replayed": result_count, "causal_edges_checked": causal_edges,
            "kinds": dict(kinds), "splits": dict(splits), "parameter_hash": p.hash,
            "production_validated": False,
            "limits": ["reduced_mechanics", "SIM_damage_laws", "reference_components_not_total",
                       "schema_validation_by_tag_quality_shape", "no_field_validation"]}
