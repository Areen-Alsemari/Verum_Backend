"""Check that the committed chained fixtures equal a fresh run of the placeholder agents."""

from __future__ import annotations

import json
from pathlib import Path

from _runner_cases import reference
from verum.agents.runner import Snapshot
from verum.agents.runner.chained import chained_files

FOLDER = Path(__file__).resolve().parents[1] / "fixtures" / "chained"


def test_the_committed_chained_fixtures_are_not_stale() -> None:
    """A fresh placeholder run reproduces every committed file byte for byte.

    If this fails, regenerate the fixtures with the build script and commit the result.
    Independent: no, because the same code that wrote the files produces the comparison, but the
    comparison itself is against files stored earlier.
    """
    stored = {path.name: path.read_text(encoding="utf-8") for path in FOLDER.glob("*.json")}
    context = json.loads(stored["index.json"])["context"]
    summary = json.loads(stored["predictive_health.request.json"])["input"]["observations"]
    snapshot = Snapshot(
        case_id=context["case_id"], revision=context["revision"], as_of_s=context["as_of_s"],
        summary=summary["summary"], reference=reference(),
        reference_snapshot_sha256=context["reference_snapshot_sha256"],
    )
    fresh = chained_files(snapshot)
    assert sorted(fresh) == sorted(stored)
    assert [name for name in fresh if fresh[name] != stored[name]] == []
