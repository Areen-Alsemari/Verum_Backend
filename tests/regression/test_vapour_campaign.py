"""Mechanical extension generation and independent artifact-corruption checks.

Small hand-built hydraulic records provide a changing tank level and a known observation.
The tests compare stored bytes and split membership, not physical performance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from _inspection_cases import EPISODE, grid, write
from verum.vapour.campaign import generate, write_rows
from verum.vapour.validation import validate_extension


def source(root: Path) -> None:
    rows = grid()
    for row in rows:
        for tank in row["tanks"].values():
            tank["level_m"] = 9.0 + row["t_sim_s"] / 10000.0
    write(root / "evaluator" / "episodes", rows)
    folder = root / "agent_visible" / "episodes" / EPISODE
    folder.mkdir(parents=True)
    observation = {"schema_version": "0.5.0", "dataset": "observations",
                   "episode_id": EPISODE, "tag_id": "LT-101", "t_sim_s": 0.0,
                   "t_available_s": 0.1, "timestamp_utc": "2026-01-01T00:00:00.000Z",
                   "value": 9.0, "unit": "m", "quality_flag": "good",
                   "availability_status": "measured"}
    write_rows(folder / "observations.jsonl.gz", [observation])
    manifest = {"campaign_seed": 20261101,
                "episodes": [{"status": "completed", "episode_id": EPISODE,
                              "kind": "healthy", "tier": "analytic_verification",
                              "split": "test"}]}
    (root / "evaluator" / "manifest.json").write_text(json.dumps(manifest))


def test_generation_preserves_splits_signals_and_source_bytes(tmp_path: Path) -> None:
    """Five children share the test split; all observations match and two workflows replay each.

    Independent: yes, because source bytes and literal expected counts are checked separately.
    """
    base, output = tmp_path / "base", tmp_path / "extension"
    source(base)
    before = {str(p.relative_to(base)): p.read_bytes() for p in base.rglob("*") if p.is_file()}
    manifest = generate(base, output, 5, allow_legacy_simulation=True)
    report = validate_extension(base, output)
    assert report["episodes"] == 5 and report["causal_edges_checked"] == 1
    assert report["inspection_workflows_replayed"] == 10
    assert report["observation_rows_compared"] == 5
    assert all(e["split"] == "test" for e in manifest["episodes"])
    assert report["production_validated"] is False
    assert before == {str(p.relative_to(base)): p.read_bytes()
                      for p in base.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        generate(base, output, 5, allow_legacy_simulation=True)


def test_validation_refuses_changed_files_and_source_manifest(tmp_path: Path) -> None:
    """Changing either a listed child file or the original manifest invalidates the extension.

    Independent: yes, because corruption is introduced after successful generation.
    """
    base, output = tmp_path / "base", tmp_path / "extension"
    source(base)
    manifest = generate(base, output, 5, allow_legacy_simulation=True)
    path = output / next(iter(manifest["episodes"][0]["files"]))
    before = path.read_bytes()
    path.write_bytes(before + b"corrupt")
    with pytest.raises(ValueError, match="hash"):
        validate_extension(base, output)
    path.write_bytes(before)
    source_manifest = base / "evaluator" / "manifest.json"
    source_manifest.write_text(source_manifest.read_text() + " ")
    with pytest.raises(ValueError, match="source manifest"):
        validate_extension(base, output)


def test_stationary_trials_retain_no_secondary_failure(tmp_path: Path) -> None:
    """A stationary tank retains its roof trial without inventing or selecting a seal tear.

    Independent: yes, because every level is explicitly held at 9 m.
    """
    base, output = tmp_path / "base", tmp_path / "extension"
    source(base)
    rows = grid()
    write_rows(base / "evaluator" / "episodes" / EPISODE / "inspection_truth.jsonl.gz", rows)
    manifest = generate(base, output, 5, allow_legacy_simulation=True)
    trial = next(e for e in manifest["episodes"] if e["kind"] == "cascade_trial")
    assert trial["cascade_outcome"] == "not_triggered"
    assert len(trial["faults"]) == 1 and trial["faults"][0]["parent_id"] is None
    assert validate_extension(base, output)["causal_edges_checked"] == 0


def test_assignment_does_not_change_when_the_future_trajectory_changes(tmp_path: Path) -> None:
    """Changing future levels cannot change target selection or the prospective case identities.

    Independent: yes, because only the future trajectory differs between two source copies.
    """
    base = tmp_path / "base"
    source(base)
    first = generate(base, tmp_path / "first", 5, allow_legacy_simulation=True)
    rows = grid()
    for row in rows:
        row["tanks"]["TK-103"]["level_m"] = 9.0 + row["t_sim_s"] / 1000.0
    write_rows(base / "evaluator" / "episodes" / EPISODE / "inspection_truth.jsonl.gz", rows)
    second = generate(base, tmp_path / "second", 5, allow_legacy_simulation=True)
    assert [(e["episode_id"], e["tank_id"]) for e in first["episodes"]] == [
        (e["episode_id"], e["tank_id"]) for e in second["episodes"]
    ]
    assert all(e["training_qualified"] is False for e in second["episodes"])
