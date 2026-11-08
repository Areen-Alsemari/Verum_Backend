"""Query the declared facility topology without confirming physical routing."""

from __future__ import annotations

from collections import deque
from typing import Any

from verum.agents.common.envelope import (
    build_response,
    implementation_block,
    make_issue,
)
from verum.agents.common.validation import check_request, check_response

ROLE = "topology_dependency"
Edge = dict[str, str]


def build_topology_input(
    role_input: dict[str, Any],
    *,
    reference_evidence_ids: list[str],
    direction: str = "both",
) -> dict[str, Any]:
    """Adapt a prepared record; its reference targets are direction-agnostic."""
    return {
        "query_asset_ids": [role_input["query"]["asset_id"]],
        "direction": direction,
        "declared_connections": [
            dict(edge) for edge in role_input["reference"]["connections"]
        ],
        "reference_evidence_ids": list(reference_evidence_ids),
        "observations": None,
    }


def _reachable(adjacency: dict[str, set[str]], starts: set[str]) -> set[str]:
    """Record each reached endpoint, even when it was also a starting node."""
    expanded = set(starts)
    pending = deque(starts)
    reached: set[str] = set()
    while pending:
        node = pending.popleft()
        for neighbour in adjacency.get(node, ()):
            reached.add(neighbour)
            if neighbour not in expanded:
                expanded.add(neighbour)
                pending.append(neighbour)
    return reached


class _ReachabilityCheckError(ValueError):
    """Signal a mismatch between traversal and the declared paths."""


def _check_reachability(
    arcs: list[tuple[str, str]],
    starts: set[str],
    edge_endpoints: set[str],
    reached: set[str],
) -> None:
    """Verify the result independently by scanning declared arcs to closure."""
    supported = set(edge_endpoints)
    while True:
        sources = starts | supported
        next_supported = supported | {
            target for source, target in arcs if source in sources
        }
        if next_supported == supported:
            break
        supported = next_supported

    if reached != supported:
        raise _ReachabilityCheckError(
            "Reachable nodes do not match the declared directional paths"
        )


def _query_graph(
    payload: dict[str, Any],
) -> tuple[list[Edge], list[str], list[str], list[str]]:
    edges: list[Edge] = payload["declared_connections"]
    queries = set(payload["query_asset_ids"])
    forward: dict[str, set[str]] = {}
    reverse: dict[str, set[str]] = {}
    nodes: set[str] = set()
    endpoints_by_id: dict[str, set[tuple[str, str]]] = {}

    for edge in edges:
        source, target = edge["from_node"], edge["to_node"]
        forward.setdefault(source, set()).add(target)
        reverse.setdefault(target, set()).add(source)
        endpoints_by_id.setdefault(edge["edge_id"], set()).add((source, target))
        nodes.update((source, target))

    starts: set[str] = set()
    missing: list[str] = []
    for asset in queries:
        matches = {node for node in nodes if node == asset or node.startswith(f"{asset}:")}
        starts.update(matches)
        if not matches and asset not in endpoints_by_id:
            missing.append(asset)

    queried_edges = [edge for edge in edges if edge["edge_id"] in queries]
    direction = payload["direction"]
    downstream = direction in {"downstream", "both"}
    upstream = direction in {"upstream", "both"}
    reachable: set[str] = set()

    if downstream:
        endpoints = {edge["to_node"] for edge in queried_edges}
        reached = endpoints | _reachable(forward, starts | endpoints)
        arcs = [(edge["from_node"], edge["to_node"]) for edge in edges]
        _check_reachability(arcs, starts, endpoints, reached)
        reachable.update(reached)

    if upstream:
        endpoints = {edge["from_node"] for edge in queried_edges}
        reached = endpoints | _reachable(reverse, starts | endpoints)
        arcs = [(edge["to_node"], edge["from_node"]) for edge in edges]
        _check_reachability(arcs, starts, endpoints, reached)
        reachable.update(reached)

    direct = {
        (edge["edge_id"], edge["from_node"], edge["to_node"]): edge
        for edge in edges
        if edge["edge_id"] in queries
        or (downstream and edge["from_node"] in starts)
        or (upstream and edge["to_node"] in starts)
    }
    conflicts = sorted(
        edge_id for edge_id, endpoints in endpoints_by_id.items() if len(endpoints) > 1
    )
    return [direct[key] for key in sorted(direct)], sorted(reachable), sorted(missing), conflicts


class TopologyDependencyAgent:
    """Report connections and nodes reachable through at least one edge.
    An asset X matches X and X:<port>; other identifiers match exactly.
    An edge query includes the edge and starts at its directional endpoint.
    """

    role = ROLE

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Follow from_node to to_node downstream and reverse it upstream.
        The caller sets direction; the adapter defaults to both. Observations are ignored.
        Routing is declared_only if any query resolves, and unknown otherwise.
        """
        check_request(request)
        if request["agent"] != self.role:
            raise ValueError("request is addressed to a different role")

        payload = request["input"]
        evidence_ids: list[str] = payload["reference_evidence_ids"]
        limitations = [
            "Declared connectivity does not establish actual flow or valve position.",
            "Observations are not used; asset IDs also match their declared ports.",
        ]
        try:
            direct, reachable, missing, conflicts = _query_graph(payload)
        except _ReachabilityCheckError as exc:
            response = build_response(
                request,
                status="error",
                result=None,
                consumed_evidence_ids=list(dict.fromkeys(evidence_ids)),
                implementation=implementation_block(self.role, "1.0.0"),
                issues=[make_issue("TOPOLOGY_REACHABILITY_CHECK_FAILED", str(exc))],
                limitations=limitations,
            )
            check_response(request, response)
            return response

        queries = set(payload["query_asset_ids"])
        issues = []
        if missing:
            issues.append(
                make_issue(
                    "ASSET_NOT_IN_DECLARED_GRAPH",
                    f"No declared node, port, or edge for: {', '.join(missing)}",
                )
            )
        if not queries:
            issues.append(make_issue("EMPTY_TOPOLOGY_QUERY", "No assets were requested."))
        if conflicts:
            issues.append(
                make_issue(
                    "CONFLICTING_EDGE_ENDPOINTS",
                    f"Declared edge IDs have different endpoints: {', '.join(conflicts)}",
                )
            )

        response = build_response(
            request,
            status="degraded" if issues else "complete",
            result={
                "direct_connections": direct,
                "reachable_nodes": reachable,
                "routing_assessment": "declared_only" if queries - set(missing) else "unknown",
                "actual_routing_confirmed": False,
                "evidence_ids": evidence_ids,
            },
            consumed_evidence_ids=list(dict.fromkeys(evidence_ids)),
            implementation=implementation_block(self.role, "1.0.0"),
            issues=issues,
            limitations=limitations,
        )
        check_response(request, response)
        return response
