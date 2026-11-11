"""Runtime implementation of the Anomaly Detection role.

The agent combines deterministic signal-quality checks with the topology residual detector
(method topology_residual_v1). The detector scores one summary window from twelve fields and
reports a window score, whether it exceeds the pinned threshold, and one event per residual that
exceeds its own threshold. It names the tags each residual reads and nothing more: no asset, no
location, no fault type. Missing or unusable inputs make a residual unknown, never zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from verum.agents.anomaly_detection import text
from verum.agents.anomaly_detection.parameters import (
    METHOD_ID,
    Parameters,
    load_parameters,
)
from verum.agents.anomaly_detection.quality import (
    build_quality_events,
    find_invalid_unit_signals,
    make_event,
)
from verum.agents.anomaly_detection.residuals import (
    COMPUTED,
    UNKNOWN,
    ResidualResult,
    compute_residuals,
    window_score,
)
from verum.agents.common import (
    attached_report_ids,
    build_response,
    check_request,
    check_response,
    implementation_block,
    make_issue,
)

ROLE = "anomaly_detection"
VERSION = "2.0.0"
FEATURE_PROFILE_ID = "topology_residual_summary_v1_12_fields"
MODEL_METHOD_ID = METHOD_ID
SCORE_DECIMALS = 6


@dataclass
class DetectorOutcome:
    """What the residual detector contributed to one response."""

    results: list[ResidualResult] = field(default_factory=list)
    params: Parameters | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    score: float | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    @property
    def computed(self) -> bool:
        """Whether at least one residual could be computed."""
        return any(r.state == COMPUTED for r in self.results)

    @property
    def complete(self) -> bool:
        """Whether every residual that applies to this window was computed."""
        return self.computed and not any(r.state == UNKNOWN for r in self.results)


def observation_evidence_ids(request: dict[str, Any]) -> list[str]:
    """Observation evidence ids that the request's evidence list also contains."""
    known = {row["evidence_id"] for row in request["evidence"]}
    listed = request["input"]["observations"]["evidence_ids"]
    return list(dict.fromkeys(evidence_id for evidence_id in listed if evidence_id in known))


def safe_consumed_ids(request: Any) -> list[str]:
    """Consumed evidence for an error response, never raising, always keeping attached reports."""
    try:
        observed = observation_evidence_ids(request)
    except Exception:  # noqa: BLE001 - the error path must not fail
        observed = []
    try:
        attached = list(attached_report_ids(request))
    except Exception:  # noqa: BLE001 - fall back to the forecast report id if it is in evidence
        attached = []
        try:
            report = request["input"].get("forecast_report")
            known = {row["evidence_id"] for row in request["evidence"]}
            if isinstance(report, dict) and report.get("report_id") in known:
                attached = [report["report_id"]]
        except Exception:  # noqa: BLE001
            attached = []
    return list(dict.fromkeys([*observed, *attached]))


def residual_events(
    request_id: str, outcome: DetectorOutcome, evidence_ids: list[str]
) -> list[dict[str, Any]]:
    """One event per computed residual above its own threshold, naming the tags it reads."""
    params, score = outcome.params, outcome.score
    assert params is not None and score is not None
    events = []
    for result in outcome.results:
        own = params.residual_thresholds[result.key]
        if result.state != COMPUTED or result.z is None or result.z <= own:
            continue
        events.append(
            make_event(
                event_id=f"{request_id}-residual-{result.key}",
                category="reported_signal_departure",
                tag_ids=list(result.reads),
                evidence_ids=evidence_ids,
                method_id=MODEL_METHOD_ID,
                score={
                    "value": round(result.z, SCORE_DECIMALS),
                    "kind": "decision_score",
                    "method_id": MODEL_METHOD_ID,
                    "calibration_id": None,
                },
                limitations=text.event_limitations(result, own, score, params),
            )
        )
    return events


def run_detector(
    request_id: str, signals: list[dict[str, Any]], evidence_ids: list[str]
) -> DetectorOutcome:
    """Apply the residual detector to one window; a failure to load is a named issue."""
    try:
        params = load_parameters()
    except Exception:  # noqa: BLE001 - any load or verification failure is a named issue
        return DetectorOutcome(
            issues=[make_issue("MODEL_UNAVAILABLE", text.MODEL_UNAVAILABLE_TEXT, evidence_ids)],
            limitations=[text.MODEL_UNAVAILABLE_TEXT],
        )
    outcome = DetectorOutcome(results=compute_residuals(signals, params), params=params)
    outcome.score = window_score(outcome.results)
    if not outcome.computed:
        outcome.issues.append(make_issue("INSUFFICIENT_EVIDENCE", _why_none(outcome), evidence_ids))
        return outcome
    outcome.events = residual_events(request_id, outcome, evidence_ids)
    if not outcome.complete:
        outcome.issues.append(
            make_issue("INSUFFICIENT_EVIDENCE", _why_partial(outcome), evidence_ids)
        )
    assert outcome.score is not None
    outcome.limitations = [
        text.window_line(outcome.score, params),
        text.computability(outcome.results),
        *text.method_limitations(params),
    ]
    return outcome


def _why_none(outcome: DetectorOutcome) -> str:
    return "No residual could be computed from this window. " + text.computability(outcome.results)


def _why_partial(outcome: DetectorOutcome) -> str:
    unknown = [r.key for r in outcome.results if r.state == UNKNOWN]
    return (
        f"{len(unknown)} of the residuals that apply to this window could not be computed and "
        "are unknown, not zero. " + text.computability(outcome.results)
    )


