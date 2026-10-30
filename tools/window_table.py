"""Validity windows and dataset tier of each shipped scenario, from stored episode directories.

Inputs: one or two directories written by ``tools/episode_diff.py run``. Outputs: a printed table
per scenario of the tier, the number of windows by kind and the time they cover; with two
directories, the tier changes between them. Run as ``python tools/window_table.py <dir> [<dir2>]``.
Assumptions: the episode record (``episode.json``) is the source of the windows and the tier
(decisions D25 and D37); a rejected scenario has no data and is listed as rejected.
Source: ``docs/design_decisions.md`` D25, D37, D53, D54; serves the Phase 5b report.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SCENARIOS = (
    "S0-A", "S0-B", "S0-C", "S0u-D", "S0u-E", "S0-F", "S0-G", "S0-A-inland",
    "REJ-1", "REJ-2", "REJ-3",
)  # fmt: skip


def episode(directory: Path, sid: str) -> dict[str, Any]:
    folder = directory / (directory / f"{sid}.dir").read_text()
    loaded: dict[str, Any] = json.loads((folder / "episode.json").read_text(encoding="utf-8"))
    return loaded


def summary(record: dict[str, Any]) -> dict[str, Any]:
    kinds: dict[str, int] = defaultdict(int)
    covered: dict[str, float] = defaultdict(float)
    for w in record["validity_windows"]:
        kinds[w["kind"]] += 1
        covered[w["kind"]] += (w["t_end_s"] or record["duration_s"]) - w["t_start_s"]
    return {
        "status": record["status"],
        "tier": record["dataset_tier"],
        "windows": dict(kinds),
        "seconds_covered": {k: round(v, 1) for k, v in covered.items()},
    }


def table(directory: Path) -> dict[str, dict[str, Any]]:
    return {sid: summary(episode(directory, sid)) for sid in SCENARIOS}


def main(dirs: list[Path]) -> None:
    tables = [table(d) for d in dirs]
    for sid in SCENARIOS:
        for label, t in zip(("A", "B"), tables, strict=False):
            r = t[sid]
            head = f"{sid:12s} {label} {r['status']:9s} {r['tier']:22s}"
            print(head, r["windows"], r["seconds_covered"])
    if len(tables) == 2:
        print("tier changes:")
        for sid in SCENARIOS:
            a, b = tables[0][sid]["tier"], tables[1][sid]["tier"]
            if a != b:
                print(f"  {sid}: {a} -> {b}")


if __name__ == "__main__":
    main([Path(p) for p in sys.argv[1:]])
