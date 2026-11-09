"""Rule-based evidence verification and advisory decision agent.

Decision precedence (highest first): more_evidence_required when reports or
verified evidence are missing; review_required for conflicts; inconclusive
when diagnostic candidates are unsupported; assessment_available otherwise.
All decisions are advisory and require human judgment.
"""

from __future__ import annotations

from typing import Any, Final

from verum.agents.common import (
    attached_report_ids,
    build_response,
    check_request,
    check_response,
    implementation_block,
    make_issue,
)
from verum.agents.evidence_verification_decision.evidence import check_proposal

ROLE: Final = "evidence_verification_decision"
VERSION: Final = "1.0.0"

REPORT_KEYS: Final = (
    "diagnosis_report",
    "inspection_plan_report",
    "inspection_quality_report",
)


def _step(
    kind: str,
    description: str,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a human-facing, non-operational next step."""
    return {
        "kind": kind,
        "description": description,
        "evidence_ids": sorted(set(evidence_ids or [])),
    }


def _conflict(
    check_id: str,
    description: str,
    evidence_ids: list[str],
) -> dict[str, Any]:
    """Record an unresolved evidence conflict."""
    return {
        "check_id": check_id,
        "description": description,
        "outcome": "fail",
        "evidence_ids": sorted(set(evidence_ids)),
    }


def _roots(
    evidence_ids: list[str],
    registry: dict[str, dict[str, Any]],
) -> set[str]:
    """Resolve original evidence roots, not derived report identities."""
    roots: set[str] = set()
    for ident in evidence_ids:
        row = registry.get(ident)
        if row is not None:
            roots.update(row["root_evidence_ids"])
    return roots


def _quality_for_proposal(
    proposal: dict[str, Any],
    quality_report: dict[str, Any] | None,
    registry: dict[str, dict[str, Any]],
) -> tuple[bool | None, bool | None]:
    """Use only relevant, independently documented quality assessments."""
    if quality_report is None or quality_report["result"] is None:
        return None, None

    claimed = set(proposal["claimed_evidence_ids"])
    matches: list[dict[str, Any]] = []

    for record in quality_report["result"]["record_checks"]:
        record_ids = set(record["evidence_ids"])

        if claimed & record_ids:
            matches.append(record)

    if not matches:
        return None, None

    def combine(field: str) -> bool | None:
        """Preserve failure and uncertainty across matching records."""
        values = [record[field] for record in matches]
        if any(value is False for value in values):
            return False
        if all(value is True for value in values):
            return True
        return None

    return combine("measurement_usable"), combine("scope_supported")


def _diagnosis_conflicts(diagnosis: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Collect hypothesis conflicts and failed diagnostic checks."""
    conflicts: list[dict[str, Any]] = []
    if diagnosis is not None and diagnosis["result"] is not None:
        for hypothesis in diagnosis["result"]["hypotheses"]:
            if hypothesis["conflict_evidence_ids"]:
                conflicts.append(
                    _conflict(
                        "diagnosis:hypothesis:" + hypothesis["hypothesis_id"],
                        "Conflicting evidence for diagnostic hypothesis.",
                        hypothesis["conflict_evidence_ids"],
                    )
                )

        for check in diagnosis["result"]["upstream_checks"]:
            if check["outcome"] == "fail":
                conflicts.append(
                    _conflict(
                        "diagnosis:" + check["check_id"],
                        "Diagnostic upstream check failed: " + check["description"],
                        check["evidence_ids"],
                    )
                )
    return conflicts


def _plan_conflicts(plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Collect failed inspection planning preconditions."""
    conflicts: list[dict[str, Any]] = []
    if plan is not None and plan["result"] is not None:
        for option in plan["result"]["options"]:
            for check in option["precondition_checks"]:
                if check["outcome"] == "fail":
                    conflicts.append(
                        _conflict(
                            "plan:" + option["option_id"] + ":" + check["check_id"],
                            "Inspection planning precondition failed: " + check["description"],
                            check["evidence_ids"],
                        )
                    )
    return conflicts


def _quality_contradictions(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect contradictory conclusions for the same inspection result."""
    conflicts: list[dict[str, Any]] = []
    for index, first in enumerate(records):
        for second in records[index + 1 :]:
            if first["result_id"] != second["result_id"]:
                continue

            contradictory = any(
                first[field] is not None
                and second[field] is not None
                and first[field] != second[field]
                for field in ("measurement_usable", "scope_supported")
            )
            if contradictory:
                conflicts.append(
                    _conflict(
                        "quality:contradiction:" + first["result_id"],
                        "Conflicting quality conclusions for one inspection result.",
                        first["evidence_ids"] + second["evidence_ids"],
                    )
                )
    return conflicts


def _quality_conflicts(quality: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Collect failed and contradictory inspection quality checks."""
    conflicts: list[dict[str, Any]] = []
    if quality is not None and quality["result"] is not None:
        records = quality["result"]["record_checks"]

        for record in records:
            for check in record["checks"]:
                if check["outcome"] == "fail":
                    conflicts.append(
                        _conflict(
                            "quality:" + record["result_id"] + ":" + check["check_id"],
                            "Inspection quality check failed: " + check["description"],
                            check["evidence_ids"],
                        )
                    )

        conflicts.extend(_quality_contradictions(records))
    return conflicts


def _report_conflicts(
    inputs: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect explicit failed checks and contradictory quality records."""
    conflicts: list[dict[str, Any]] = []
    diagnosis = inputs["diagnosis_report"]
    plan = inputs["inspection_plan_report"]
    quality = inputs["inspection_quality_report"]

    conflicts.extend(_diagnosis_conflicts(diagnosis))

    conflicts.extend(_plan_conflicts(plan))

    conflicts.extend(_quality_conflicts(quality))

    return conflicts


def _overlap_conflicts(
    checks: list[dict[str, Any]],
    registry: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Identify proposals sharing original evidence roots."""
    conflicts: list[dict[str, Any]] = []

    for index, first in enumerate(checks):
        first_roots = _roots(first["evidence_ids"], registry)
        if not first_roots:
            continue

        for second in checks[index + 1 :]:
            shared = first_roots & _roots(second["evidence_ids"], registry)
            if shared:
                conflicts.append(
                    _conflict(
                        "shared-roots:" + first["proposal_id"] + ":" + second["proposal_id"],
                        "Evidence proposals share original evidence roots "
                        "and must not be counted as independent support.",
                        first["evidence_ids"] + second["evidence_ids"],
                    )
                )

    return conflicts


def _more_evidence_decision() -> tuple[str, str, list[dict[str, Any]]]:
    """Return the decision for unavailable or unverified evidence."""
    return (
        "more_evidence_required",
        "Required evidence or verification remains unavailable.",
        [
            _step(
                "collect_evidence",
                "Obtain and verify missing or unresolved evidence before making an assessment.",
            )
        ],
    )


def _review_decision(conflicts: list[dict[str, Any]]) -> tuple[str, str, list[dict[str, Any]]]:
    """Return the decision for conflicting evidence."""
    return (
        "review_required",
        "Evidence conflicts or shared provenance require human review.",
        [
            _step(
                "review_records",
                "Review conflicting records and overlapping evidence "
                "roots without treating them as independent support.",
                [ident for conflict in conflicts for ident in conflict["evidence_ids"]],
            )
        ],
    )


def _inconclusive_decision() -> tuple[str, str, list[dict[str, Any]]]:
    """Return the decision when diagnostic candidates are unavailable."""
    return (
        "inconclusive",
        "No supported diagnostic candidate assessment is available.",
        [
            _step(
                "human_review",
                "Review the inconclusive diagnostic assessment.",
            )
        ],
    )


def _available_decision() -> tuple[str, str, list[dict[str, Any]]]:
    """Return the decision for supported diagnostic candidates."""
    return (
        "assessment_available",
        "Supported diagnostic candidates are available for human review; "
        "equipment condition is not confirmed.",
        [
            _step(
                "human_review",
                "Review the supported diagnostic candidates and evidence "
                "before any operational decision.",
            )
        ],
    )


def _decision(
    diagnosis: dict[str, Any] | None,
    checks: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    missing_reports: list[str],
) -> tuple[str, str, list[dict[str, Any]]]:
    """Apply explicit, conservative decision precedence."""
    if missing_reports or not checks or any(check["usable"] is not True for check in checks):
        return _more_evidence_decision()

    if conflicts:
        return _review_decision(conflicts)

    if (
        diagnosis is None
        or diagnosis["result"] is None
        or diagnosis["result"]["assessment"] != "candidates_available"
        or not diagnosis["result"]["hypotheses"]
    ):
        return _inconclusive_decision()

    return _available_decision()


def _build_evidence_checks(
    inputs: dict[str, Any], registry: dict[str, dict[str, Any]], as_of_s: float
) -> list[dict[str, Any]]:
    """Verify each proposed evidence item."""
    quality_report = inputs["inspection_quality_report"]
    evidence_checks: list[dict[str, Any]] = []

    for proposal in inputs["evidence_proposals"]:
        quality, scope = _quality_for_proposal(proposal, quality_report, registry)

        evidence_checks.append(
            check_proposal(
                proposal,
                registry,
                as_of_s,
                quality_acceptable=quality,
                scope_supported=scope,
            )
        )
    return sorted(evidence_checks, key=lambda check: check["proposal_id"])


def _build_decision_result(inputs, state, summary, next_steps, evidence_checks, conflicts):
    """Assemble the advisory decision result."""
    diagnosis = inputs["diagnosis_report"]
    hypothesis_report_ids = (
        [diagnosis["report_id"]]
        if diagnosis is not None
        and diagnosis["result"] is not None
        and diagnosis["result"]["assessment"] == "candidates_available"
        else []
    )

    ids = sorted({eid for c in evidence_checks for eid in c["evidence_ids"]})
    if ids:
        summary += " Evidence IDs: " + ", ".join(ids) + "."

    result = {
        "decision_state": state,
        "summary": summary,
        "hypothesis_report_ids": hypothesis_report_ids,
        "evidence_checks": evidence_checks,
        "conflicts": conflicts,
        "next_steps": next_steps,
        "human_decision_required": True,
        "automatic_action_authorized": False,
        "equipment_condition_confirmed": False,
    }
    return result


def _consumed_ids(request, evidence_checks, conflicts):
    """Collect distinct consumed evidence identifiers."""
    consumed = sorted(
        set(attached_report_ids(request))
        | {ident for check in evidence_checks for ident in check["evidence_ids"]}
        | {ident for conflict in conflicts for ident in conflict["evidence_ids"]}
    )
    return consumed


def _build_decision_response(request, result, evidence_checks, conflicts, state, summary):
    """Build the validated decision envelope fields."""
    consumed = _consumed_ids(request, evidence_checks, conflicts)

    issues = []
    if state != "assessment_available":
        issues.append(
            make_issue(
                "EVIDENCE_DECISION_" + state.upper(),
                summary,
            )
        )

    response = build_response(
        request,
        status=("complete" if state == "assessment_available" else "degraded"),
        result=result,
        consumed_evidence_ids=consumed,
        implementation=implementation_block(ROLE + "-rules", VERSION),
        issues=issues,
        limitations=[
            "Advisory assessment only; human decision is required.",
            "Evidence identity does not establish physical truth.",
            "No equipment condition or automatic action is confirmed.",
        ],
    )
    return response


def _process_decision(request):
    """Evaluate evidence and construct the advisory response."""
    inputs = request["input"]
    context = request["context"]
    registry = {row["evidence_id"]: row for row in request["evidence"]}

    evidence_checks = _build_evidence_checks(inputs, registry, context["as_of_s"])

    conflicts = _report_conflicts(inputs, registry)
    conflicts.extend(_overlap_conflicts(evidence_checks, registry))

    missing_reports = [
        key for key in REPORT_KEYS if inputs[key] is None or inputs[key]["result"] is None
    ]

    state, summary, next_steps = _decision(
        inputs["diagnosis_report"],
        evidence_checks,
        conflicts,
        missing_reports,
    )

    result = _build_decision_result(inputs, state, summary, next_steps, evidence_checks, conflicts)

    response = _build_decision_response(
        request, result, evidence_checks, conflicts, state, result["summary"]
    )
    return response


class EvidenceVerificationDecisionAgent:
    """Verify available evidence and return a non-authoritative decision."""

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Validate inputs, apply deterministic rules, and validate output."""
        try:
            check_request(request)

            if request["agent"] != ROLE:
                raise ValueError("request is addressed to a different role")

            response = _process_decision(request)
            check_response(request, response)
            return response
        except Exception as error:
            return build_response(
                request,
                status="error",
                result=None,
                consumed_evidence_ids=[],
                implementation=implementation_block(ROLE + "-rules", VERSION),
                issues=[make_issue("EVIDENCE_DECISION_ERROR", f"{type(error).__name__}: {error}")],
            )
