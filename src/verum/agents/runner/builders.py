"""One small request builder per role, reading a prepared snapshot and the reports so far.

Each builder returns the role's input object. Where the reference or the snapshot lacks something,
the builder uses the contract's null or empty value and records a note instead of inventing it.
The default topology query keeps only the assets the declared graph can resolve, in reference
order, and notes the rest; a query the caller names is passed on as given.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from verum.agents.common import to_plain
from verum.agents.runner.prepare import REFERENCE, Prepared, note

Reports = dict[str, dict[str, Any] | None]
Builder = Callable[[Prepared, Reports], dict[str, Any]]


def predictive_health(prep: Prepared, reports: Reports) -> dict[str, Any]:
    """Forecast every numeric reference instrument over the fixed horizon."""
    if not prep.forecast_tags:
        note(prep, "predictive_health", "NO_FORECAST_TARGETS",
             "The reference lists no numeric instrument, so no channel is requested.")
    return {
        "observations": prep.observations, "target_tag_ids": prep.forecast_tags,
        "forecast_horizon_s": 300.0,
    }


def anomaly_detection(prep: Prepared, reports: Reports) -> dict[str, Any]:
    """Observations with the forecast report when Agent 1 produced one."""
    return {"observations": prep.observations, "forecast_report": reports["predictive_health"]}


def _resolvable_in_graph(asset_id: str, connections: list[dict[str, Any]]) -> bool:
    """Whether the graph names the asset as an edge, a node, or the owner of a port node."""
    if any(edge["edge_id"] == asset_id for edge in connections):
        return True
    nodes = {node for edge in connections for node in (edge["from_node"], edge["to_node"])}
    return any(node == asset_id or node.startswith(f"{asset_id}:") for node in nodes)


def _topology_query(prep: Prepared) -> list[str]:
    """The assets to ask Agent 3 about: those the declared graph can resolve, in input order."""
    if not prep.connections or prep.snapshot.query_asset_ids is not None:
        return prep.query_assets
    kept = [a for a in prep.query_assets if _resolvable_in_graph(a, prep.connections)]
    skipped = [a for a in prep.query_assets if a not in set(kept)]
    if skipped:
        note(prep, "topology_dependency", "ASSETS_NOT_IN_DECLARED_GRAPH",
             f"Not queried because the declared graph does not name them: {', '.join(skipped)}.")
    return kept


def topology_dependency(prep: Prepared, reports: Reports) -> dict[str, Any]:
    """The declared graph of the reference and the queried assets."""
    if not prep.connections:
        note(prep, "topology_dependency", "NO_DECLARED_CONNECTIONS",
             "The reference declares no connections.")
    return {
        "query_asset_ids": _topology_query(prep), "direction": prep.snapshot.direction,
        "declared_connections": prep.connections, "reference_evidence_ids": [REFERENCE],
        "observations": prep.observations,
    }


def historical_asset_intelligence(prep: Prepared, reports: Reports) -> dict[str, Any]:
    """Assets and declared facts from the reference, and only the history that was supplied."""
    missing = sum(fact["unit"] is None for fact in prep.facts)
    if missing:
        note(prep, "historical_asset_intelligence", "UNIT_NOT_DECLARED",
             f"{missing} declared facts have no unit in the reference and carry a null unit.")
    if not prep.snapshot.history:
        note(prep, "historical_asset_intelligence", "NO_HISTORY_SUPPLIED",
             "No maintenance history was supplied, so the history is empty.")
    return {
        "query_asset_ids": prep.query_assets, "assets": prep.assets,
        "declared_facts": prep.facts, "history": to_plain(list(prep.snapshot.history)),
        "reference_evidence_ids": [REFERENCE],
    }


def diagnostic_reasoning(prep: Prepared, reports: Reports) -> dict[str, Any]:
    """Observations and whichever upstream reports exist."""
    return {
        "observations": prep.observations,
        "forecast_report": reports["predictive_health"],
        "anomaly_report": reports["anomaly_detection"],
        "topology_report": reports["topology_dependency"],
        "asset_report": reports["historical_asset_intelligence"],
        "inspection_quality_report": reports["inspection_quality_documentation"],
    }


def inspection_planning(prep: Prepared, reports: Reports) -> dict[str, Any]:
    """The reference catalogue, with constraints and budget only as supplied."""
    snapshot = prep.snapshot
    if not prep.catalog:
        note(prep, "inspection_planning", "NO_CATALOG",
             "The reference holds no inspection catalogue.")
    if not snapshot.constraint_checks:
        note(prep, "inspection_planning", "NO_CONSTRAINT_CHECKS",
             "No constraint checks were supplied, so the list is empty.")
    if snapshot.budget is None:
        note(prep, "inspection_planning", "NO_BUDGET",
             "No budget was supplied, so both limits are null.")
    budget = snapshot.budget or {"max_cost_usd": None, "max_duration_min": None}
    return {
        "diagnosis_report": reports["diagnostic_reasoning"], "catalog": prep.catalog,
        "catalog_evidence_ids": [REFERENCE], "observations": prep.observations,
        "constraint_checks": to_plain(list(snapshot.constraint_checks)), "budget": budget,
        "target_asset_ids": prep.query_assets, "assets": prep.assets,
        "workflow_requests": to_plain(list(snapshot.inspection_requests)),
    }


def inspection_quality_documentation(prep: Prepared, reports: Reports) -> dict[str, Any]:
    """Supplied inspection results, requests and coverage; empty when none exist."""
    snapshot = prep.snapshot
    if not snapshot.inspection_results:
        note(prep, "inspection_quality_documentation", "NO_INSPECTION_RESULTS",
             "No performed inspection result was supplied, so there is nothing to check.")
    return {
        "inspection_results": to_plain(list(snapshot.inspection_results)),
        "result_evidence_ids": prep.result_ids, "catalog": prep.catalog,
        "catalog_evidence_ids": [REFERENCE],
        "process_coverage": to_plain(list(snapshot.process_coverage)),
        "observations": prep.observations,
        "inspection_requests": to_plain(list(snapshot.inspection_requests)),
    }


def evidence_verification_decision(prep: Prepared, reports: Reports) -> dict[str, Any]:
    """The diagnosis, plan and quality reports, and only the proposals that were supplied."""
    if not prep.snapshot.evidence_proposals:
        note(prep, "evidence_verification_decision", "NO_EVIDENCE_PROPOSALS",
             "No evidence proposal was supplied, so none is assessed.")
    return {
        "diagnosis_report": reports["diagnostic_reasoning"],
        "inspection_plan_report": reports["inspection_planning"],
        "inspection_quality_report": reports["inspection_quality_documentation"],
        "evidence_proposals": to_plain(list(prep.snapshot.evidence_proposals)),
    }


BUILDERS: dict[str, Builder] = {
    "predictive_health": predictive_health,
    "anomaly_detection": anomaly_detection,
    "topology_dependency": topology_dependency,
    "historical_asset_intelligence": historical_asset_intelligence,
    "diagnostic_reasoning": diagnostic_reasoning,
    "inspection_planning": inspection_planning,
    "inspection_quality_documentation": inspection_quality_documentation,
    "evidence_verification_decision": evidence_verification_decision,
}
