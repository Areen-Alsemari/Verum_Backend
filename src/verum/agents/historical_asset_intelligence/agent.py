"""Look up declared asset facts and simulated history for an investigation."""

from __future__ import annotations

from collections import Counter
from typing import Any

from verum.agents.common.envelope import (
    build_response,
    implementation_block,
    make_issue,
)
from verum.agents.common.validation import check_request, check_response

ROLE = "historical_asset_intelligence"


_LIMITATIONS = (
    "Declared facts do not establish measured operating conditions.",
    "Supplied history records are simulated.",
)


def _duplicate_issues(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag repeated reference identifiers before selecting query results."""
    issues = []
    for rows, key, code in (
        (payload["assets"], "asset_id", "DUPLICATE_ASSET_ID"),
        (payload["declared_facts"], "fact_id", "DUPLICATE_FACT_ID"),
    ):
        counts = Counter(row[key] for row in rows)
        for identifier, count in sorted(counts.items()):
            if count > 1:
                issues.append(make_issue(code, f"Duplicate {key}: {identifier}"))
    return issues


def _collect_result(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Select exact asset matches and report gaps in the supplied records."""
    issues = _duplicate_issues(payload)
    asset_index = {asset["asset_id"]: asset for asset in payload["assets"]}
    query_ids: list[str] = payload["query_asset_ids"]
    matched_ids = [asset_id for asset_id in query_ids if asset_id in asset_index]
    matched = set(matched_ids)
    missing = [asset_id for asset_id in query_ids if asset_id not in asset_index]

    facts = [fact for fact in payload["declared_facts"] if fact["asset_id"] in matched]
    # Request validation already rejects history recorded after the cutoff.
    history = [record for record in payload["history"] if record["asset_id"] in matched]
    assets_with_history = {record["asset_id"] for record in history}

    if missing:
        issues.append(
            make_issue("ASSET_NOT_FOUND", f"No supplied asset record for: {', '.join(missing)}")
        )
    if not query_ids:
        issues.append(make_issue("EMPTY_ASSET_QUERY", "No assets were requested."))

    for asset_id in matched_ids:
        if asset_id not in assets_with_history:
            issues.append(
                make_issue(
                    "NO_VERIFIED_PAST_MAINTENANCE",
                    f"No eligible history was supplied for {asset_id}.",
                )
            )

    history_status = "unknown"
    if history:
        history_status = "simulated_records_available"
    elif matched:
        history_status = "no_verified_past_maintenance_supplied"

    evidence_ids: list[str] = list(payload["reference_evidence_ids"])
    for fact in facts:
        evidence_ids.extend(fact["evidence_ids"])

    return {
        "asset_records": [asset_index[asset_id] for asset_id in matched_ids],
        "facts": facts,
        "history": history,
        "history_status": history_status,
        "missing_asset_ids": missing,
        "evidence_ids": list(dict.fromkeys(evidence_ids)),
    }, issues


class HistoricalAssetIntelligenceAgent:
    """Report supplied facts and eligible history for the requested assets."""

    role = ROLE

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Validate the request and report exact matches and missing history."""
        check_request(request)
        if request["agent"] != self.role:
            raise ValueError("request is addressed to a different role")

        payload = request["input"]
        try:
            result, issues = _collect_result(payload)
        except Exception:
            response = build_response(
                request,
                status="error",
                result=None,
                consumed_evidence_ids=[],
                implementation=implementation_block(self.role, "1.0.0"),
                issues=[
                    make_issue(
                        "HISTORICAL_ASSET_LOOKUP_FAILED",
                        "The historical asset lookup could not be completed.",
                    )
                ],
                limitations=list(_LIMITATIONS),
            )
        else:
            response = build_response(
                request,
                status="degraded" if issues else "complete",
                result=result,
                consumed_evidence_ids=result["evidence_ids"],
                implementation=implementation_block(self.role, "1.0.0"),
                issues=issues,
                limitations=list(_LIMITATIONS),
            )
        check_response(request, response)
        return response
