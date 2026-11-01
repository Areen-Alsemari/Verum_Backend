"""Evaluator-only inventory of campaign faults awaiting an observability audit.

The inventory preserves each original class and groups missing coverage by subtype, lineup and
asset. It is a work queue rather than a relabelling rule, and never calibrates on held-out data.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def inventory(root: Path) -> dict[str, Any]:
    """Read a campaign and return its unresolved fault queue with source-manifest provenance."""
    manifest_bytes = (root / "evaluator" / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    queue = []
    cells: Counter[tuple[str, str, str]] = Counter()
    gaps = []
    for episode in manifest["episodes"]:
        if episode["status"] == "gap":
            gaps.append({"index": episode["index"], "cell": episode["cell"],
                         "attempts": episode["attempts"]})
            continue
        if episode["status"] != "completed":
            raise ValueError(f"unknown slot status: {episode['status']}")
        for fault in episode["faults"]:
            if fault["class"] != "unaudited":
                continue
            key = (fault["subtype"], episode["strata"]["mode"], fault["asset_id"])
            cells[key] += 1
            queue.append({
                "episode_id": episode["episode_id"], "slot_index": episode["index"],
                "fault_instance_id": fault["instance_id"], "subtype": fault["subtype"],
                "asset_id": fault["asset_id"], "mode": key[1], "split": episode["split"],
                "dataset_tier": episode["tier"], "original_class": fault["class"],
                "audit_status": "pending", "audited_class": None,
                "label_rule_fit_eligible": episode["split"] == "train",
                "threshold_calibration_eligible": False,
            })
    return {
        "schema_version": "1.0.0", "dataset": "campaign_audit_inventory", "hidden": True,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "simulation_config_hash": manifest["config_hash"],
        "simulation_code_commit": manifest["code_commit"],
        "pending_faults": len(queue),
        "pending_episodes": len({row["episode_id"] for row in queue}),
        "coverage_cells": [
            {"subtype": key[0], "mode": key[1], "asset_id": key[2], "faults": count}
            for key, count in sorted(cells.items())
        ],
        "gaps": gaps, "queue": queue,
    }


def write_inventory(root: Path, output: Path) -> dict[str, Any]:
    """Write a new evaluator artifact outside the campaign without replacing an existing file."""
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError("audit output must be outside the original campaign")
    result = inventory(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return result
