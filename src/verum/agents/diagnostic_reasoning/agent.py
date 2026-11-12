"""Agent class of the Diagnostic Reasoning role combining observation models and evidence rules.

The agent produces candidate fault hypotheses from the observation summary and compares them with
available upstream reports. It never forces a single root cause or claims field qualification.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Final

from verum.agents.common import (
    attached_report_ids,
    build_response,
    check_request,
    check_response,
    implementation_block,
    make_issue,
    report_id,
)
from verum.agents.diagnostic_reasoning.evidence_update import update_scores
from verum.agents.diagnostic_reasoning.features import FEATURE_PROFILE_ID
from verum.agents.diagnostic_reasoning.model import DiagnosticModel, format_hypotheses
from verum.agents.diagnostic_reasoning.rules import (
    build_default_limitations,
    enrich_hypothesis_with_rules,
    evaluate_upstream_checks,
)

ROLE: Final = "diagnostic_reasoning"
IMPL_NAME: Final = "diagnostic_reasoning_ovr_hgb"
IMPL_VERSION: Final = "1.0.0"

DEFAULT_LIMITATIONS: Final[tuple[str, ...]] = build_default_limitations()


def _consumed_ids(request: dict[str, Any]) -> list[str]:
    """Collect consumed evidence identifiers in a stable order without duplicates."""
    known = {row["evidence_id"]: row for row in request["evidence"]}
    obs_ids = list((request["input"].get("observations") or {}).get("evidence_ids", []))
    roots: list[str] = []
    for eid in obs_ids:
        if eid in known:
            for r in known[eid].get("root_evidence_ids", []):
                if r in known and r not in roots:
                    roots.append(r)
    for r in ("source-observations", "source-reference"):
        if r in known and r not in roots:
            roots.append(r)
    ordered: list[str] = []
    for item in [*roots, *obs_ids, *attached_report_ids(request)]:
        if item in known and item not in ordered:
            ordered.append(item)
    return ordered


class DiagnosticReasoningAgent:
    """Observation-based fault classifier and upstream evidence comparator for Agent 5."""

    def __init__(
        self, artifact_path: Path | None = None, expected_sha256: str | None = None
    ) -> None:
        self.role = ROLE
        self.artifact_path = artifact_path
        self.expected_sha256 = expected_sha256
        self._model: DiagnosticModel | None = None
        self._init_error: str | None = None
        try:
            self._model = DiagnosticModel(artifact_path, expected_sha256)
        except Exception as error:
            self._init_error = f"{type(error).__name__}: {error}"

    def _implementation(self) -> dict[str, Any]:
        sha = self._model.sha256 if self._model is not None else None
        return implementation_block(
            IMPL_NAME,
            IMPL_VERSION,
            artifact_sha256=sha,
            feature_profile_id=FEATURE_PROFILE_ID,
        )

    def _error_response(self, request: dict[str, Any], code: str, message: str) -> dict[str, Any]:
        """Build a valid error response, guarding against helper failures so run() never raises."""
        try:
            consumed = _consumed_ids(request)
        except Exception:
            consumed = []
        try:
            issue = make_issue(code, message)
        except Exception:
            issue = {"code": code, "message": message, "evidence_ids": []}
        try:
            response = build_response(
                request,
                status="error",
                result=None,
                consumed_evidence_ids=consumed,
                implementation=self._implementation(),
                issues=[issue],
                limitations=list(DEFAULT_LIMITATIONS),
            )
            check_response(request, response)
            return response
        except Exception:
            analysis = request["context"]["analysis_id"]
            return {
                "interface_version": request.get("interface_version", "1.0.0"),
                "message_type": "response",
                "agent": request["agent"],
                "request_id": request["request_id"],
                "report_id": report_id(request["agent"], analysis, request["request_id"]),
                "context": copy.deepcopy(request["context"]),
                "implementation": self._implementation(),
                "status": "error",
                "consumed_evidence_ids": consumed,
                "issues": [issue],
                "limitations": list(DEFAULT_LIMITATIONS),
                "advisory_only": True,
                "result": None,
            }

    def _execute(
        self, request: dict[str, Any], consumed: list[str]
    ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        """Run model inference and upstream comparison rules, returning status, result, issues."""
        if self._init_error is not None or self._model is None:
            raise RuntimeError(self._init_error or "DiagnosticModel failed to initialize")
        inputs = request["input"]
        observations = inputs["observations"]
        predictions = self._model.predict_candidates(observations)
        obs_ev_ids = [eid for eid in observations.get("evidence_ids", []) if eid in set(consumed)]
        raw_hypotheses = format_hypotheses(predictions)
        hypotheses = [enrich_hypothesis_with_rules(h, inputs, obs_ev_ids) for h in raw_hypotheses]
        hypotheses = update_scores(hypotheses, inputs.get("anomaly_report"))
        upstream_checks = evaluate_upstream_checks(inputs, hypotheses)
        missing_upstreams = [c["check_id"] for c in upstream_checks if c["outcome"] == "unknown"]
        issues: list[dict[str, Any]] = []
        status = "complete"
        if self._model.artifact is None:
            status = "degraded"
            issues.append(
                make_issue(
                    "MODEL_ARTIFACT_MISSING",
                    "Saved model artifact is missing; predictions use heuristic rules only.",
                )
            )
        if missing_upstreams:
            status = "degraded"
            issues.append(
                make_issue(
                    "UPSTREAM_EVIDENCE_INCOMPLETE",
                    f"Upstream checks unknown or unavailable: {', '.join(missing_upstreams)}",
                )
            )
        result: dict[str, Any] = {
            "hypotheses": hypotheses,
            "assessment": "candidates_available" if hypotheses else "inconclusive",
            "upstream_checks": upstream_checks,
            "field_diagnosis_qualified": False,
            "ranking_basis": "decision_score_descending" if hypotheses else None,
        }
        return status, result, issues

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Validate the request, infer candidate hypotheses, compare upstream reports and return."""
        check_request(request)
        if request.get("agent") != self.role:
            raise ValueError("request is addressed to a different role")

        try:
            observations = request["input"].get("observations")
            if observations is None or observations.get("representation") != "summary_v1":
                issue = make_issue(
                    "UNSUPPORTED_OBSERVATION_REPRESENTATION",
                    "Diagnostic Reasoning v1 requires summary_v1 observations.",
                )
                response = build_response(
                    request,
                    status="insufficient_evidence",
                    result=None,
                    consumed_evidence_ids=attached_report_ids(request),
                    implementation=self._implementation(),
                    issues=[issue],
                    limitations=list(DEFAULT_LIMITATIONS),
                )
                check_response(request, response)
                return response

            consumed = _consumed_ids(request)
            status, result, issues = self._execute(request, consumed)
            response = build_response(
                request,
                status=status,
                result=result,
                consumed_evidence_ids=consumed,
                implementation=self._implementation(),
                issues=issues,
                limitations=list(DEFAULT_LIMITATIONS),
            )
            check_response(request, response)
            return response
        except Exception as error:
            return self._error_response(
                request, "DIAGNOSTIC_EXECUTION_ERROR", f"Execution failed: {error}"
            )
