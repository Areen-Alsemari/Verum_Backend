"""Checks that the shared role list and the manifest workflow agree with the message schemas."""

from __future__ import annotations

import json
import re
from typing import Any

from verum.agents.common import ROLES
from verum.contracts.agent_interfaces import contract_directory


def _manifest() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (contract_directory() / "manifest.json").read_text(encoding="utf-8")
    )
    return loaded


def _upstream_roles(role: str) -> set[str]:
    """The roles whose response a role's request schema references."""
    text = (contract_directory() / f"{role}.schema.json").read_text(encoding="utf-8")
    found = set(re.findall(r"urn:verum:agents:v1:(\w+)#/\$defs/response", text))
    return found - {role}


def test_role_tuple_matches_the_manifest_order() -> None:
    """The shared role tuple lists the manifest roles in the manifest order.

    Independent: yes, because the manifest is a separate document.
    """
    assert ROLES == tuple(entry["key"] for entry in _manifest()["agents"])


def test_workflow_lists_every_role_once() -> None:
    """Every role appears in exactly one workflow stage.

    Independent: yes, because the stages are read from the manifest.
    """
    flat = [role for stage in _manifest()["workflow"] for role in stage]
    assert sorted(flat) == sorted(ROLES)


def test_no_role_runs_before_a_role_it_consumes() -> None:
    """Each stage comes after the stages of every role whose report its schema accepts.

    Independent: yes, because the dependencies are read from the schemas, not from the manifest.
    """
    stage = {role: i for i, roles in enumerate(_manifest()["workflow"]) for role in roles}
    for role in ROLES:
        for upstream in _upstream_roles(role):
            assert stage[upstream] < stage[role], (upstream, role)


def test_report_assembly_follows_the_decision_role() -> None:
    """The report assembly is a separate final operation of the quality role, after the decision.

    Independent: yes, because the manifest is a separate document.
    """
    final = _manifest()["final_operation"]
    assert final == {
        "agent": "inspection_quality_documentation", "operation": "build_report",
        "follows": "evidence_verification_decision",
    }
