"""Literal tiny campaign files shared by supported-release integration checks.

The source includes reported observations and empty canonical fault tracks without an engine run.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from verum.sensors.specs import load_sensor_config
from verum.training.dataset import source_digest


def fixture_source(root: Path) -> Path:
    source = root / "source"
    episode = source / "evaluator/episodes/EP-FIXTURE"
    episode.mkdir(parents=True)
    visible = source / "agent_visible/episodes/EP-FIXTURE/observations.jsonl.gz"
    visible.parent.mkdir(parents=True)
    unit = load_sensor_config().tags["PT-201"].unit
    with gzip.open(visible, "wt") as handle:
        for t in (100.0, 400.0, 700.0):
            row = {
                "episode_id": "EP-FIXTURE",
                "tag_id": "PT-201",
                "unit": unit,
                "t_sim_s": t,
                "t_available_s": t,
                "value": t,
                "quality_flag": "good",
                "availability_status": "available",
            }
            handle.write(json.dumps(row) + "\n")
    (episode / "scenario.json").write_text(json.dumps({"duration_s": 900.0}))
    (episode / "labels.json").write_text(json.dumps({"faults": []}))
    for name in ("fault_truth.jsonl.gz", "validity_windows.jsonl.gz"):
        with gzip.open(episode / name, "wt"):
            pass
    record: dict[str, Any] = {
        "episode_id": "EP-FIXTURE",
        "status": "completed",
        "split": "test",
        "tier": "analytic_verification",
        "faults": [],
        "files": {
            p.relative_to(source).as_posix(): source_digest(p)
            for p in [visible, *episode.iterdir()]
        },
    }
    (source / "evaluator/manifest.json").write_text(json.dumps({"episodes": [record]}))
    return source
