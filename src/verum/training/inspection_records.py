"""Inspection metadata exercises preserve archived evidence without endorsing its findings.

Only coverage and record-completeness facts become targets, never legacy condition categories.
Parent-related records keep one split and incomplete timelines cannot qualify a measurement.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, TypeGuard

from verum.inspection.catalog import UNQUALIFIED_ACTIONS, load_catalog


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
    coverage = bool(performed and _finite_number(performed_s) and 0 <= performed_s <= horizon_s)
    timeline_valid = _timeline_valid(item, performed_s)
    metric_valid = _metric_valid(metric, request["action_id"])
    supported_model = not legacy and request["action_id"] not in UNQUALIFIED_ACTIONS
    reasons = []
    if not performed:
        reasons.append("no_performed_result")
    if performed and not coverage:
        reasons.append("process_horizon_does_not_cover_performance")
    if performed and not timeline_valid:
        reasons.append("workflow_timing_unverified")
    if metric and not metric_valid:
        reasons.append("measurement_invalid_or_incomplete")
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
        "workflow_timing_verified": timeline_valid,
        "measurement_record_complete": metric_valid,
        "equipment_acceptance_tolerance_supplied": False,
    }
    return {
        "input": inputs,
        "target": {
            "performance_within_process_coverage": coverage,
            "raw_measurement_supported": coverage
            and supported_model
            and not missing
            and metric_valid
            and timeline_valid,
            "workflow_timing_valid": timeline_valid,
            "condition_acceptance_supported": False,
            "equipment_condition": None,
            "quality_flags": reasons,
            "decision": "retain_provenance_and_hold_condition_conclusion",
        },
    }


def _finite_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _metric_valid(metric: dict[str, Any], action_id: str) -> bool:
    catalog = load_catalog()
    action = catalog.actions.get(action_id)
    matched = action is not None and any(
        o.name == metric.get("name") and o.unit == metric.get("unit") and o.modelled
        for o in action.outputs
    )
    return (
        matched
        and isinstance(metric.get("name"), str)
        and bool(metric["name"].strip())
        and isinstance(metric.get("unit"), str)
        and bool(metric["unit"].strip())
        and _finite_number(metric.get("value"))
        and _finite_number(metric.get("uncertainty_k2"))
        and metric["uncertainty_k2"] >= 0
    )


def _timeline_valid(item: dict[str, Any], performed: Any) -> bool:
    timeline = item.get("timeline") or {}
    names = ("t_requested_s", "t_decision_s", "t_start_s", "t_performed_s", "t_visible_s")
    times = [timeline.get(name) for name in names]
    if not all(_finite_number(t) for t in times):
        return False
    checked = [float(t) for t in times if t is not None]
    requested = item["request"].get("t_requested_sim_s")
    action = load_catalog().actions.get(item["request"]["action_id"])
    return bool(
        action is not None
        and _finite_number(requested)
        and item.get("cancellation") is None
        and checked[3] == checked[2] + action.duration_s
        and timeline.get("reason", "unknown") is None
        and checked[0] == requested
        and checked[0] >= 0
        and checked[3] == performed
        and all(a <= b for a, b in zip(checked, checked[1:], strict=False))
    )


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
