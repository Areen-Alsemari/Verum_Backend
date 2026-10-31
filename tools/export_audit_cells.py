"""Export the audit classes of stuck-at and misrouting (a) cells to a configuration file.

Each cell of the agent-side audit that has no severity coordinate is keyed by subtype, lineup and
asset, and takes its class from the scaled margin of the nominal-design runs (invisible below 1,
marginal below 3, clear from 3). A cell that the audit rejected is listed with its gate and has no
class. Only the profile used by the campaign is exported.

See D154.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from verum.evaluation.agent_audit import klass

PROFILE = "v2"
LINEUPS = {"A": "DELIVER_101_A", "B": "RECEIVE_101", "C": "RECEIVE_101_DELIVER_102_A"}
SOURCE = Path("local/results/audit_cells.json")
TARGET = Path("config/audit_cells.json")


def cell_key(label: str) -> tuple[str, str] | None:
    """The key and profile of a stuck-at or misrouting (a) cell label; other labels give None."""
    p = label.split("|")
    if p[0] == "case" and p[1] == "stuck" and p[-1] == PROFILE:
        return f"stuck/{LINEUPS[p[2]]}/{p[3]}", PROFILE
    if p[0] == "misroute_a" and p[-1] == PROFILE and p[1] in LINEUPS:
        return f"misroute_a/{LINEUPS[p[1]]}/{p[2]}", PROFILE
    return None


def export(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cells: dict[str, Any] = {}
    rejected: dict[str, str] = {}
    for row in rows:
        found = cell_key(row["label"])
        if found is None:
            continue
        key = found[0]
        if row.get("rejected"):
            rejected[key] = str(row["rejected"])
        else:
            cells[key] = {"class": klass(row["margin"]), "margin": round(row["margin"], 3)}
    return {
        "description": "Audit class of the stuck-at and misrouting (a) cells, by lineup and asset.",
        "profile": PROFILE, "cells": dict(sorted(cells.items())),
        "rejected": dict(sorted(rejected.items())),
    }  # fmt: skip


def main() -> None:
    rows = json.loads(SOURCE.read_text(encoding="utf-8"))
    TARGET.write_text(json.dumps(export(rows), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
