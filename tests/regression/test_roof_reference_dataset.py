"""Prospective roof reference selection and inspection coverage preserve original splits.

Literal manifests test that no recorded trajectory is consulted to select the experiment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from verum.inspection.catalog import load_catalog
from verum.params import ParamValue, UnresolvedParameter
from verum.training.dataset import source_digest
from verum.training.reference import coverage_duration, select_parents


def parent(
    root: Path, ident: str, split: str, mode: str, *, kind: str = "healthy"
) -> dict[str, Any]:
    scenario = root / "evaluator/episodes" / ident / "scenario.json"
    scenario.parent.mkdir(parents=True)
    scenario.write_text(json.dumps({"initial": {"mode": mode}, "schedule": []}))
    return {
        "episode_id": ident,
        "split": split,
        "kind": kind,
        "status": "completed",
        "tier": "analytic_verification",
        "files": {scenario.relative_to(root).as_posix(): source_digest(scenario)},
    }


def test_parent_selection_keeps_withdrawing_tanks_and_source_splits(tmp_path: Path) -> None:
    """A receiving-only tank and a tank with net receipt are excluded before any simulation.

    Independent: yes, because declared modes and splits are literal inputs without trajectories.
    """
    records = [
        parent(tmp_path, "A", "train", "DELIVER_101_A"),
        parent(tmp_path, "B", "validation", "DELIVER_102_B"),
        parent(tmp_path, "C", "test", "RECEIVE_101_DELIVER_102_A"),
        parent(tmp_path, "D", "test", "RECEIVE_101_DELIVER_101_A"),
        parent(tmp_path, "E", "test", "RECEIVE_103"),
        parent(tmp_path, "F", "train", "DELIVER_103_A", kind="single"),
    ]
    (tmp_path / "evaluator/manifest.json").write_text(json.dumps({"episodes": records}))
    chosen = select_parents(tmp_path)
    assert {(r["record"]["split"], r["tank_id"]) for r in chosen} == {
        ("train", "TK-101"),
        ("validation", "TK-102"),
        ("test", "TK-102"),
    }
    assert len(chosen) == 3
    records.reverse()
    (tmp_path / "evaluator/manifest.json").write_text(json.dumps({"episodes": records}))
    assert select_parents(tmp_path) == chosen


def test_reference_duration_covers_existing_workflow_worst_case() -> None:
    """The known 1800+1800+900+2700+120 s workflow fits within the derived horizon.

    Independent: yes, because the sum is hand-derived from the existing catalog selections.
    """
    requested = ParamValue.selected(1800.0, "s", "DESIGN", "fixture-existing-time")
    assert coverage_duration(load_catalog(), requested) == 7320.0
    with pytest.raises(ValueError):
        coverage_duration(load_catalog(), ParamValue.selected(1800.0, "m", "DESIGN", "fixture"))
    with pytest.raises(UnresolvedParameter):
        coverage_duration(load_catalog(), ParamValue.unresolved("s"))
