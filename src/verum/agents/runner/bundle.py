"""The result of an analysis run and the cross-cutting rules the message validators do not enforce.

The validators check each message against its own request. The bundle rules check the whole set:
every report belongs to one snapshot and mode, each response consumed the reports attached to its
request, identifiers do not collide, and a later revision is a new analysis. Agent 7's report
assembly receives only a verified bundle.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from verum.agents.common import (
    EvidenceRegistry,
    analysis_id,
    attached_report_ids,
    check_request,
    check_response,
    stable_hash,
)
from verum.agents.common.stub import STUB_CODE
from verum.agents.runner.persistence import AssessmentLog
from verum.agents.runner.wiring import UPSTREAM

PLACEHOLDER_CODE = "PLACEHOLDER_AGENT"
SNAPSHOT_FIELDS = (
    "case_id", "analysis_id", "revision", "as_of_s", "reference_snapshot_sha256",
    "execution_mode",
)


class BundleError(ValueError):
    """A set of messages breaks a rule that holds across the whole analysis."""


@dataclass
class Bundle:
    """Requests sent, reports received (null for a role that failed), and what went wrong."""

    context: dict[str, Any]
    registry: EvidenceRegistry
    requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    reports: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    issues: list[dict[str, str]] = field(default_factory=list)
    notes: list[dict[str, str]] = field(default_factory=list)
    assessments: AssessmentLog = field(default_factory=AssessmentLog)


@dataclass(frozen=True)
class VerifiedBundle:
    """Validated responses with the context and evidence that bind them."""

    context: dict[str, Any]
    responses: dict[str, dict[str, Any]]
    evidence: list[dict[str, Any]]
    issues: tuple[dict[str, str], ...]


def check_same_snapshot(expected: dict[str, Any], other: dict[str, Any], what: str) -> None:
    """Raise a field-specific error unless two contexts name the same snapshot and mode."""
    for name in SNAPSHOT_FIELDS:
        if expected[name] != other[name]:
            if name == "execution_mode" and expected[name] == "runtime":
                raise BundleError(f"{what}: fixture-mode report inside a runtime request")
            raise BundleError(f"{what}: {name} differs from the analysis")


def check_exchange(request: dict[str, Any], response: dict[str, Any]) -> None:
    """Raise unless the response consumed every attached report and its identifier is unique."""
    consumed = set(response["consumed_evidence_ids"])
    for identifier in attached_report_ids(request):
        if identifier not in consumed:
            raise BundleError(f"response ignores attached upstream report {identifier}")
    if response["report_id"] in {row["evidence_id"] for row in request["evidence"]}:
        raise BundleError("report identifier collides with an evidence identifier")


def _check_request(role: str, request: dict[str, Any], context: dict[str, Any]) -> None:
    check_same_snapshot(context, request["context"], f"{role} request")
    for key, value in request["input"].items():
        if key.endswith("_report") and value is not None:
            check_same_snapshot(context, value["context"], f"{role} {key}")
    try:
        check_request(request)
    except jsonschema.ValidationError as error:
        raise BundleError(f"{role} request breaks its schema") from error
    except ValueError as error:
        raise BundleError(f"{role} request: {error}") from error


def _check_attached(
    role: str, request: dict[str, Any], reports: dict[str, dict[str, Any] | None]
) -> None:
    """Each attached report must be the report the bundle holds for its producer."""
    for key, value in request["input"].items():
        if not key.endswith("_report") or value is None:
            continue
        producer = UPSTREAM.get(role, {}).get(key)
        registered = reports.get(producer) if producer else None
        if registered is None:
            raise BundleError(f"{role} {key} has no registered report of {producer}")
        if value["report_id"] != registered["report_id"]:
            raise BundleError(f"{role} {key} is not the registered report of {producer}")
        if stable_hash(value) != stable_hash(registered):
            raise BundleError(f"{role} {key} differs from the registered report of {producer}")


def _check_report(
    role: str, request: dict[str, Any], report: dict[str, Any], registry: EvidenceRegistry
) -> None:
    try:
        check_response(request, report)
    except jsonschema.ValidationError as error:
        raise BundleError(f"{role} response breaks its schema") from error
    except ValueError as error:
        raise BundleError(f"{role} response: {error}") from error
    check_exchange(request, report)
    row = registry.row(report["report_id"])
    if row["kind"] != "agent_report" or row["content_sha256"] != stable_hash(report):
        raise BundleError(f"{role} report is not registered with its own content hash")


def _check_ids(bundle: Bundle) -> None:
    context = bundle.context
    if context["execution_mode"] == "runtime" and context["analysis_id"] != analysis_id(
        context["case_id"], context["revision"]
    ):
        raise BundleError("analysis identifier does not follow the case and revision")
    ids = [r["report_id"] for r in bundle.reports.values() if r is not None]
    if len(set(ids)) != len(ids):
        raise BundleError("two reports share one identifier")
    rows = bundle.registry.rows()
    sources = {row["evidence_id"] for row in rows if row["kind"] != "agent_report"}
    if sources & set(ids):
        raise BundleError("report identifier collides with an evidence identifier")


def check_revision(bundle: Bundle, previous: VerifiedBundle) -> None:
    old, new = previous.context, bundle.context
    if new["case_id"] != old["case_id"]:
        raise BundleError("a revision belongs to the same case")
    if new["revision"] <= old["revision"]:
        raise BundleError("revision does not increase")
    if new["analysis_id"] == old["analysis_id"]:
        raise BundleError("analysis identifier did not change with the revision")
    if new["as_of_s"] < old["as_of_s"]:
        raise BundleError("a revision cannot move the cutoff backwards")
    reused = {r["report_id"] for r in bundle.reports.values() if r} & {
        r["report_id"] for r in previous.responses.values()
    }
    if reused:
        raise BundleError("a report of an earlier revision is reused as current")


def placeholder_roles(bundle: Bundle) -> list[str]:
    """Roles served by a placeholder, from the run notes and from the reports themselves."""
    noted = {n["role"] for n in bundle.notes if n["code"] == PLACEHOLDER_CODE}
    marked = {
        role for role, report in bundle.reports.items()
        if report is not None and any(i["code"] == STUB_CODE for i in report["issues"])
    }
    return sorted(noted | marked)


def check_placeholders(bundle: Bundle) -> None:
    """Raise if any role was served by a placeholder agent."""
    roles = placeholder_roles(bundle)
    if roles:
        raise BundleError(f"placeholder agents serve: {', '.join(roles)}")


def verify_bundle(
    bundle: Bundle, previous: VerifiedBundle | None = None, *, allow_placeholders: bool = True
) -> VerifiedBundle:
    """Check every message and every cross-cutting rule, and return the verified bundle.

    Placeholder agents are accepted unless allow_placeholders is false.
    """
    _check_ids(bundle)
    for role, request in bundle.requests.items():
        _check_request(role, request, bundle.context)
        _check_attached(role, request, bundle.reports)
    for role, report in bundle.reports.items():
        if report is None:
            continue
        if role not in bundle.requests:
            raise BundleError(f"{role} report has no request")
        check_same_snapshot(bundle.context, report["context"], f"{role} response")
        _check_report(role, bundle.requests[role], report, bundle.registry)
    if previous is not None:
        check_revision(bundle, previous)
    if not allow_placeholders:
        check_placeholders(bundle)
    return VerifiedBundle(
        context=copy.deepcopy(bundle.context),
        responses={r: copy.deepcopy(v) for r, v in bundle.reports.items() if v is not None},
        evidence=bundle.registry.rows(),
        issues=tuple(bundle.issues),
    )
