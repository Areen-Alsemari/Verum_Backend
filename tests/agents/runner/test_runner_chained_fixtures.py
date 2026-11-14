"""Checks of the committed chained fixtures: valid messages that carry real upstream reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from verum.agents.common import ROLES, check_request, check_response, stable_hash
from verum.agents.runner.wiring import UPSTREAM, workflow_stages

FOLDER = Path(__file__).resolve().parents[1] / "fixtures" / "chained"


def _load(name: str) -> Any:
    return json.loads((FOLDER / name).read_text(encoding="utf-8"))


def test_the_index_lists_every_role_in_manifest_order() -> None:
    """The index names the roles in the manifest order and a runtime context.

    Independent: yes, because the order is read from the manifest.
    """
    index = _load("index.json")
    assert index["order"] == [role for stage in workflow_stages() for role in stage]
    assert set(index["order"]) == set(ROLES)
    assert index["context"]["execution_mode"] == "runtime"


@pytest.mark.parametrize("role", ROLES)
def test_each_fixture_pair_passes_the_contract(role: str) -> None:
    """Every stored request and response pair validates.

    Independent: yes, because the contract validators are separate from the fixtures.
    """
    request, response = _load(f"{role}.request.json"), _load(f"{role}.response.json")
    check_request(request)
    check_response(request, response)
    assert response["report_id"] == _load("index.json")["report_ids"][role]


@pytest.mark.parametrize("role", sorted(UPSTREAM))
def test_upstream_reports_in_the_fixtures_are_the_stored_responses(role: str) -> None:
    """Each attached report equals the stored response of its producer and is hash-bound.

    Independent: yes, because the registry hash is recomputed.
    """
    request = _load(f"{role}.request.json")
    rows = {row["evidence_id"]: row for row in request["evidence"]}
    for field, producer in UPSTREAM[role].items():
        report = request["input"][field]
        assert report == _load(f"{producer}.response.json")
        assert rows[report["report_id"]]["content_sha256"] == stable_hash(report)
