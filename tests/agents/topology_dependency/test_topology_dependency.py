"""Test declared topology queries and the prepared role-view adapter."""

from __future__ import annotations

import json
from typing import Any

import pytest

from verum.agents.topology_dependency import TopologyDependencyAgent
from verum.agents.topology_dependency import agent as topology_agent
from verum.agents.topology_dependency.agent import build_topology_input
from verum.contracts.agent_interfaces import contract_directory


def _example(role: str = "topology_dependency") -> dict[str, Any]:
    path = contract_directory() / "examples" / f"{role}.request.json"
    request: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return request


def _edge(edge_id: str, source: str, target: str) -> dict[str, str]:
    return {"edge_id": edge_id, "from_node": source, "to_node": target}


def _graph(
    queries: list[str], direction: str, edges: list[dict[str, str]]
) -> dict[str, Any]:
    request = _example()
    request["input"].update(
        query_asset_ids=queries, direction=direction, declared_connections=edges
    )
    return request


@pytest.mark.parametrize(
    ("direction", "direct_ids"),
    [
        ("upstream", ["E-R101b"]),
        ("downstream", ["E-S101a"]),
        ("both", ["E-R101b", "E-S101a"]),
    ],
)
def test_published_example(direction: str, direct_ids: list[str]) -> None:
    """Compare exact results with a path walk over the published edge list.

    Independent: The expected paths are walked directly from the published edges.
    """
    request = _example()
    payload = request["input"]
    payload["direction"] = direction
    edges = payload["declared_connections"]
    expected: set[str] = set()

    for source_key, target_key in (
        [("to_node", "from_node")] if direction == "upstream"
        else [("from_node", "to_node")] if direction == "downstream"
        else [("to_node", "from_node"), ("from_node", "to_node")]
    ):
        paths: list[tuple[str, ...]] = [
            (edge[source_key], edge[target_key])
            for edge in edges
            if any(
                edge[source_key] == asset or edge[source_key].startswith(f"{asset}:")
                for asset in payload["query_asset_ids"]
            )
        ]
        while paths:
            path = paths.pop()
            expected.add(path[-1])
            if path[-1] in path[:-1]:
                continue
            paths.extend(
                (*path, edge[target_key])
                for edge in edges
                if edge[source_key] == path[-1]
            )

    report = TopologyDependencyAgent().run(request)
    result = report["result"]

    assert report["status"] == "complete"
    assert [edge["edge_id"] for edge in result["direct_connections"]] == direct_ids
    assert result["reachable_nodes"] == sorted(expected)
    assert result["routing_assessment"] == "declared_only"
    assert result["actual_routing_confirmed"] is False
    assert report["consumed_evidence_ids"] == payload["reference_evidence_ids"]


@pytest.mark.parametrize(
    ("direction", "reachable"),
    [
        ("upstream", ["A", "B"]),
        ("downstream", ["C", "D"]),
        ("both", ["A", "B", "C", "D"]),
    ],
)
def test_query_by_edge_id(direction: str, reachable: list[str]) -> None:
    """The requested edge is direct; each direction starts at its far endpoint.

    Independent: The expected nodes are read from the hand-built chain.
    """
    queried = _edge("E002", "B", "C")
    edges = [_edge("E001", "A", "B"), queried, _edge("E003", "C", "D")]
    report = TopologyDependencyAgent().run(_graph(["E002"], direction, edges))

    assert report["status"] == "complete"
    assert report["result"]["direct_connections"] == [queried]
    assert report["result"]["reachable_nodes"] == reachable


def test_multi_query_counts_a_start_reached_from_another_start() -> None:
    """Check the expected behavior for the supplied input.

    Independent: The two starts and their downstream nodes are known from the two edges.
    """
    edges = [_edge("E1", "A", "B"), _edge("E2", "B", "C")]
    report = TopologyDependencyAgent().run(_graph(["A", "B"], "downstream", edges))

    assert report["result"]["reachable_nodes"] == ["B", "C"]


def test_cycles_parallel_edges_and_shuffled_input() -> None:
    """Check the expected behavior for the supplied input.

    Independent: The expected order and cycle nodes are specified by hand.
    """
    first = _edge("E1", "A", "B")
    parallel = _edge("E2", "A", "B")
    self_loop = _edge("E3", "A", "A")
    edges = [
        parallel, _edge("E4", "B", "A"), self_loop, first, dict(first),
        _edge("E5", "X", "Y"),
    ]
    agent = TopologyDependencyAgent()

    for order in (edges, list(reversed(edges))):
        result = agent.run(_graph(["A"], "downstream", order))["result"]
        assert result["direct_connections"] == [first, parallel, self_loop]
        assert result["reachable_nodes"] == ["A", "B"]


def test_self_loop_counts_as_one_edge() -> None:
    """Check the expected behavior for the supplied input.

    Independent: The only declared edge leads back to A.
    """
    loop = _edge("LOOP", "A", "A")
    result = TopologyDependencyAgent().run(_graph(["A"], "downstream", [loop]))["result"]

    assert result["direct_connections"] == [loop]
    assert result["reachable_nodes"] == ["A"]


def test_ports_match_but_similar_ids_do_not() -> None:
    """Check the expected behavior for the supplied input.

    Independent: The input identifies exactly one matching port and two absent IDs.
    """
    port = _edge("E1", "X:out", "A")
    edges = [port, _edge("E10", "X2:out", "B"), _edge("E2", "Y", "Z")]
    report = TopologyDependencyAgent().run(
        _graph(["X", "E", "X20"], "downstream", edges)
    )

    assert report["status"] == "degraded"
    assert report["result"]["direct_connections"] == [port]
    assert report["result"]["reachable_nodes"] == ["A"]
    assert report["issues"][0]["code"] == "ASSET_NOT_IN_DECLARED_GRAPH"