def status_and_coverage(
    observation_ids: list[str], outcome: DetectorOutcome, invalid_units: list[str]
) -> tuple[str, str]:
    """Only a window whose applicable residuals were all computed is complete and assessed."""
    if not observation_ids or outcome.params is None:
        return "degraded", "partial" if observation_ids else "unknown"
    if outcome.complete and not invalid_units:
        return "complete", "assessed"
    return "degraded", "partial"


def response_limitations(outcome: DetectorOutcome) -> list[str]:
    """Response-level limitations; the method text appears only when the detector ran."""
    return [
        "Forecast reports are not used as model features.",
        *outcome.limitations,
        "No detected event does not establish healthy equipment.",
    ]


class AnomalyDetectionAgent:
    """Detect reported data-quality issues and window-level topology residual departures."""

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Validate a request, analyze its observations, and validate the response.

        Any failure, including an invalid request, returns a status="error" response.
        """
        try:
            check_request(request)
        except Exception as exc:  # noqa: BLE001
            return self.error_response(
                request, f"The request failed contract validation ({type(exc).__name__})."
            )
        try:
            return self._analyze(request)
        except Exception as exc:  # noqa: BLE001
            return self.error_response(
                request,
                f"An unexpected internal error ({type(exc).__name__}) prevented anomaly analysis.",
            )

    def _analyze(self, request: dict[str, Any]) -> dict[str, Any]:
        if request["agent"] != ROLE:
            raise ValueError("request is addressed to a different role")
        observations = request["input"]["observations"]
        if observations["representation"] != "summary_v1":
            return self.error_response(
                request,
                "Anomaly detection reads summary_v1 observations; "
                f"{observations['representation']} is not supported.",
                code="UNSUPPORTED_OBSERVATION_REPRESENTATION",
            )
        signals = [s for s in observations["summary"]["signals"] if isinstance(s, dict)]
        observation_ids = observation_evidence_ids(request)
        consumed = list(dict.fromkeys([*observation_ids, *attached_report_ids(request)]))
        invalid = find_invalid_unit_signals(signals)
        outcome = run_detector(request["request_id"], signals, observation_ids)
        issues = [] if not invalid else [self._unit_issue(observation_ids)]
        issues.extend(outcome.issues)
        if outcome.params is not None and not outcome.computed:
            return self._insufficient(request, consumed, issues, outcome)
        events = [*build_quality_events(request["request_id"], signals, observation_ids)]
        events.extend(outcome.events)
        status, coverage = status_and_coverage(observation_ids, outcome, invalid)
        return self._respond(request, status, events, coverage, consumed, issues, outcome)

    @staticmethod
    def _unit_issue(evidence_ids: list[str]) -> dict[str, Any]:
        return make_issue(
            "INVALID_SIGNAL_UNIT",
            "Signals with unknown tags or unexpected units were excluded from the analysis.",
            evidence_ids,
        )

    def _respond(
        self, request: dict[str, Any], status: str, events: list[dict[str, Any]], coverage: str,
        consumed: list[str], issues: list[dict[str, Any]], outcome: DetectorOutcome,
    ) -> dict[str, Any]:  # fmt: skip
        params = outcome.params
        response = build_response(
            request,
            status=status,
            result={"events": events, "coverage": coverage, "no_event_means_healthy": False},
            consumed_evidence_ids=consumed,
            implementation=implementation_block(
                ROLE,
                VERSION,
                artifact_sha256=None if params is None else params.sha256,
                feature_profile_id=FEATURE_PROFILE_ID,
            ),
            issues=issues,
            limitations=response_limitations(outcome),
        )
        check_response(request, response)
        return dict(response)

    def _insufficient(
        self, request: dict[str, Any], consumed: list[str], issues: list[dict[str, Any]],
        outcome: DetectorOutcome,
    ) -> dict[str, Any]:  # fmt: skip
        params = outcome.params
        assert params is not None
        response = build_response(
            request,
            status="insufficient_evidence",
            result=None,
            consumed_evidence_ids=consumed,
            implementation=implementation_block(
                ROLE, VERSION, artifact_sha256=params.sha256, feature_profile_id=FEATURE_PROFILE_ID
            ),
            issues=issues,
            limitations=[
                "No residual could be computed, so no statement about the equipment is made.",
                *text.method_limitations(params),
            ],
        )
        check_response(request, response)
        return dict(response)

    def error_response(
        self, request: dict[str, Any], message: str, code: str = "INTERNAL_ERROR"
    ) -> dict[str, Any]:
        """Build a result-less response that still lists the attached report ids as consumed.

        It is validated when the request itself is valid. For an invalid request no
        response can pass validation, so it is returned as built.
        """
        consumed = safe_consumed_ids(request)
        response = build_response(
            request,
            status="error",
            result=None,
            consumed_evidence_ids=consumed,
            implementation=implementation_block(
                ROLE, VERSION, feature_profile_id=FEATURE_PROFILE_ID
            ),
            issues=[make_issue(code, message, consumed)],
            limitations=[
                "The anomaly analysis could not be completed; no conclusion about the "
                "equipment can be drawn."
            ],
        )
        try:
            check_response(request, response)
        except Exception:  # noqa: BLE001 - an invalid request cannot yield a valid response
            pass
        return dict(response)
