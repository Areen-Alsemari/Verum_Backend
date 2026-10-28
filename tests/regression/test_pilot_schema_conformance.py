"""Known non-conformance of the analytic pilot observations with the schema.

Inputs: ``config/reference/pilot_agent_observations_ANALYTIC_ONLY.json`` and
``schemas/observation.schema.json``. Outputs: pass/fail. The pilot file is not
modified; this test records exactly why its rows are rejected.
Key assumptions: every one of the 74 rows lacks the same three envelope keys
and is otherwise valid, so the failure is a missing envelope and not a content
defect. The pilot is analytic-verification data only.

Source: ``VERUM_INTEGRATION_README.md`` section D (analytic pilot).
"""

from __future__ import annotations

import collections
import json
from pathlib import Path
from typing import Any

from verum.contracts import validator

ENVELOPE = {
    "schema_version": "0.5.0",
    "dataset": "observations",
    "timestamp_utc": "2026-01-01T00:00:00Z",
}


def _rows(root: Path) -> list[dict[str, Any]]:
    path = root / "config" / "reference" / "pilot_agent_observations_ANALYTIC_ONLY.json"
    rows: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["observations"]
    return rows


def test_no_pilot_row_validates(root: Path) -> None:
    rows = _rows(root)
    assert len(rows) == 74
    assert not any(validator("observation").is_valid(r) for r in rows)


def test_every_row_fails_only_on_the_same_three_required_keys(root: Path) -> None:
    failures: collections.Counter[tuple[str, str]] = collections.Counter()
    for row in _rows(root):
        for error in validator("observation").iter_errors(row):
            failures[(str(error.validator), error.message.split("'")[1])] += 1
    assert failures == {
        ("required", "schema_version"): 74,
        ("required", "dataset"): 74,
        ("required", "timestamp_utc"): 74,
    }


def test_rows_validate_once_the_envelope_is_added(root: Path) -> None:
    assert all(validator("observation").is_valid({**r, **ENVELOPE}) for r in _rows(root))
