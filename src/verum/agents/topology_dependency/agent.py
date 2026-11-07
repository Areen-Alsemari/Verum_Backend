"""Query the declared topology supplied with an investigation request.

The agent reports structural reachability without confirming physical routing.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from verum.agents.common.envelope import (
    attached_report_ids,
    build_response,
    implementation_block,
    make_issue,
)
from verum.agents.common.validation import check_request, check_response

ROLE = "topology_dependency"


def build_topology_input(
    role_input: dict[str, Any],
    *,
    direction: str,
    reference_evidence_ids: list[str],
) -> dict[str, Any]:
    """Build the topology input from a prepared role record."""
    return {
        "query_asset_ids": [role_input["query"]["asset_id"]],
        "direction": direction,
        "declared_connections": role_input["reference"]["connections"],
        "reference_evidence_ids": reference_evidence_ids,
        "observations": None,
    }


def _reachable(adjacency: dict[str, set[str]], starts: set[str]) -> set[str]:
    visited = set(starts)
    pending = deque(starts)
    while pending:
        node = pending.popleft()
        for neighbour in adjacency.get(node, set()):
            if neighbour not in visited:
                visited.add(neighbour)
                pending.append(neighbour)
    return visited - starts


def _query_graph(
    payload: dict[str, Any],
) -> tuple[list[dict[str, str]], list[str], list[str]]:
    edges: list[dict[str, str]] = payload["declared_connections"]
    queries: list[str] = payload["query_asset_ids"]
    forward: dict[str, set[str]] = {}
    reverse: dict[str, set[str]] = {}
    nodes: set[str] = set()

    for edge in edges:
        source, target = edge["from_node"], edge["to_node"]
        forward.setdefault(source, set()).add(target)
        reverse.setdefault(target, set()).add(source)
        nodes.update((source, target))

    starts: set[str] = set()
    missing: list[str] = []
    for asset in queries:
        # An asset can be represented by named ports in the declared graph.
        matches = {node for node in nodes if node == asset or node.startswith(f"{asset}:")}
        if matches:
            starts.update(matches)
        else:
            missing.append(asset)

    direction = payload["direction"]
    downstream = direction in {"downstream", "both"}
    upstream = direction in {"upstream", "both"}
    reachable: set[str] = set()
    if downstream:
        reachable.update(_reachable(forward, starts))
    if upstream:
        reachable.update(_reachable(reverse, starts))

    # Keep original edges and collapse only identical repeated rows.
    direct = {
        (edge["edge_id"], edge["from_node"], edge["to_node"]): edge
        for edge in edges
        if (downstream and edge["from_node"] in starts)
        or (upstream and edge["to_node"] in starts)
    }
    return [direct[key] for key in sorted(direct)], sorted(reachable), sorted(missing)


class TopologyDependencyAgent:
    """Report direct connections and reachable nodes for a topology query."""

    role = ROLE

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Validate the request and return a source-linked topology report."""
        check_request(request)
        if request["agent"] != self.role:
            raise ValueError("request is addressed to a different role")

        payload = request["input"]
        direct, reachable, missing = _query_graph(payload)
        queries = payload["query_asset_ids"]
        evidence_ids: list[str] = payload["reference_evidence_ids"]
        issues = []
        if missing:
            issues.append(
                make_issue(
                    "ASSET_NOT_IN_DECLARED_GRAPH",
                    f"No declared graph endpoint for: {', '.join(missing)}",
                )
            )
        if not queries:
            issues.append(make_issue("EMPTY_TOPOLOGY_QUERY", "No assets were requested."))

        response = build_response(
            request,
            status="degraded" if issues else "complete",
            result={
                "direct_connections": direct,
                "reachable_nodes": reachable,
                "routing_assessment": "declared_only" if len(queries) > len(missing) else "unknown",
                "actual_routing_confirmed": False,
                "evidence_ids": evidence_ids,
            },
            consumed_evidence_ids=list(dict.fromkeys(evidence_ids + attached_report_ids(request))),
            implementation=implementation_block(self.role, "1.0.0"),
            issues=issues,
            limitations=["Declared connectivity does not establish actual flow or valve position."],
        )
        check_response(request, response)
        return response