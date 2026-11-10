"""Runtime implementation of the Inspection Planning role."""

from __future__ import annotations

from typing import Any

from verum.agents.common import (
    attached_report_ids,
    build_response,
    check_request,
    check_response,
    implementation_block,
    make_issue,
)

ROLE = "inspection_planning"
VERSION = "1.0.0"
NO_DISPATCH = "No inspection dispatch or operational action is authorized."


def _hypotheses_for_target(
    diagnosis: dict[str, Any] | None,
    target_asset: str,
) -> list[str]:
    """Return hypotheses explicitly associated with the target asset."""
    if diagnosis is None or diagnosis.get("result") is None:
        return []
    return [
        hypothesis["hypothesis_id"]
        for hypothesis in diagnosis["result"].get("hypotheses", [])
        if any(component["asset_id"] == target_asset for component in hypothesis["components"])
    ]


def _within_budget(action: dict[str, Any], budget: dict[str, Any]) -> bool:
    """Check whether the action fits the supplied budget."""
    max_cost = budget["max_cost_usd"]
    max_duration = budget["max_duration_min"]
    return (max_cost is None or action["cost_usd"] <= max_cost) and (
        max_duration is None or action["duration_min"] <= max_duration
    )


def _report_ids(request: Any) -> list[str]:
    """Attached report ids, read again from the evidence if the shared helper fails."""
    try:
        return sorted(attached_report_ids(request))
    except Exception:  # noqa: BLE001
        try:
            return sorted(
                row["evidence_id"]
                for row in request["evidence"]
                if row.get("kind") == "agent_report"
            )
        except Exception:  # noqa: BLE001
            return []


def _duplicate_action_ids(catalog: list[dict[str, Any]]) -> list[str]:
    """Action ids that appear more than once in the catalogue."""
    seen: set[str] = set()
    repeated: set[str] = set()
    for action in catalog:
        (repeated if action["action_id"] in seen else seen).add(action["action_id"])
    return sorted(repeated)


class InspectionPlanningAgent:
    """Generate evidence-backed inspection options without dispatch authority."""

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Plan inspection options, or return a validated error when planning cannot finish."""
        try:
            check_request(request)
        except Exception:  # noqa: BLE001
            return self._error(
                request, "INVALID_REQUEST", "The request failed validation.", validate=False
            )
        try:
            if request["agent"] != ROLE:
                return self._error(request, "WRONG_ROLE", "The request is for another role.")
            repeated = _duplicate_action_ids(request["input"]["catalog"])
            if repeated:
                return self._error(
                    request,
                    "DUPLICATE_ACTION_ID",
                    "The catalogue repeats action ids: " + ", ".join(repeated) + ".",
                )
            return self._plan(request)
        except Exception as exc:  # noqa: BLE001
            return self._error(
                request, "INTERNAL_ERROR", f"Inspection planning failed ({type(exc).__name__})."
            )

    def _plan(self, request: dict[str, Any]) -> dict[str, Any]:
        """Generate inspection options for a validated request."""
        inputs = request["input"]
        assets = {asset["asset_id"]: asset["kind"] for asset in inputs["assets"]}
        diagnosis = inputs.get("diagnosis_report")
        budget = inputs["budget"]

        options: list[dict[str, Any]] = []
        consumed = set(attached_report_ids(request))

        for action in inputs["catalog"]:
            for target_asset in inputs["target_asset_ids"]:
                if assets.get(target_asset) != action["target_kind"]:
                    continue
                checks, feasibility = evaluate_action(action, request, target_asset)
                evidence_ids = sorted(
                    {evidence_id for check in checks for evidence_id in check["evidence_ids"]}
                )
                consumed.update(evidence_ids)
                option_limitations: list[str] = []
                if not _within_budget(action, budget):
                    feasibility = "blocked"
                    option_limitations.append("Action exceeds the supplied inspection budget.")
                if feasibility == "unknown":
                    option_limitations.append(
                        "One or more preconditions lack sufficient scoped evidence."
                    )
                options.append(
                    {
                        "option_id": f"{action['action_id']}-{target_asset}",
                        "action_id": action["action_id"],
                        "target_asset": target_asset,
                        "addresses_hypothesis_ids": _hypotheses_for_target(diagnosis, target_asset),
                        "feasibility": feasibility,
                        "precondition_checks": checks,
                        "cost_usd": action["cost_usd"],
                        "duration_min": action["duration_min"],
                        "expected_information_gain_bits": None,
                        "information_gain_method_id": None,
                        "limitations": option_limitations,
                        "evidence_ids": evidence_ids,
                    }
                )

        if not options:
            return self._insufficient(
                request,
                "NO_COMPATIBLE_INSPECTION_OPTIONS",
                "No catalog action matches the requested target assets.",
            )

        has_unknown = any(option["feasibility"] == "unknown" for option in options)
        limitations: list[str] = []
        if has_unknown:
            limitations.append(
                "Some inspection preconditions remain unknown because "
                "the supplied evidence does not establish their target scope."
            )
        limitations.append(
            "Options are advisory only. Human approval and operational "
            "precondition verification remain mandatory."
        )
        issues = (
            [
                make_issue(
                    "INSPECTION_PRECONDITIONS_UNKNOWN",
                    "Some inspection options cannot be established as eligible.",
                )
            ]
            if has_unknown
            else []
        )
        response = build_response(
            request,
            status="degraded" if has_unknown else "complete",
            result={
                "options": options,
                "selection_policy_id": None,
                "recommended_option_id": None,
                "dispatch_authorized": False,
            },
            consumed_evidence_ids=sorted(consumed),
            implementation=implementation_block("inspection-planning", VERSION),
            issues=issues,
            limitations=limitations,
        )
        check_response(request, response)
        return response

    def _insufficient(self, request: dict[str, Any], code: str, message: str) -> dict[str, Any]:
        """Return a contract-valid resultless response."""
        response = build_response(
            request,
            status="insufficient_evidence",
            result=None,
            consumed_evidence_ids=attached_report_ids(request),
            implementation=implementation_block("inspection-planning", VERSION),
            issues=[make_issue(code, message)],
            limitations=[NO_DISPATCH],
        )
        check_response(request, response)
        return response

    def _error(
        self, request: dict[str, Any], code: str, message: str, *, validate: bool = True
    ) -> dict[str, Any]:
        """Return an error response that still lists the attached report ids."""
        response = build_response(
            request,
            status="error",
            result=None,
            consumed_evidence_ids=_report_ids(request),
            implementation=implementation_block("inspection-planning", VERSION),
            issues=[make_issue(code, message)],
            limitations=[NO_DISPATCH],
        )
        if validate:
            check_response(request, response)
        return response


def evaluate_action(
    action: dict[str, Any],
    request: dict[str, Any],
    target_asset: str,
) -> tuple[list[dict[str, Any]], str]:
    """Evaluate one action using the evidence-backed precondition evaluator."""
    from verum.agents.inspection_planning.preconditions import evaluate_preconditions

    return evaluate_preconditions(action, request, target_asset)
