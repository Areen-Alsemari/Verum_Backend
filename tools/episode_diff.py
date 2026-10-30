"""Run every shipped scenario into a directory, or compare two such directories.

Inputs: ``run <out_dir>`` runs the scenarios; ``diff <dir_a> <dir_b>`` compares the written
hydraulic-state and observation rows of two runs. Outputs: a printed table with, per scenario,
the number of changed rows and the largest absolute change of each numeric field that moved.
Assumptions: the two directories hold episodes of the same scenarios with the same seeds, so
the rows pair by dataset, record type, element, time and side; rows present in only one run are
counted separately.
Source: ``CONTRIBUTING.md`` (tests and phase closure); serves the Phase 5b step 1 list of
scenarios whose observations change.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from typing import Any

from verum.hydraulics import HydraulicModel
from verum.sim.episode import run_episode

SCENARIOS = [
    "S0-A", "S0-B", "S0-C", "S0u-D", "S0u-E", "S0-F", "S0-G", "S0-A-inland",
    "REJ-1", "REJ-2", "REJ-3",
]  # fmt: skip


def run_all(out: Path) -> None:
    model = HydraulicModel.load()
    out.mkdir(parents=True, exist_ok=True)
    for sid in SCENARIOS:
        result = run_episode(sid, out, model)
        (out / f"{sid}.dir").write_text(result.directory.name)
        print(sid, result.directory.name, "rejected" if result.rejected else "completed")


def _rows(path: Path) -> list[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _flat(value: Any, prefix: str = "") -> dict[str, float]:
    out: dict[str, float] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            out.update(_flat(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        out[prefix] = float(value)
    return out


def _key(row: dict[str, Any]) -> tuple[Any, ...]:
    payload = row.get("payload", {})
    return (
        row.get("record_type", row.get("dataset")),
        row.get("element_id", row.get("sensor_id", row.get("asset_id", payload.get("sensor_id")))),
        row.get("t_sim_s", row.get("t_obs_s")),
        row.get("side"),
        row.get("sequence_index"),
    )


def diff_dirs(a: Path, b: Path) -> None:
    for sid in SCENARIOS:
        da, db = a / (a / f"{sid}.dir").read_text(), b / (b / f"{sid}.dir").read_text()
        if not da.exists() or not db.exists():
            continue
        print(f"== {sid}")
        for name in sorted(p.name for p in da.iterdir() if p.suffix in (".gz", ".jsonl")):
            if name.startswith(("provenance", "manifest")) or not (db / name).exists():
                continue
            ra, rb = {_key(r): r for r in _rows(da / name)}, {_key(r): r for r in _rows(db / name)}
            moved: dict[str, float] = {}
            changed = 0
            for k, row in ra.items():
                other = rb.get(k)
                if other is None:
                    continue
                fa, fb = _flat(row), _flat(other)
                hit = False
                for f, v in fa.items():
                    if f in fb and v != fb[f]:
                        moved[f] = max(moved.get(f, 0.0), abs(fb[f] - v))
                        hit = True
                changed += hit
            only = len(set(ra) ^ set(rb))
            if changed or only:
                print(f"  {name}: changed rows {changed}, unpaired {only}")
                for f, d in sorted(moved.items(), key=lambda kv: -kv[1])[:6]:
                    print(f"      {f}: max abs change {d:.6g}")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run_all(Path(sys.argv[2]))
    else:
        diff_dirs(Path(sys.argv[2]), Path(sys.argv[3]))
