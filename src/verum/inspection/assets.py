"""The assets that an inspection can target and the places where they sit in the topology.

An asset has a kind (tank, pump, isolation valve, pipe edge or pressure transmitter), and each
action accepts one kind. The helper methods give the edges next to a valve, the discharge edge of a
pump and the receipt edges of a tank, which the preconditions and the models read from the truth.

See D100 and D104.
"""

from __future__ import annotations

from functools import lru_cache

from verum.contracts import load_topology
from verum.contracts.topology import Edge, Topology
from verum.inspection.catalog import PRESSURE_TRANSMITTERS


class Assets:
    def __init__(self, topology: Topology) -> None:
        self.topology = topology
        self.edges = {e.edge_id: e for e in topology.edges}
        self.valves = sorted(n for n in topology.nodes if n.startswith("XV-"))

    def kind(self, asset: str) -> str | None:
        if asset in self.topology.tank_ids:
            return "tank"
        if asset in self.topology.pumps:
            return "pump"
        if asset in self.valves:
            return "isolation_valve"
        if asset in self.edges:
            return "pipe"
        if asset in PRESSURE_TRANSMITTERS:
            return "pressure_transmitter"
        return None

    def listing(self) -> list[dict[str, str]]:
        """Every target of an inspection, as the gateway lists assets."""
        items = [(t, "tank") for t in self.topology.tank_ids]
        items += [(p, "pump") for p in self.topology.pumps]
        items += [(v, "isolation_valve") for v in self.valves]
        items += [(e, "pipe") for e in self.edges]
        items += [(t, "pressure_transmitter") for t in PRESSURE_TRANSMITTERS]
        return [{"asset_id": a, "kind": k} for a, k in items]

    def valve_edges(self, valve: str) -> tuple[Edge, Edge]:
        """The inbound and the outbound edge of an isolation valve."""
        inbound = next(e for e in self.topology.edges if e.to_node == valve)
        outbound = next(e for e in self.topology.edges if e.from_node == valve)
        return inbound, outbound

    def pump_discharge_edge(self, pump: str) -> Edge:
        return next(e for e in self.topology.edges if e.from_node == pump)

    def receipt_edges(self, tank: str) -> list[Edge]:
        suffix = tank[-3:]
        return [e for e in self.topology.edges if e.edge_id.startswith(f"E-R{suffix}")]

    def receipt_valve(self, tank: str) -> str:
        return f"XV-R{tank[-3:]}"


@lru_cache(maxsize=1)
def load_assets() -> Assets:
    return Assets(load_topology())
