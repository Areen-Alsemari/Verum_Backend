"""Known non-conformance of the analytic pilot observations with the observation schema.

All 74 rows of the pilot file lack the same three envelope keys and are otherwise valid, so the
failure is a missing envelope and not a content defect. The pilot file is analytic-verification data
only and is not modified here.
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
    """None of the 74 pilot rows validates against the observation schema. Independent: yes, because
    the schema is a separate file.
    """
    rows = _rows(root)
    assert len(rows) == 74
    assert not any(validator("observation").is_valid(r) for r in rows)


def test_every_row_fails_only_on_the_same_three_required_keys(root: Path) -> None:
    """Every pilot row fails only on the same three missing envelope keys. Independent: yes, because
    the errors are counted by the schema validator.
    """
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
    """Every pilot row validates once the three envelope keys are added. Independent: yes, because
    the schema is a separate file.
    """
    assert all(validator("observation").is_valid({**r, **ENVELOPE}) for r in _rows(root))
