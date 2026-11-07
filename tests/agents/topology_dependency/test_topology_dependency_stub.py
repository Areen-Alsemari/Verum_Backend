"""Check topology traversal on the published example and small test graphs."""

from __future__ import annotations

import json
from typing import Any

import pytest

from verum.agents.topology_dependency import TopologyDependencyAgent
from verum.contracts.agent_interfaces import contract_directory


def _example_request() -> dict[str, Any]:
    path = contract_directory() / "examples" / "topology_dependency.request.json"
    request: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return request


@pytest.mark.parametrize(
    ("direction", "expected_edges", "expected_boundary", "excluded_boundary"),
    [
        ("upstream", {"E-R101b"}, "PIPELINE_RECEIPT_BOUNDARY", "DISTRIBUTION_BOUNDARY"),
        ("downstream", {"E-S101a"}, "DISTRIBUTION_BOUNDARY", "PIPELINE_RECEIPT_BOUNDARY"),
    ],
)
def test_topology_traces_the_requested_direction(
    direction: str,
    expected_edges: set[str],
    expected_boundary: str,
    excluded_boundary: str,
) -> None:
    """Check that the tank query follows only the requested direction.

    Independent: yes, because the expected links and boundaries come from the fixture graph.
    """
    request = _example_request()
    request["input"]["direction"] = direction

    report = TopologyDependencyAgent().run(request)
    result = report["result"]

    assert report["status"] == "complete"
    assert {edge["edge_id"] for edge in result["direct_connections"]} == expected_edges
    assert expected_boundary in result["reachable_nodes"]
    assert excluded_boundary not in result["reachable_nodes"]
    assert result["routing_assessment"] == "declared_only"
    assert result["actual_routing_confirmed"] is False


def test_topology_handles_cycles_and_duplicate_edges() -> None:
    """Check traversal through a loop with a duplicate edge and a disconnected branch.

    Independent: yes, because the expected nodes and direct edge are derived by hand.
    """
    request = _example_request()
    first_edge = {"edge_id": "E1", "from_node": "A", "to_node": "B"}
    request["input"].update(
        query_asset_ids=["A"],
        direction="downstream",
        declared_connections=[
            first_edge,
            dict(first_edge),
            {"edge_id": "E2", "from_node": "B", "to_node": "C"},
            {"edge_id": "E3", "from_node": "C", "to_node": "A"},
            {"edge_id": "E4", "from_node": "X", "to_node": "Y"},
        ],
    )

    report = TopologyDependencyAgent().run(request)

    assert report["status"] == "complete"
    assert report["result"]["direct_connections"] == [first_edge]
    assert report["result"]["reachable_nodes"] == ["B", "C"]


def test_topology_reports_an_unknown_asset() -> None:
    """Check that a query for an absent asset returns an explicit issue.

    Independent: yes, because the queried identifier is absent from the fixture graph.
    """
    request = _example_request()
    request["input"]["query_asset_ids"] = ["UNKNOWN-ASSET"]

    report = TopologyDependencyAgent().run(request)

    assert report["status"] == "degraded"
    assert report["result"]["routing_assessment"] == "unknown"
    assert report["result"]["direct_connections"] == []
    assert report["result"]["reachable_nodes"] == []
    assert any(issue["code"] == "ASSET_NOT_IN_DECLARED_GRAPH" for issue in report["issues"])


def test_topology_traces_a_single_declared_edge() -> None:
    """Check direct connectivity and reachability in a graph with one edge.

    Independent: yes, because the expected result is specified by the single input edge.
    """
    request = _example_request()
    edge = {"edge_id": "E1", "from_node": "A", "to_node": "B"}
    request["input"].update(
        query_asset_ids=["A"],
        direction="downstream",
        declared_connections=[edge],
    )

    report = TopologyDependencyAgent().run(request)
    result = report["result"]

    assert report["status"] == "complete"
    assert result["direct_connections"] == [edge]
    assert result["reachable_nodes"] == ["B"]