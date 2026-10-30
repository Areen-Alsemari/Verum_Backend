"""Lumped liquid column of one flow path: losses, inertance and inertial head offsets.

Inputs: the ordered edges of a single flow path, the lineup that sets the local loss
coefficients, the fitting profile and the hydraulic model. Outputs: the head loss
``H_loss(Q)`` with partly closed valves, the inertance ``I = sum L_i / (g A_i)``, the
wave travel time ``sum L_i / a_i`` and the head offsets that the inertial term adds to
the node heads of a steady solve.
Key assumptions:
    * Rigid column (decision D22): the liquid along the path moves as one body, so the
      path has one flow and one ``dQ/dt``. Pipes are full; the pipe inventory is constant.
    * The loss uses the same friction law, fitting coefficients and valve law as the
      steady solver, so a steady solve at an imposed flow and this path agree (a
      same-formula check, not independent validation).
    * A partly closed valve adds ``K(alpha) - K_open`` to the edge that starts at the
      valve, as in the steady solver.
    * Offsets: along the flow, the head drop over edge ``i`` is ``loss_i + (L_i/(g A_i)) dQ/dt``.
      A receipt path is anchored at its tank (offset ``+ Lambda_down dQ/dt``); a delivery
      path is anchored at its tank and the pump rise is quasi-steady (offset
      ``- Lambda_up dQ/dt``).

Source: ``docs/design_decisions.md`` D22; ``revised/02_hydraulic_model.md`` section 3.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from verum.graph import Lineup
from verum.hydraulics import HydraulicModel
from verum.hydraulics.friction import head_loss

RECEIPT_COMMON = ("E001", "E002", "E003")
AFTER_PUMP = frozenset(
    {"E-PA2", "E-PA3", "E-PA4", "E-PB2", "E-PB3", "E-PB4", "E-D1", "E-D2"}
)  # edges downstream of the pump outlet


@dataclass(frozen=True)
class LeakLayout:
    """Where the leaks sit on a column and how they change the flow of each edge.

    ``fractions`` maps a leaked edge to its position; ``offsets`` maps every edge to the flow at its
    upstream and downstream ends relative to the state of the column (the source flow of a
    receipt column, the pump flow of a delivery column). ``tank_extra`` is the flow the tank
    gives up beyond the state (suction-side leaks), ``boundary_deduct`` the flow that never reaches
    the end of the column (a receipt tank inflow or a delivery boundary flow is the state less
    this)."""

    fractions: Mapping[str, float] = field(default_factory=dict)
    offsets: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    tank_extra: float = 0.0
    boundary_deduct: float = 0.0

    @property
    def total(self) -> float:
        return self.tank_extra + self.boundary_deduct


@dataclass(frozen=True)
class PathEdge:
    edge_id: str
    a: str
    b: str
    length_m: float
    diameter_m: float
    k_base: float
    valve: str | None


@dataclass(frozen=True)
class LumpedPath:
    edges: tuple[PathEdge, ...]
    model: HydraulicModel
    kind: str  # "receipt" or "delivery"

    @property
    def inertance(self) -> float:
        g = self.model.g
        return sum(e.length_m / (g * math.pi * e.diameter_m**2 / 4) for e in self.edges)

    def loss(
        self, flow_m3s: float, alphas: Mapping[str, float], layout: LeakLayout | None = None
    ) -> float:
        m = self.model
        total = 0.0
        for e in self.edges:
            k = e.k_base
            if e.valve is not None:
                k += m.valve_extra_k(alphas.get(e.valve, 1.0))
            if layout is None or e.edge_id not in layout.offsets:
                total += head_loss(
                    flow_m3s, e.diameter_m, e.length_m, k, m.rho, m.mu, m.roughness, m.g
                )
                continue
            up, down = layout.offsets[e.edge_id]
            x = layout.fractions.get(e.edge_id, 1.0)
            for share, off in ((x, up), (1.0 - x, down)):
                total += head_loss(
                    flow_m3s + off, e.diameter_m, share * e.length_m, share * k,
                    m.rho, m.mu, m.roughness, m.g,
                )  # fmt: skip
        return total

    def leak_layout(
        self, fractions: Mapping[str, float], flows: Mapping[str, float]
    ) -> LeakLayout | None:
        """Layout of the leaks that lie on this column (``flows``: the frozen leak flow of each)."""
        here = {eid: x for eid, x in fractions.items() if any(e.edge_id == eid for e in self.edges)}
        if not here or not any(flows.get(eid, 0.0) > 0.0 for eid in here):
            return None
        offsets: dict[str, tuple[float, float]] = {}
        ids = [e.edge_id for e in self.edges]
        if self.kind == "receipt":
            cum = 0.0
            for eid in ids:
                up = -cum
                cum += flows.get(eid, 0.0) if eid in here else 0.0
                offsets[eid] = (up, -cum)
            return LeakLayout(here, offsets, 0.0, cum)
        pump = next((i for i, eid in enumerate(ids) if eid in AFTER_PUMP), len(ids))
        suction = 0.0
        for eid in reversed(ids[:pump]):
            down = suction
            suction += flows.get(eid, 0.0) if eid in here else 0.0
            offsets[eid] = (suction, down)
        discharge = 0.0
        for eid in ids[pump:]:
            up = -discharge
            discharge += flows.get(eid, 0.0) if eid in here else 0.0
            offsets[eid] = (up, -discharge)
        return LeakLayout(here, offsets, suction, discharge)

    def wave_time_s(self, speeds: Mapping[int, float]) -> float:
        return sum(e.length_m / speeds[_dn(e.diameter_m)] for e in self.edges)

    def tap_offset(self, flow_m3s: float, qdot_m3s2: float, n_upstream: int = 2) -> float:
        """Head at a tap that lies after the first ``n_upstream`` edges of the column, minus
        the head at the start of the column: ``-(loss + Lambda dQ/dt)`` over those edges
        (decision D36). Valves are not on these edges for the receipt path."""
        m, g = self.model, self.model.g
        edges = self.edges[:n_upstream]
        loss = sum(
            head_loss(flow_m3s, e.diameter_m, e.length_m, e.k_base, m.rho, m.mu, m.roughness, m.g)
            for e in edges
        )
        lam = sum(e.length_m / (g * math.pi * e.diameter_m**2 / 4) for e in edges)
        return -(loss + lam * qdot_m3s2)

    def valves(self) -> tuple[str, ...]:
        return tuple(e.valve for e in self.edges if e.valve is not None)

    def offsets(self, qdot_m3s2: float) -> dict[str, float]:
        """Inertial head offsets (m) of the solver nodes on the path."""
        g = self.model.g
        out: dict[str, float] = {}
        if self.kind == "receipt":
            down = 0.0
            for e in reversed(self.edges):
                out.setdefault(e.b, down * qdot_m3s2)
                down += e.length_m / (g * math.pi * e.diameter_m**2 / 4)
                out[e.a] = down * qdot_m3s2
            return out
        up = 0.0
        for e in self.edges:
            out.setdefault(e.a, -up * qdot_m3s2)
            up += e.length_m / (g * math.pi * e.diameter_m**2 / 4)
            out[e.b] = -up * qdot_m3s2
        return out


def _dn(diameter_m: float) -> int:
    return int(round(diameter_m * 1000.0 / 50.0)) * 50


def _build(
    model: HydraulicModel, edge_ids: tuple[str, ...], lineup: Lineup, profile: str, kind: str
) -> LumpedPath:
    ks = model.edge_k(lineup, profile)
    valves = {
        "XV-R000", "XV-R101", "XV-R102", "XV-R103", "XV-S101", "XV-S102", "XV-S103",
        "XV-PAI", "XV-PAO", "XV-PBI", "XV-PBO",
    }  # fmt: skip
    edges = []
    for eid in edge_ids:
        e = model.topology.edge(eid)
        edges.append(
            PathEdge(
                eid,
                model._end(e.from_node, "from"),
                model._end(e.to_node, "to"),
                e.length_m,
                e.inner_diameter_m,
                ks[eid],
                e.from_node if e.from_node in valves else None,
            )
        )
    return LumpedPath(tuple(edges), model, kind)


def receipt_edges(model: HydraulicModel, tank: str) -> tuple[str, ...]:
    branch = [e.edge_id for e in model.topology.edges if e.route_id == f"R-{tank[3:]}"]
    return RECEIPT_COMMON + tuple(branch)


def delivery_edges(model: HydraulicModel, tank: str, pump: str) -> tuple[str, ...]:
    leg = "P-A" if pump == "P-101A" else "P-B"
    routes = (f"S-{tank[3:]}", "S-HEADER", leg, "D-MAIN")
    return tuple(e.edge_id for r in routes for e in model.topology.edges if e.route_id == r)


def receipt_path(model: HydraulicModel, tank: str, lineup: Lineup, profile: str) -> LumpedPath:
    return _build(model, receipt_edges(model, tank), lineup, profile, "receipt")


def delivery_path(
    model: HydraulicModel, tank: str, pump: str, lineup: Lineup, profile: str
) -> LumpedPath:
    return _build(model, delivery_edges(model, tank, pump), lineup, profile, "delivery")
