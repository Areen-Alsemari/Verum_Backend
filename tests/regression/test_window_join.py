"""Joining validity-window identifiers to observation rows by time, on the evaluation side.

The join sits in the evaluation package and not in the api package, and the gateway imports nothing
from it. A row belongs to a window if its sample time lies between the start and end of the window,
and the expected membership is computed directly from the window times of the episode record.

See D25.
"""

from __future__ import annotations

import ast
import gzip
import json
from pathlib import Path
from typing import Any

from verum.evaluation import attach_window_ids, load_windows
from verum.sim.episode import EpisodeResult


def test_the_s0ue_windows_are_attached_to_the_samples_inside_them(
    episodes: dict[str, EpisodeResult],
) -> None:
    """Each observation row of the isolation scenario receives the identifiers of the windows that
    contain its sample time. Independent: yes, because the membership is computed by a direct
    comparison with the recorded window times.
    """
    directory = episodes["S0u-E"].directory
    with gzip.open(directory / "observations.jsonl.gz", "rt") as handle:
        rows = [json.loads(line) for line in handle]
    windows = load_windows(directory)
    assert sorted(w["kind"] for w in windows) == [
        "dead_leg_unvalidated", "flow_collapse", "valve_stroke",
    ]  # fmt: skip
    collapse = next(w for w in windows if w["kind"] == "flow_collapse")
    joined = attach_window_ids(rows, windows)
    for r in joined:
        expected = [
            w["window_id"] for w in windows if w["t_start_s"] <= r["t_sim_s"] <= w["t_end_s"]
        ]
        assert r["validity_window_ids"] == expected
    inside = [r for r in joined if collapse["window_id"] in r["validity_window_ids"]]
    # The collapse lasts 0.19 s: the seven 1 s tags put about 1.3 rows inside it.
    assert len(joined) == len(rows) and len(inside) >= 1
    first = min(w["t_start_s"] for w in windows) - 1e-9  # the 10 s closure starts first
    assert all(not r["validity_window_ids"] for r in joined if r["t_sim_s"] < first)
    assert all("validity_window_ids" not in r for r in rows)  # the input is not modified


def test_overlapping_open_and_empty_windows() -> None:
    """Overlapping windows, a window with no end and a window that holds no row are all joined
    correctly. Independent: yes, because the expected membership is written out in the test.
    """
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
    """The gateway modules import nothing from the evaluation package. Independent: yes, because the
    check parses the source.
    """
    for path in (root / "src" / "verum" / "api").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
        ]
        assert not [m for m in names if "evaluation" in m], path.name
