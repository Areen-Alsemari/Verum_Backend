"""Builders for the request and response envelopes shared by all eight message contracts.

The response builder copies the request context exactly, derives the report identifier, and refuses
combinations the contract forbids: a result next to an error or insufficient-evidence status, or
such a status without an issue. Agents fill only their own result.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any, Final

from verum.agents.common.ids import report_id
from verum.agents.common.numbers import to_plain
from verum.agents.common.registry import EvidenceRegistry
from verum.agents.common.roles import require_role

INTERFACE_VERSION: Final = "1.0.0"
STATUSES: Final = ("complete", "degraded", "insufficient_evidence", "error")
RESULTLESS: Final = ("insufficient_evidence", "error")


def implementation_block(
    name: str, version: str, *, artifact_sha256: str | None = None,
    feature_profile_id: str | None = None,
) -> dict[str, Any]:
    """Describe the software that produced a report."""
    return {
        "name": name, "version": version, "artifact_sha256": artifact_sha256,
        "feature_profile_id": feature_profile_id,
    }


def make_issue(code: str, message: str, evidence_ids: Iterable[str] = ()) -> dict[str, Any]:
    """Build a structured issue."""
    return {"code": code, "message": message, "evidence_ids": list(evidence_ids)}


def attached_report_ids(request: dict[str, Any]) -> list[str]:
    """Return the identifiers of the upstream reports attached to a request, in field order."""
    return [
        value["report_id"] for key, value in request["input"].items()
        if key.endswith("_report") and value is not None
    ]


def build_request(
    role: str, request_id: str, registry: EvidenceRegistry, inputs: dict[str, Any]
) -> dict[str, Any]:
    """Assemble a request whose evidence is the registry and whose input is plain JSON."""
    return {
        "interface_version": INTERFACE_VERSION, "message_type": "request",
        "agent": require_role(role), "request_id": request_id,
        "context": copy.deepcopy(registry.context), "evidence": registry.rows(),
        "input": to_plain(inputs),
    }


def build_response(
    request: dict[str, Any], *, status: str, result: dict[str, Any] | None,
    consumed_evidence_ids: Iterable[str], implementation: dict[str, Any],
    issues: Iterable[dict[str, Any]] = (), limitations: Iterable[str] = (),
) -> dict[str, Any]:
    """Assemble a response to a request, enforcing the status rules of the contract."""
    kept_issues, consumed = list(issues), list(consumed_evidence_ids)
    _check_status(status, result, kept_issues)
    known = {row["evidence_id"] for row in request["evidence"]}
    if not set(consumed) <= known or len(set(consumed)) != len(consumed):
        raise ValueError("consumed evidence must be distinct and present in the request")
    analysis = request["context"]["analysis_id"]
    identifier = report_id(request["agent"], analysis, request["request_id"])
    if identifier in known:
        raise ValueError("report identifier collides with an evidence identifier")
    return {
        "interface_version": INTERFACE_VERSION, "message_type": "response",
        "agent": request["agent"], "request_id": request["request_id"],
        "report_id": identifier, "context": copy.deepcopy(request["context"]),
        **to_plain({
            "implementation": implementation, "status": status,
            "consumed_evidence_ids": consumed, "issues": kept_issues,
            "limitations": list(limitations), "advisory_only": True, "result": result,
        }),
    }


def _check_status(status: str, result: dict[str, Any] | None, issues: list[dict[str, Any]]) -> None:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    if status in RESULTLESS:
        if result is not None:
            raise ValueError("an error or insufficient-evidence report carries no result")
        if not issues:
            raise ValueError("an error or insufficient-evidence report needs an issue")
    elif result is None:
        raise ValueError("a complete or degraded report carries a result")
