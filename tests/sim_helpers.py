"""Small readers shared by the protection-row tests.

Inputs: an episode directory. Outputs: the protection rows of a tank and its tank levels.
Key assumptions: reads the written hydraulic-state file with ``gzip`` and ``json`` only.

Source: ``schemas/hydraulic_state.schema.json``.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any


def protection_rows(
    directory: Path, tank: str
) -> tuple[list[tuple[float, dict[str, Any]]], dict[float, float]]:
    rows: list[tuple[float, dict[str, Any]]] = []
    levels: dict[float, float] = {}
    with gzip.open(directory / "hydraulic_state.jsonl.gz", "rt") as handle:
        for line in handle:
            r = json.loads(line)
            if r["side"] == "pre_event" or r["element_id"] != tank:
                continue
            if r["record_type"] == "protection_state":
                rows.append((r["t_sim_s"], r["payload"]))
            elif r["record_type"] == "tank_state":
                levels[r["t_sim_s"]] = r["payload"]["level_m"]
    return rows, levels
