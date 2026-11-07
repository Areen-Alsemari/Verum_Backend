"""Checks of the observation adapter and the role-file reader of the shared agent helpers."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from verum.agents.common import (
    TAG_ORDER,
    EpisodeRef,
    RoleRecord,
    episode_lookup,
    iter_role_records,
    stable_hash,
    summary_representation,
)
from verum.contracts.agent_interfaces import content_hash, contract_directory
from verum.sensors import load_sensor_config


def _summary() -> dict[str, Any]:
    path = contract_directory() / "examples" / "predictive_health.request.json"
    request = json.loads(path.read_text(encoding="utf-8"))
    summary: dict[str, Any] = request["input"]["observations"]["summary"]
    return summary


def test_tag_order_is_the_sorted_emitted_tag_list() -> None:
    """The fixed order equals the sorted emitted tags of the sensor configuration.

    Independent: yes, because the configuration is read from a separate source.
    """
    assert list(TAG_ORDER) == sorted(load_sensor_config().tags)
    assert len(set(TAG_ORDER)) == len(TAG_ORDER) == 30


def test_adapter_reorders_signals_and_binds_to_the_summary_hash() -> None:
    """Shuffled signals come out in the fixed order, and the wrapper holds the summary it hashes.

    Independent: yes, because the order is compared with the example, which is sorted by tag.
    """
    summary = _summary()
    shuffled = copy.deepcopy(summary)
    shuffled["signals"].reverse()
    wrapped = summary_representation(shuffled, ["features-x"])
    assert wrapped["representation"] == "summary_v1" and wrapped["evidence_ids"] == ["features-x"]
    assert [s["tag_id"] for s in wrapped["summary"]["signals"]] == list(TAG_ORDER)
    assert [s["tag_id"] for s in summary["signals"]] == list(TAG_ORDER)
    assert content_hash(wrapped["summary"]) == stable_hash(summary)


def test_adapter_rejects_missing_duplicate_extra_and_unknown_fields() -> None:
    """The summary must hold exactly the emitted tags and exactly the summary fields.

    Independent: yes, because the rejected inputs are literal edits of the example.
    """
    summary = _summary()
    missing = copy.deepcopy(summary)
    missing["signals"].pop()
    duplicate = copy.deepcopy(summary)
    duplicate["signals"][1] = duplicate["signals"][0]
    extra = copy.deepcopy(summary)
    extra["signals"].append({**extra["signals"][0], "tag_id": "ZZ-999"})
    unknown = {**copy.deepcopy(summary), "episode_id": "EP-1"}
    for bad in (missing, duplicate, extra, unknown):
        with pytest.raises(ValueError):
            summary_representation(bad, [])


def _write_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _release(root: Path) -> Path:
    rows = [
        {"example_id": "e1", "input": {"observations": {}}, "target": {"t": 1}, "use": "pair"},
        {"example_id": "e2", "input": {"observations": {}}, "target": {"t": 2}, "use": "pair"},
    ]
    role_file = root / "role_views" / "predictive_health" / "train.jsonl.gz"
    _write_gz(role_file, rows)
    inventory = [{
        "role": "predictive_health", "split": "train",
        "file": "role_views/predictive_health/train.jsonl.gz",
        "sha256": hashlib.sha256(role_file.read_bytes()).hexdigest(),
    }]
    (root / "role_views_manifest.json").write_text(json.dumps(inventory), encoding="utf-8")
    lineage = {"episode_id": "EP-1", "parent_group": "EP-1", "source_cutoff_s": 300.0}
    _write_gz(root / "examples" / "train" / "EP-1.jsonl.gz", [
        {"example_id": "e1", "input": {}, "targets": {}, "lineage": lineage},
        {"example_id": "e2", "input": {}, "targets": {}, "lineage": lineage},
    ])
    return root


def test_reader_yields_records_without_episode_information(tmp_path: Path) -> None:
    """Records carry only the example, input, target and use fields.

    Independent: yes, because the release files are written by the test.
    """
    records = list(iter_role_records(_release(tmp_path), "predictive_health", "train"))
    assert [r.example_id for r in records] == ["e1", "e2"]
    assert set(RoleRecord.__dataclass_fields__) == {"example_id", "input", "target", "use"}
    assert records[0].target == {"t": 1}


def test_episode_lookup_is_separate_and_maps_every_example(tmp_path: Path) -> None:
    """The episode mapping is a separate structure keyed by example identifier.

    Independent: yes, because the lineage files are written by the test.
    """
    found = episode_lookup(_release(tmp_path), "train")
    assert found == {
        "e1": EpisodeRef("EP-1", "EP-1", 300.0), "e2": EpisodeRef("EP-1", "EP-1", 300.0),
    }


def test_reader_rejects_bad_names_changed_files_and_incomplete_exports(tmp_path: Path) -> None:
    """Unknown role or split, a changed role file, and an unfinished export are refused.

    Independent: yes, because each failure is created by editing the written release.
    """
    root = _release(tmp_path)
    with pytest.raises(ValueError, match="unknown agent role"):
        list(iter_role_records(root, "nonsense", "train"))
    with pytest.raises(ValueError, match="unknown split"):
        list(iter_role_records(root, "predictive_health", "dev"))
    path = root / "role_views" / "predictive_health" / "train.jsonl.gz"
    _write_gz(path, [{"example_id": "x", "input": {}, "target": {}, "use": "pair"}])
    with pytest.raises(ValueError, match="inventory"):
        list(iter_role_records(root, "predictive_health", "train"))
    unchecked = iter_role_records(root, "predictive_health", "train", verify=False)
    assert [r.example_id for r in unchecked] == ["x"]
    (root / "BUILDING.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete"):
        list(iter_role_records(root, "predictive_health", "train"))
