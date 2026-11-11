"""Reader for the prepared role files of a dataset release, without the training package.

Records are yielded as example identifier, input, target and use. The mapping from an example to its
episode is read separately and only on request, so it cannot travel inside a model input. The
reader checks each role file against the release's own inventory before using it.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from verum.agents.common.context import file_sha256
from verum.agents.common.roles import require_role

SPLITS: Final = ("train", "validation", "test")


@dataclass(frozen=True)
class RoleRecord:
    """One prepared example; the target is for training and evaluation only."""

    example_id: str
    input: dict[str, Any]
    target: dict[str, Any]
    use: str


@dataclass(frozen=True)
class EpisodeRef:
    """Where an example came from, for grouping and evaluation outside any model input."""

    episode_id: str
    parent_group: str
    source_cutoff_s: float


def _require_split(split: str) -> str:
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}")
    return split


def _check_release(root: Path) -> None:
    if (root / "BUILDING.json").exists():
        raise ValueError("export is incomplete")


def _check_role_file(root: Path, role: str, split: str, path: Path) -> None:
    inventory = json.loads((root / "role_views_manifest.json").read_text(encoding="utf-8"))
    entry = next((e for e in inventory if e["role"] == role and e["split"] == split), None)
    if entry is None or file_sha256(path) != entry["sha256"]:
        raise ValueError("role file does not match the release inventory")


def iter_role_records(
    root: Path, role: str, split: str, *, verify: bool = True
) -> Iterator[RoleRecord]:
    """Yield the prepared records of one role and split."""
    require_role(role)
    _require_split(split)
    _check_release(root)
    path = root / "role_views" / role / f"{split}.jsonl.gz"
    if verify:
        _check_role_file(root, role, split, path)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            yield RoleRecord(row["example_id"], row["input"], row["target"], row["use"])


def episode_lookup(root: Path, split: str) -> dict[str, EpisodeRef]:
    """Map each example identifier of a split to its episode, from the example lineage files."""
    _require_split(split)
    _check_release(root)
    found: dict[str, EpisodeRef] = {}
    for path in sorted((root / "examples" / split).glob("*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                lineage = row["lineage"]
                found[row["example_id"]] = EpisodeRef(
                    lineage["episode_id"], lineage["parent_group"], lineage["source_cutoff_s"]
                )
    return found