@pytest.mark.parametrize(
    ("queries", "code"),
    [([], "EMPTY_TOPOLOGY_QUERY"), (["UNKNOWN-ASSET"], "ASSET_NOT_IN_DECLARED_GRAPH")],
)
def test_empty_or_unknown_query(queries: list[str], code: str) -> None:
    """Check the expected behavior for the supplied input.

    Independent: The query is empty or absent from the one-edge graph.
    """
    report = TopologyDependencyAgent().run(
        _graph(queries, "both", [_edge("E1", "A", "B")])
    )

    assert report["status"] == "degraded"
    assert report["result"]["routing_assessment"] == "unknown"
    assert report["result"]["direct_connections"] == []
    assert report["result"]["reachable_nodes"] == []
    assert [issue["code"] for issue in report["issues"]] == [code]


def test_duplicate_edge_id_with_conflicting_endpoints() -> None:
    """Check the expected behavior for the supplied input.

    Independent: The fixture declares two different endpoints under the same edge ID.
    """
    edges = [_edge("E1", "A", "B"), _edge("E1", "A", "C")]
    report = TopologyDependencyAgent().run(_graph(["A"], "downstream", edges))

    assert report["status"] == "degraded"
    assert report["result"]["direct_connections"] == edges
    assert report["result"]["reachable_nodes"] == ["B", "C"]
    assert [issue["code"] for issue in report["issues"]] == ["CONFLICTING_EDGE_ENDPOINTS"]


def test_observations_do_not_change_topology_or_consumed_evidence() -> None:
    """Check the expected behavior for the supplied input.

    Independent: The expected evidence IDs come directly from the request.
    """
    request = _example()
    agent = TopologyDependencyAgent()
    baseline = agent.run(request)
    forecast_request = _example("predictive_health")
    observations = forecast_request["input"]["observations"]
    known_ids = {item["evidence_id"] for item in request["evidence"]}
    request["evidence"].extend(
        item for item in forecast_request["evidence"] if item["evidence_id"] not in known_ids
    )
    request["input"]["observations"] = observations

    report = agent.run(request)

    assert report["result"] == baseline["result"]
    assert report["consumed_evidence_ids"] == request["input"]["reference_evidence_ids"]


def test_role_view_adapter_runs_both_directions_and_copies_connections() -> None:
    """Check the expected behavior for the supplied input.

    Independent: The input edge and its two endpoints are specified by hand.
    """
    edge = _edge("E002", "A", "B")
    record = {"query": {"asset_id": "E002"}, "reference": {"connections": [edge]}}
    request = _example()
    request["input"] = build_topology_input(
        record, reference_evidence_ids=request["input"]["reference_evidence_ids"]
    )

    assert request["input"]["direction"] == "both"
    assert request["input"]["declared_connections"] == [edge]
    assert request["input"]["declared_connections"][0] is not edge
    edge["to_node"] = "CHANGED"

    report = TopologyDependencyAgent().run(request)

    assert report["status"] == "complete"
    assert report["result"]["direct_connections"] == [_edge("E002", "A", "B")]
    assert report["result"]["reachable_nodes"] == ["A", "B"]


def test_chain_end_has_no_downstream_nodes() -> None:
    """Return an empty result for a known node at the end of a chain.

    Independent: C appears in the graph and has no outgoing edge.
    """
    edges = [_edge("E1", "A", "B"), _edge("E2", "B", "C")]
    report = TopologyDependencyAgent().run(_graph(["C"], "downstream", edges))

    assert report["status"] == "complete"
    assert report["result"]["routing_assessment"] == "declared_only"
    assert report["result"]["direct_connections"] == []
    assert report["result"]["reachable_nodes"] == []


def test_query_stays_in_its_disconnected_component() -> None:
    """Return only the connection in the queried component.

    Independent: the two declared edges have no common endpoint.
    """
    separate = _edge("E2", "X", "Y")
    report = TopologyDependencyAgent().run(
        _graph(["X"], "both", [_edge("E1", "A", "B"), separate])
    )

    assert report["status"] == "complete"
    assert report["result"]["direct_connections"] == [separate]
    assert report["result"]["reachable_nodes"] == ["Y"]


@pytest.mark.parametrize("query", ["x", " X", "X ", "e1", " E1", "E1 "])
def test_case_and_whitespace_near_misses_do_not_resolve(query: str) -> None:
    """Reject near-misses for both the port owner and the edge ID.

    Independent: the graph declares X:out and E1 with exact spelling.
    """
    report = TopologyDependencyAgent().run(
        _graph([query], "both", [_edge("E1", "X:out", "Y")])
    )

    assert report["status"] == "degraded"
    assert report["result"]["routing_assessment"] == "unknown"
    assert report["result"]["direct_connections"] == []
    assert report["result"]["reachable_nodes"] == []
    assert [issue["code"] for issue in report["issues"]] == [
        "ASSET_NOT_IN_DECLARED_GRAPH"
    ]


def test_reachability_self_check_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return an error report when traversal omits a declared reachable node.

    Independent: A -> B must reach B, even when traversal is forced to omit it.
    """

    def omit_reachable_nodes(
        _adjacency: dict[str, set[str]], _starts: set[str]
    ) -> set[str]:
        return set()

    monkeypatch.setattr(topology_agent, "_reachable", omit_reachable_nodes)
    report = TopologyDependencyAgent().run(
        _graph(["A"], "downstream", [_edge("E1", "A", "B")])
    )

    assert report["status"] == "error"
    assert report["result"] is None
    assert [issue["code"] for issue in report["issues"]] == [
        "TOPOLOGY_REACHABILITY_CHECK_FAILED"
    ]
