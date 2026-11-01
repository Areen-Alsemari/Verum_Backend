"""Audit inventory coverage, provenance and preservation of campaign records.

Small literal manifests isolate counting and output rules from the simulation engine.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from verum.evaluation.campaign_audit import inventory, write_inventory


def campaign(root: Path) -> Path:
    episodes: list[dict[str, Any]] = []
    for index, split in enumerate(("train", "validation", "test")):
        episodes.append({
            "status": "completed", "index": index, "episode_id": f"EP-{index}",
            "strata": {"mode": "DELIVER_101_A"}, "split": split,
            "tier": "analytic_verification", "faults": [
                {"instance_id": f"FI-{index}", "subtype": "stuck", "asset_id": "LT-101",
                 "class": "unaudited"},
                {"instance_id": f"FI-known-{index}", "class": "clear"},
            ],
        })
    episodes.append({"status": "gap", "index": 3, "cell": "missing", "attempts": []})
    path = root / "evaluator" / "manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"episodes": episodes, "config_hash": "config",
                                "code_commit": "commit"}), encoding="utf-8")
    return path


def test_inventory_keeps_unknown_labels_and_separates_held_out_data(tmp_path: Path) -> None:
    """Three unresolved faults share one cell, and only the train row may calibrate a rule.

    Independent: yes, because the fixture explicitly contains one row for each split.
    """
    root = tmp_path / "campaign"
    path = campaign(root)
    before = path.read_bytes()
    result = inventory(root)
    assert result["pending_faults"] == result["pending_episodes"] == 3
    assert len(result["gaps"]) == 1
    assert result["coverage_cells"] == [
        {"subtype": "stuck", "mode": "DELIVER_101_A", "asset_id": "LT-101", "faults": 3}
    ]
    assert [row["label_rule_fit_eligible"] for row in result["queue"]] == [True, False, False]
    assert all(row["audited_class"] is None for row in result["queue"])
    assert not any(row["threshold_calibration_eligible"] for row in result["queue"])
    assert result["hidden"] is True
    assert result["manifest_sha256"] == hashlib.sha256(before).hexdigest()
    assert path.read_bytes() == before


def test_output_cannot_replace_campaign_data_or_an_existing_artifact(tmp_path: Path) -> None:
    """The artifact must be new and outside the campaign; a second write leaves it untouched.

    Independent: yes, because the checks compare literal stored bytes before and after failures.
    """
    root = tmp_path / "campaign"
    campaign(root)
    with pytest.raises(ValueError):
        write_inventory(root, root / "agent_visible" / "audit.json")
    output = tmp_path / "review" / "audit.json"
    write_inventory(root, output)
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        write_inventory(root, output)
    assert output.read_bytes() == before
