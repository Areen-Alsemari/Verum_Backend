"""Convert historical asset role-view input into an agent request payload."""

from __future__ import annotations

from typing import Any

from verum.agents.historical_asset_intelligence.reference_facts import reference_facts


def build_historical_asset_input(
    role_input: dict[str, Any], *, reference_evidence_id: str
) -> dict[str, Any]:
    """Map a role-view input to the historical asset request payload."""
    reference = role_input["reference"]
    history = reference.get("history")
    return {
        "query_asset_ids": [role_input["query"]["asset_id"]],
        "assets": reference["assets"],
        "declared_facts": reference_facts(reference, reference_evidence_id),
        "history": [] if history is None else history,
        "reference_evidence_ids": [reference_evidence_id],
    }
