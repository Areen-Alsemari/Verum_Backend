"""Read fault truth across hydraulic and mechanical tracks without silently losing a track.

All records use the audited hidden fault schema. Duplicate conflicting identifiers or disagreement
with the stored labels is an error, rather than an apparently healthy episode.
"""

from __future__ import annotations

import gzip
import json
from functools import cache
from pathlib import Path
from typing import Any

from verum.contracts import validator


@cache
def _validator() -> Any:
    return validator("fault_truth")


def load_episode_truth(directory: Path) -> list[dict[str, Any]]:
    """Load every fault track and check its identifiers against stored labels when present."""
    paths = [directory / name for name in (
        "fault_truth.jsonl.gz", "mechanical_fault_truth.jsonl.gz"
    ) if (directory / name).exists()]
    if not paths:
        raise ValueError("episode has no declared fault-truth files")
    records: dict[str, dict[str, Any]] = {}
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row: dict[str, Any] = json.loads(line)
                _validator().validate(row)
                ident = row["fault_instance_id"]
                if ident in records and records[ident] != row:
                    raise ValueError(f"conflicting fault truth: {ident}")
                records[ident] = row
    labels_path = directory / "labels.json"
    if labels_path.exists():
        labels = json.loads(labels_path.read_text(encoding="utf-8"))
        expected = {fault["instance_id"] for fault in labels["faults"]}
        if expected != set(records):
            raise ValueError("fault truth and labelled instances disagree")
    return [records[key] for key in sorted(records)]
