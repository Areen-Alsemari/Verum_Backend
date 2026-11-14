"""Checks of the live-mode confinement, the import boundary of the service and a real live run."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from _service_cases import call, events_of, get_json, start_run
from verum.contracts.paths import repo_root
from verum.service import guard

RELEASE = repo_root() / "data" / "reference_release_v2" / "verum_reference_v2"
HIDDEN = ("verum.truth", "verum.training", "verum.sim", "verum.faults", "verum.sensors")


@pytest.mark.parametrize("relative", [
    "knowledge/public_reference.json", "role_views_manifest.json",
    "role_views/diagnostic_reasoning/validation.jsonl.gz", "examples/validation/a.jsonl.gz",
])
def test_the_guard_allows_what_a_validation_run_reads(relative: str) -> None:
    """Knowledge, the inventory, the validation role views and validation examples are allowed.

    Independent: yes, because the paths are written out by hand.
    """
    assert guard.classify(relative) == "allowed"


@pytest.mark.parametrize("relative", [
    "role_views/diagnostic_reasoning/test.jsonl.gz",
    "role_views/diagnostic_reasoning/train.jsonl.gz", "examples/test/a.jsonl.gz",
    "examples/train/a.jsonl.gz", "evaluator/source_episodes/EP-1/labels.json",
    "observations/test/EP-1/x.json", "role_views/../evaluator/x",
    "knowledge/../evaluator/source_episodes/EP-1/labels.json", "knowledge//x",
])
def test_the_guard_refuses_the_test_and_train_splits_and_everything_else(relative: str) -> None:
    """Any other part of a release is refused, the test split first of all.

    Independent: yes, because the paths are written out by hand.
    """
    assert guard.classify(relative) == "rejected"


def test_the_installed_hook_raises_on_a_test_file_and_ignores_other_paths(tmp_path: Path) -> None:
    """In a fresh process, opening a test-split file under the release raises; others do not.

    Independent: yes, because the hook runs in a separate interpreter on a throwaway folder.
    """
    release = tmp_path / "release"
    for name in ("role_views/r/validation.jsonl.gz", "role_views/r/test.jsonl.gz"):
        (release / name).parent.mkdir(parents=True, exist_ok=True)
        (release / name).write_text("x")
    (tmp_path / "outside.txt").write_text("x")
    code = textwrap.dedent(f"""
        import json, sys
        from pathlib import Path
        from verum.service import guard
        release = Path({str(release)!r})
        guard.confine(release)
        out = {{}}
        for name in ("role_views/r/validation.jsonl.gz", "role_views/r/test.jsonl.gz"):
            try:
                open(release / name).close(); out[name] = "opened"
            except PermissionError:
                out[name] = "refused"
        import os
        os.chdir({str(tmp_path)!r})
        try:
            open("release/role_views/r/test.jsonl.gz").close(); out["relative"] = "opened"
        except PermissionError:
            out["relative"] = "refused"
        open({str(tmp_path / "outside.txt")!r}).close()
        out["rejected"] = guard.summary()["rejected"]
        print(json.dumps(out))
    """)
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["role_views/r/validation.jsonl.gz"] == "opened"
    assert result["role_views/r/test.jsonl.gz"] == "refused"
    assert result["relative"] == "refused"
    assert [Path(p).name for p in result["rejected"]] == ["test.jsonl.gz", "test.jsonl.gz"]


def test_the_service_imports_neither_the_truth_nor_the_training_side() -> None:
    """Importing the whole service loads no truth, training, simulation, fault or sensor package.

    Independent: yes, because the check lists the modules of a fresh interpreter.
    """
    code = ("import sys, verum.service.app, verum.service.__main__\n"
            "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('verum.'))))")
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    loaded = done.stdout.split()
    assert [m for m in loaded if m.startswith(HIDDEN)] == []
    assert "verum.service.app" in loaded


def test_a_live_run_on_the_validation_split_through_the_started_service() -> None:
    """The service started as a process runs the real runner on a validation episode.

    Independent: yes, because the statuses are checked against the runner's own contract.
    """
    if not (RELEASE / "knowledge" / "public_reference.json").exists():
        pytest.skip("the release data is not present")
    process = subprocess.Popen(
        [sys.executable, "-m", "verum.service", "--port", "0", "--release", str(RELEASE)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert process.stdout is not None
        port = int(process.stdout.readline().rsplit(":", 1)[1])
        assert get_json(port, "/api/health")["modes"]["live"] is True
        episodes = get_json(port, "/api/episodes?mode=live")["episodes"]
        shortest = min(episodes, key=lambda e: e["windows"])
        run = start_run(port, mode="live", episode_id=shortest["episode_id"])
        started = time.monotonic()
        events = events_of(port, run)
        results = [e for e in events if e["type"] == "window_result"]
        assert events[-1]["status"] == "completed" and len(results) == shortest["windows"]
        assert {e["mode"] for e in events} == {"live"}
        assert all(a["status"] is not None for r in results for a in r["agents"].values())
        assert results[-1]["decision"]["automatic_action_authorized"] is False
        assert call(port, "GET", f"/api/runs/{run}/truth")[0] == 404
        assert get_json(port, f"/api/runs/{run}/report")["report"]["advisory_only"] is True
        assert time.monotonic() - started < 120
    finally:
        process.terminate()
        process.wait(10)
