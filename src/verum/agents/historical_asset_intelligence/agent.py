"""Look up declared asset facts and simulated history for an investigation."""

from __future__ import annotations

from typing import Any

from verum.agents.common.envelope import (
    build_response,
    implementation_block,
    make_issue,
)
from verum.agents.common.validation import check_request, check_response

ROLE = "historical_asset_intelligence"


class HistoricalAssetIntelligenceAgent:
    """Report supplied facts and eligible history for the requested assets."""

    role = ROLE

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return exact asset matches and history recorded by the cutoff."""
        check_request(request)
        if request["agent"] != self.role:
            raise ValueError("request is addressed to a different role")

        payload = request["input"]
        cutoff_s = request["context"]["as_of_s"]
        asset_index = {asset["asset_id"]: asset for asset in payload["assets"]}
        query_ids: list[str] = payload["query_asset_ids"]
        matched_ids = [asset_id for asset_id in query_ids if asset_id in asset_index]
        matched = set(matched_ids)
        missing = [asset_id for asset_id in query_ids if asset_id not in asset_index]

        facts = [
            fact for fact in payload["declared_facts"] if fact["asset_id"] in matched
        ]
        history = [
            record
            for record in payload["history"]
            if record["asset_id"] in matched and record["t_recorded_s"] <= cutoff_s
        ]

        issues = []
        if missing:
            issues.append(
                make_issue(
                    "ASSET_NOT_FOUND",
                    f"No supplied asset record for: {', '.join(missing)}",
                )
            )
        if not query_ids:
            issues.append(make_issue("EMPTY_ASSET_QUERY", "No assets were requested."))

        if history:
            history_status = "simulated_records_available"
        elif matched:
            history_status = "no_verified_past_maintenance_supplied"
            issues.append(
                make_issue(
                    "NO_VERIFIED_PAST_MAINTENANCE",
                    "No eligible history was supplied for the matched assets.",
                )
            )
        else:
            history_status = "unknown"

        evidence_ids: list[str] = list(payload["reference_evidence_ids"])
        for fact in facts:
            evidence_ids.extend(fact["evidence_ids"])
        evidence_ids = list(dict.fromkeys(evidence_ids))

        response = build_response(
            request,
            status="degraded" if issues else "complete",
            result={
                "asset_records": [asset_index[asset_id] for asset_id in matched_ids],
                "facts": facts,
                "history": history,
                "history_status": history_status,
                "missing_asset_ids": missing,
                "evidence_ids": evidence_ids,
            },
            consumed_evidence_ids=evidence_ids,
            implementation=implementation_block(self.role, "1.0.0"),
            issues=issues,
            limitations=[
                "Declared facts do not establish measured operating conditions.",
                "Supplied history records are simulated.",
            ],
        )
        check_response(request, response)
        return response