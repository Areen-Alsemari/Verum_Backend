"""Pipe network connectivity under a valve and pump lineup.

Inputs: a validated ``Topology`` and a ``Lineup`` (open valves, running pumps).
Outputs: reachability, paths and the set of edges that can carry flow.
Key assumptions:
    * No node or edge is added. The tank is not an edge; ``through_tanks``
      adds a virtual link between a tank's receipt and outlet nozzles only for
      queries that ask for it, and it is reported as such in a path.
    * Pipes and open valves carry flow in either direction, because the
      receipt branches have no check valve and signed (reverse) flow is
      physical. Check valves and pumps are one-way, in the contract's
      from -> to direction. A stopped pump blocks. A closed valve blocks every
      edge that touches it.
    * An edge is active when it lies on a walk between two distinct terminals
      (external boundaries and tank nozzles). Every branch point of this
      topology is guarded by a valve, so a walk is equivalent to a simple path;
      the tests confirm this by exhaustive search for all documented lineups.
    * The phase 0 ``reachable`` query (contract orientation, no lineup) is kept.

Source: ``revised/01_facility_tanks_topology.md`` sections 3.3, 6.2 and 7.1;
``VERUM_INTEGRATION_README.md`` section B (separate receipt and suction
headers).
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Collection
from dataclasses import dataclass

from verum.contracts.errors import ContractError
from verum.contracts.topology import Edge, Topology

RECEIPT_BOUNDARY = "PIPELINE_RECEIPT_BOUNDARY"
DISTRIBUTION_BOUNDARY = "DISTRIBUTION_BOUNDARY"
TANK_LINK = "<tank>"

Arc = tuple[str, str, str]  # (from node, to node, edge id or TANK_LINK)


@dataclass(frozen=True)
class Lineup:
    """Which valves are open and which pumps are running."""

    open_valves: frozenset[str]
    running_pumps: frozenset[str]

    @classmethod
    def of(cls, open_valves: Collection[str] = (), running_pumps: Collection[str] = ()) -> Lineup:
        return cls(frozenset(open_valves), frozenset(running_pumps))


@dataclass(frozen=True)
class Network:
    """Directed topology with lineup-dependent connectivity."""

    topology: Topology
    successors: dict[str, frozenset[str]]

    @classmethod
    def from_topology(cls, topology: Topology) -> Network:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in topology.edges:
            adjacency[edge.from_node].add(edge.to_node)
            adjacency.setdefault(edge.to_node, set())
        return cls(topology, {node: frozenset(out) for node, out in adjacency.items()})

    # --- phase 0 query: contract orientation, every element passable ---------
    def reachable(self, source: str, target: str) -> bool:
        """True when ``target`` is reachable from ``source`` along directed edges."""
        if source not in self.successors or target not in self.successors:
            return False
        seen, queue = {source}, deque([source])
        while queue:
            node = queue.popleft()
            if node == target:
                return True
            for nxt in self.successors[node] - seen:
                seen.add(nxt)
                queue.append(nxt)
        return False

    # --- element classes ---------------------------------------------------------
    @property
    def valves(self) -> frozenset[str]:
        return frozenset(n for n in self.topology.nodes if n.startswith("XV-"))

    @property
    def one_way(self) -> frozenset[str]:
        checks = frozenset(n for n in self.topology.nodes if n.startswith("CV-"))
        return checks | frozenset(self.topology.pumps)

    @property
    def terminals(self) -> frozenset[str]:
        nozzles = frozenset(n for n in self.topology.nodes if ":" in n)
        return nozzles | {RECEIPT_BOUNDARY, DISTRIBUTION_BOUNDARY}

    def _tank_links(self) -> list[tuple[str, str]]:
        return [(f"{t}:receipt_nozzle", f"{t}:outlet_nozzle") for t in self.topology.tank_ids]

    def check_lineup(self, lineup: Lineup) -> None:
        """Raise ``ContractError`` if the lineup names an unknown valve or pump."""
        unknown = (lineup.open_valves - self.valves) | (
            lineup.running_pumps - frozenset(self.topology.pumps)
        )
        if unknown:
            raise ContractError(f"lineup names unknown elements: {sorted(unknown)}")

    # --- arcs ---------------------------------------------------------------------
    def _blocked(self, node: str, lineup: Lineup) -> bool:
        if node in self.valves:
            return node not in lineup.open_valves
        if node in self.topology.pumps:
            return node not in lineup.running_pumps
        return False

    def _edge_arcs(self, edge: Edge, lineup: Lineup) -> list[Arc]:
        if self._blocked(edge.from_node, lineup) or self._blocked(edge.to_node, lineup):
            return []
        arcs: list[Arc] = [(edge.from_node, edge.to_node, edge.edge_id)]
        if not ({edge.from_node, edge.to_node} & self.one_way):
            arcs.append((edge.to_node, edge.from_node, edge.edge_id))
        return arcs

    def arcs(self, lineup: Lineup, through_tanks: bool = False) -> list[Arc]:
        """All passable arcs under a lineup."""
        self.check_lineup(lineup)
        result = [a for edge in self.topology.edges for a in self._edge_arcs(edge, lineup)]
        if through_tanks:
            for recv, out in self._tank_links():
                result += [(recv, out, TANK_LINK), (out, recv, TANK_LINK)]
        return result

    @staticmethod
    def _adjacency(arcs: list[Arc]) -> dict[str, list[Arc]]:
        out: dict[str, list[Arc]] = defaultdict(list)
        for arc in arcs:
            out[arc[0]].append(arc)
        return out

    def _reach(self, start: str, adjacency: dict[str, list[Arc]]) -> set[str]:
        seen, queue = {start}, deque([start])
        while queue:
            for _, nxt, _ in adjacency.get(queue.popleft(), []):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen

    # --- queries ---------------------------------------------------------------------
    def path(
        self, source: str, target: str, lineup: Lineup, through_tanks: bool = False
    ) -> list[Arc] | None:
        """Shortest arc path from ``source`` to ``target``, or None."""
        adjacency = self._adjacency(self.arcs(lineup, through_tanks))
        parent: dict[str, Arc | None] = {source: None}
        queue = deque([source])
        while queue:
            node = queue.popleft()
            if node == target:
                break
            for arc in adjacency.get(node, []):
                if arc[1] not in parent:
                    parent[arc[1]] = arc
                    queue.append(arc[1])
        if target not in parent:
            return None
        steps: list[Arc] = []
        cursor = target
        while parent[cursor] is not None:
            step = parent[cursor]
            assert step is not None
            steps.append(step)
            cursor = step[0]
        return steps[::-1]

    def connected(
        self, source: str, target: str, lineup: Lineup, through_tanks: bool = False
    ) -> bool:
        """True when a passable path joins the two nodes."""
        return self.path(source, target, lineup, through_tanks) is not None

    def connected_terminals(self, source: str, lineup: Lineup) -> frozenset[str]:
        """Terminals other than ``source`` that ``source`` can reach."""
        adjacency = self._adjacency(self.arcs(lineup))
        return frozenset((self._reach(source, adjacency) & self.terminals) - {source})

    def active_edges(self, lineup: Lineup) -> frozenset[str]:
        """Edges that lie on a passable walk between two distinct terminals."""
        arcs = self.arcs(lineup)
        adjacency = self._adjacency(arcs)
        reach = {node: self._reach(node, adjacency) for node in self.topology.nodes}
        active: set[str] = set()
        for source in self.terminals:
            for tail, head, edge_id in arcs:
                if tail in reach[source] and (reach[head] & self.terminals) - {source}:
                    active.add(edge_id)
        return frozenset(active)
