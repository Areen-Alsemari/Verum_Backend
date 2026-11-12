"""Checks of the default topology query: only assets the declared graph can resolve are asked."""

from __future__ import annotations

from typing import Any

from _runner_cases import reference, run, snapshot

TRANSMITTERS = ["PT-001", "PT-201", "PT-202A", "PT-202B", "PT-203"]
SKIP_CODE = ("topology_dependency", "ASSETS_NOT_IN_DECLARED_GRAPH")


def _edge(edge_id: str, source: str, target: str) -> dict[str, str]:
    return {"edge_id": edge_id, "from_node": source, "to_node": target}


def _query(ref: dict[str, Any] | None = None, **changes: Any) -> list[str]:
    changed = snapshot(reference=ref, **changes) if ref is not None else snapshot(**changes)
    bundle = run(snapshot=changed)
    query: list[str] = bundle.requests["topology_dependency"]["input"]["query_asset_ids"]
    return query


def _codes(ref: dict[str, Any] | None = None) -> set[tuple[str, str]]:
    bundle = run(snapshot=snapshot(reference=ref)) if ref is not None else run()
    return {(n["role"], n["code"]) for n in bundle.notes}


def test_pressure_transmitters_are_not_asked_about() -> None:
    """The five transmitters are skipped, every other reference asset is kept, and it is noted.

    Independent: yes, because the transmitter ids and the asset count are literals.
    """
    all_ids = [a["asset_id"] for a in reference()["assets"]]
    query = _query()
    assert not set(TRANSMITTERS) & set(query)
    assert query == [a for a in all_ids if a not in TRANSMITTERS] and len(all_ids) == 49
    assert SKIP_CODE in _codes()


def test_a_node_an_edge_and_a_port_owner_are_all_kept() -> None:
    """A node id, an edge id and an asset that owns a port node stay in the query.

    Independent: yes, because the three small graphs are written by the test.
    """
    ref = reference()
    ref["connections"] = [_edge("E-D1", "XV-R000", "DELIVERY_METER")]
    assert _query(ref) == ["XV-R000", "E-D1"]
    ref["connections"] = [_edge("E-S101a", "TK-101:outlet_nozzle", "XV-S101")]
    assert _query(ref) == ["TK-101", "XV-S101", "E-S101a"]
    ref["connections"] = [_edge("E001", "BOUNDARY", "METER")]
    assert _query(ref) == ["E001"]


def test_near_misses_of_declared_ids_are_not_kept() -> None:
    """An id that only starts like a node, or differs in case, is skipped.

    Independent: yes, because the graph declares exactly one node with a port.
    """
    ref = reference()
    ref["assets"] = [
        {"asset_id": "TK-10", "kind": "tank"},
        {"asset_id": "tk-101", "kind": "tank"},
        {"asset_id": "TK-101", "kind": "tank"},
    ]
    ref["connections"] = [_edge("E-S101a", "TK-101:outlet_nozzle", "XV-S101")]
    assert _query(ref) == ["TK-101"]


def test_the_order_follows_the_reference_and_repeats() -> None:
    """The query keeps the order of the reference assets and is the same on every run.

    Independent: yes, because the expected order is computed from the asset list alone.
    """
    ref = reference()
    first, second = _query(ref), _query(ref)
    assert first == second
    position = {a["asset_id"]: i for i, a in enumerate(ref["assets"])}
    assert [position[a] for a in first] == sorted(position[a] for a in first)
    ref["assets"] = list(reversed(ref["assets"]))
    assert _query(ref) == list(reversed(first))


def test_a_reference_without_a_graph_keeps_the_old_query() -> None:
    """Without declared connections every asset is queried and no skip is noted.

    Independent: yes, because the reference is edited to have no connections.
    """
    ref = reference()
    ref["connections"] = []
    assert _query(ref) == [a["asset_id"] for a in ref["assets"]]
    codes = _codes(ref)
    assert ("topology_dependency", "NO_DECLARED_CONNECTIONS") in codes
    assert SKIP_CODE not in codes


def test_assets_named_by_the_caller_are_passed_on_as_given() -> None:
    """A caller's query is never filtered, so an absent id is left for Agent 3 to report.

    Independent: yes, because the queried ids are literals.
    """
    named = ("PT-001", "E001", "NOPE-1")
    assert _query(query_asset_ids=named) == list(named)
    notes = run(snapshot=snapshot(query_asset_ids=named)).notes
    assert SKIP_CODE not in {(n["role"], n["code"]) for n in notes}


def test_the_requests_of_the_other_roles_do_not_change() -> None:
    """Agents 1, 2 and 4 build the same requests as when every asset is named explicitly.

    Agent 6 differs by design: by default it gets only the assets that Agent 5 implicates (none
    for the placeholders), and a caller's list is passed on as given.

    Independent: yes, because the comparison run names all asset ids and skips nothing.
    """
    all_ids = tuple(a["asset_id"] for a in reference()["assets"])
    default, explicit = run(), run(snapshot=snapshot(query_asset_ids=all_ids))
    for role in (
        "predictive_health",
        "anomaly_detection",
        "historical_asset_intelligence",
    ):
        assert default.requests[role] == explicit.requests[role], role
    assert default.requests["historical_asset_intelligence"]["input"]["query_asset_ids"] == list(
        all_ids
    )
    assert default.requests["inspection_planning"]["input"]["target_asset_ids"] == []
    assert explicit.requests["inspection_planning"]["input"]["target_asset_ids"] == list(all_ids)
    assert len(default.requests["topology_dependency"]["input"]["query_asset_ids"]) == 44
