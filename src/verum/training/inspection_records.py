"""Inspection metadata exercises preserve archived evidence without endorsing its findings.

Only coverage and record-completeness facts become targets, never legacy condition categories.
Mechanical children keep their hydraulic parent's split; native roof references stay challenge-only.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from verum.inspection.catalog import UNQUALIFIED_ACTIONS


def inspection_example(
    item: dict[str, Any],
    horizon_s: float,
    *,
    legacy: bool,
) -> dict[str, Any]:
    """Describe a retrospective record with numerical findings withheld."""
    result = item.get("result") or {}
    request = item["request"]
    performed = result.get("workflow_status") == "performed"
    performed_s = result.get("performed_at_t_sim_s")
    metric = (result.get("findings") or {}).get("primary_metric") or {}
    missing = result.get("evidence_status") == "missing"
    coverage = bool(performed and performed_s is not None and 0 <= performed_s <= horizon_s)
    supported_model = not legacy and request["action_id"] not in UNQUALIFIED_ACTIONS
    reasons = []
    if not performed:
        reasons.append("no_performed_result")
    if performed and not coverage:
        reasons.append("process_horizon_does_not_cover_performance")
    if not supported_model:
        reasons.append("measurement_model_unqualified")
    if missing or not metric:
        reasons.append("measurement_missing")
    inputs = {
        "task": "retrospective_record_quality_review",
        "source_is_synthetic": True,
        "action_id": request["action_id"],
        "workflow_status": result.get("workflow_status", "not_performed"),
        "performed_at_s": performed_s,
        "process_horizon_s": horizon_s,
        "evidence_status": result.get("evidence_status"),
        "measurement_model_qualified": supported_model,
        "measurement_model_qualification_scope": "reduced_reference_simulator",
        "metric": {
            "name": metric.get("name"),
            "unit": metric.get("unit"),
            "numerical_value_withheld": True,
            "value_recorded": bool(metric and metric.get("value") is not None),
            "uncertainty_recorded": metric.get("uncertainty_k2") is not None,
        },
        "equipment_acceptance_tolerance_supplied": False,
    }
    return {
        "input": inputs,
        "target": {
            "performance_within_process_coverage": coverage,
            "raw_measurement_supported": coverage
            and supported_model
            and not missing
            and bool(metric),
            "condition_acceptance_supported": False,
            "equipment_condition": None,
            "quality_flags": reasons,
            "decision": "retain_provenance_and_hold_condition_conclusion",
        },
    }


def build_inspection_exercises(
    source: Path,
    output: Path,
    source_splits: dict[str, str],
    *,
    native: bool = False,
) -> dict[str, Any]:
    """Derive metadata exercises from hash-checked replays without altering archived results."""
    from verum.training.dataset import digest, source_digest

    manifest_path = source / "evaluator" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    counts: Counter[str] = Counter()
    records = []
    path = output / "inspection_quality.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for entry in manifest["episodes"]:
            if entry.get("status", "completed") != "completed":
                continue
            ident = entry["episode_id"]
            directory = source / "evaluator" / "episodes" / ident
            replay_path, scenario_path = (
                directory / "inspection_replay.json",
                directory / "scenario.json",
            )
            for p in (replay_path, scenario_path):
                expected = entry["files"][p.relative_to(source).as_posix()]
                if source_digest(p) != expected:
                    raise ValueError(f"inspection source changed: {p}")
            horizon = float(json.loads(scenario_path.read_text())["duration_s"])
            parent = entry.get("parent_episode_id", ident)
            split = (
                "challenge"
                if native and entry["split"] == "research_reference"
                else source_splits[parent]
            )
            if split != "challenge" and split != entry["split"]:
                raise ValueError("inspection child differs from parent split")
            for index, item in enumerate(json.loads(replay_path.read_text())):
                row = inspection_example(item, horizon, legacy=not native)
                key = hashlib.sha256(f"inspection/{ident}/{index}".encode()).hexdigest()[:24]
                row.update(
                    example_id=key,
                    split=split,
                    lineage={
                        "episode_id": ident,
                        "parent_group": parent,
                        "source_manifest_sha256": digest(manifest_path),
                    },
                )
                handle.write(json.dumps(row, allow_nan=False) + "\n")
                counts[split] += 1
                counts["raw_measurement_supported"] += row["target"]["raw_measurement_supported"]
                for flag in row["target"]["quality_flags"]:
                    counts[flag] += 1
            records.append(ident)
    return {
        "file": path.relative_to(output.parent).as_posix(),
        "sha256": digest(path),
        "source_manifest_sha256": digest(manifest_path),
        "source_episodes": len(records),
        "counts": dict(counts),
        "scope": "record_quality_not_condition_diagnosis",
    }
