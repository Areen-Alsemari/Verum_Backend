"""Directed view of the topology for reachability checks.

Inputs: a validated ``Topology``.

Outputs: ``Network``, an adjacency structure
over node names with a breadth-first reachability query.
Key assumptions:
    * Edges are directed from -> to as in the contract. Flow may reverse in the
      physical system; this view answers "is there an installed path in the
      reference direction" only and does not model flow.
    * Tank nozzles are separate nodes (``TK-101:receipt_nozzle`` and
      ``TK-101:outlet_nozzle``). The tank itself is not an edge, so the receipt
      side and the suction side are connected only through the tank inventory,
      which this graph deliberately does not represent. Reachability from the
      receipt header to the suction header must therefore be false.

Source: ``revised/01_facility_tanks_topology.md`` section 7.1;
``VERUM_INTEGRATION_README.md`` section B (separate receipt and suction
headers).
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from verum.contracts.topology import Topology


@dataclass(frozen=True)
class Network:
    """Adjacency lists keyed by node name."""

    successors: dict[str, frozenset[str]]

    @classmethod
    def from_topology(cls, topology: Topology) -> Network:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in topology.edges:
            adjacency[edge.from_node].add(edge.to_node)
            adjacency.setdefault(edge.to_node, set())
        return cls({node: frozenset(out) for node, out in adjacency.items()})

    def reachable(self, source: str, target: str) -> bool:
        """True when ``target`` can be reached from ``source`` along directed edges."""
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
