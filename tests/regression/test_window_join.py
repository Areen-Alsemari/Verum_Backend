"""Joining validity-window identifiers to observation rows by time (evaluation side).

Inputs: the S0u-E episode (one flagged window) and small synthetic cases. Outputs: pass/fail.
Key assumptions:
    * The join sits in ``verum.evaluation``, not in ``verum.api``; the gateway imports
      nothing from the evaluation package, and the audited audit schema is not changed.
    * A row belongs to a window if ``t_start_s <= t_sim_s <= t_end_s`` (sample time).
Independence: the expected membership is computed here by a direct comparison with the window
times written in the episode record.

Source: ``docs/design_decisions.md`` D25.
"""

from __future__ import annotations

import ast
import gzip
import json
from pathlib import Path
from typing import Any

from verum.evaluation import attach_window_ids, load_windows
from verum.sim.episode import EpisodeResult


def test_the_s0ue_collapse_window_is_attached_to_the_samples_inside_it(
    episodes: dict[str, EpisodeResult],
) -> None:
    directory = episodes["S0u-E"].directory
    with gzip.open(directory / "observations.jsonl.gz", "rt") as handle:
        rows = [json.loads(line) for line in handle]
    windows = load_windows(directory)
    assert len(windows) == 1
    w = windows[0]
    joined = attach_window_ids(rows, windows)
    inside = [r for r in joined if r["validity_window_ids"]]
    expected = [r for r in rows if w["t_start_s"] <= r["t_sim_s"] <= w["t_end_s"]]
    assert [r["t_sim_s"] for r in inside] == [r["t_sim_s"] for r in expected]
    assert all(r["validity_window_ids"] == [w["window_id"]] for r in inside)
    assert len(joined) == len(rows) and len(inside) >= 10  # 1 s tags and event tags are inside
    assert all(not r["validity_window_ids"] for r in joined if r["t_sim_s"] < w["t_start_s"] - 1e-9)
    assert all("validity_window_ids" not in r for r in rows)  # the input is not modified


def test_overlapping_open_and_empty_windows() -> None:
    rows = [{"t_sim_s": float(t)} for t in (0, 5, 10, 15, 20)]
    windows: list[dict[str, Any]] = [
        {"window_id": "VW-0002", "t_start_s": 10.0, "t_end_s": None},
        {"window_id": "VW-0001", "t_start_s": 5.0, "t_end_s": 15.0},
    ]
    joined = attach_window_ids(rows, windows)
    assert [r["validity_window_ids"] for r in joined] == [
        [], ["VW-0001"], ["VW-0001", "VW-0002"], ["VW-0001", "VW-0002"], ["VW-0002"]
    ]  # fmt: skip
    assert [r["validity_window_ids"] for r in attach_window_ids(rows, [])] == [[]] * 5


def test_the_gateway_does_not_import_the_evaluation_package(root: Path) -> None:
    for path in (root / "src" / "verum" / "api").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
        ]
        assert not [m for m in names if "evaluation" in m], path.name
