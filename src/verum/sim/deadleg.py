"""Pressure of segments that carry no flow (decision D39).

Inputs: the topology, the valves that are not closed, a steady result, the tank heads, the
reservoir head, the heads held from the last committed step and the time constant.
Outputs: a total head for every edge of the network, determined by the solve or not.
Key assumptions:
    * An edge that the steady solve gave end pressures is determined; its head is the mean of
      the heads at its ends.
    * Every other edge is a dead leg. Dead legs are joined into segments through nodes that
      are not barriers (a closed valve, a check valve, a pump). A segment that touches a tank
      nozzle takes that tank's head, one that touches the distribution boundary takes the
      reservoir head, both without delay.
    * An isolated segment holds the head it had at the last committed step and relaxes to the
      head across its closed isolation valve (valves first, then check valves and pumps, in
      name order; a neighbour that is itself a dead leg contributes its own head) with
      ``H = H_target + (H_0 - H_target) exp(-dt / tau)``. A segment with no neighbour at all
      takes zero gauge pressure at its elevation. No edge is left undetermined.
    * Trapped-liquid thermal and compressibility effects are outside the model.

Source: ``docs/design_decisions.md`` D39.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping

from verum.contracts.topology import Edge
from verum.hydraulics import HydraulicModel, SteadyResult

BOUNDARY = "DISTRIBUTION_BOUNDARY"


def _determined_heads(
    model: HydraulicModel, result: SteadyResult
) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    rho_g = model.rho * model.g
    for e in model.topology.edges:
        ends = result.edge_end_pressures_pa_gauge.get(e.edge_id)
        if ends is None:
            continue
        area = 3.141592653589793 * e.inner_diameter_m**2 / 4
        v2 = (result.edge_flows_m3s[e.edge_id] / area) ** 2 / (2.0 * model.g)
        out[e.edge_id] = (e.z_from_m + ends[0] / rho_g + v2, e.z_to_m + ends[1] / rho_g + v2)
    return out


def _is_barrier(model: HydraulicModel, node: str, open_valves: Collection[str]) -> bool:
    if node.startswith("XV-"):
        return node not in open_valves
    return node.startswith("CV-") or node in model.topology.pumps


def _barrier_rank(node: str) -> int:
    return 0 if node.startswith("XV-") else 1 if node.startswith("CV-") else 2


def _anchor(node: str, tank_heads: Mapping[str, float], h_res: float) -> float | None:
    if node.endswith((":receipt_nozzle", ":outlet_nozzle")):
        return tank_heads[node.split(":")[0]]
    return h_res if node == BOUNDARY else None


def _segments(
    model: HydraulicModel, dead: list[Edge], open_valves: Collection[str]
) -> list[list[Edge]]:
    parent = {e.edge_id: e.edge_id for e in dead}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_node: dict[str, list[Edge]] = {}
    for e in dead:
        for n in (e.from_node, e.to_node):
            if not _is_barrier(model, n, open_valves):
                by_node.setdefault(n, []).append(e)
    for edges in by_node.values():
        for other in edges[1:]:
            parent[find(other.edge_id)] = find(edges[0].edge_id)
    groups: dict[str, list[Edge]] = {}
    for e in dead:
        groups.setdefault(find(e.edge_id), []).append(e)
    return [sorted(g, key=lambda e: e.edge_id) for _k, g in sorted(groups.items())]


def edge_heads(
    model: HydraulicModel,
    open_valves: Collection[str],
    result: SteadyResult,
    tank_heads: Mapping[str, float],
    h_res: float,
    held: Mapping[str, float],
    was_dead: Collection[str],
    dt_s: float,
    tau_s: float,
) -> tuple[dict[str, float], frozenset[str]]:
    """Total head of every edge and the set of dead edges.

    Determined edges keep the mean of their end heads. An edge that was determined at the last
    committed step and is dead now is isolated at this instant: it keeps its held head."""
    det = _determined_heads(model, result)
    heads = {eid: 0.5 * (a + b) for eid, (a, b) in det.items()}
    dead = [e for e in model.topology.edges if e.edge_id not in det]
    decay = math.exp(-max(dt_s, 0.0) / tau_s)
    pending: list[tuple[list[Edge], list[str]]] = []
    for seg in _segments(model, dead, open_valves):
        direct = sorted(
            h for e in seg for n in (e.from_node, e.to_node)
            if (h := _anchor(n, tank_heads, h_res)) is not None
        )  # fmt: skip
        nodes = {n for e in seg for n in (e.from_node, e.to_node)}
        if not direct:  # open to flowing fluid at a node that is not a barrier: its head
            direct = sorted(
                h for n in nodes if not _is_barrier(model, n, open_valves)
                if (h := _neighbour_head(model, seg, n, heads, det, live_only=True)) is not None
            )  # fmt: skip
        if direct:
            for e in seg:
                heads[e.edge_id] = direct[0]
            continue
        barriers = sorted(
            (n for n in nodes if _is_barrier(model, n, open_valves)),
            key=lambda n: (_barrier_rank(n), n),
        )
        pending.append((seg, barriers))
    _resolve(model, pending, heads, det, held, decay, set(was_dead))
    return heads, frozenset(e.edge_id for e in dead)


def _neighbour_head(
    model: HydraulicModel, seg: list[Edge], node: str, heads: dict[str, float],
    det: dict[str, tuple[float, float]], live_only: bool = False,
) -> float | None:  # fmt: skip
    own = {e.edge_id for e in seg}
    for e in model.topology.edges:
        if e.edge_id in own or node not in (e.from_node, e.to_node):
            continue
        if e.edge_id in det:
            return det[e.edge_id][0] if e.from_node == node else det[e.edge_id][1]
        if e.edge_id in heads and not live_only:
            return heads[e.edge_id]
    return None


def _resolve(
    model: HydraulicModel, pending: list[tuple[list[Edge], list[str]]],
    heads: dict[str, float], det: dict[str, tuple[float, float]],
    held: Mapping[str, float], decay: float, was_dead: set[str],
) -> None:  # fmt: skip
    remaining = list(pending)
    while remaining:
        progressed = False
        for item in list(remaining):
            seg, barriers = item
            target = next(
                (
                    h
                    for b in barriers
                    if (h := _neighbour_head(model, seg, b, heads, det)) is not None
                ),
                None,
            )
            if target is None:
                continue
            _relax(seg, target, heads, held, decay, was_dead)
            remaining.remove(item)
            progressed = True
        if not progressed:
            break
    for seg, _barriers in remaining:  # nothing connected: zero gauge pressure at the elevation
        _relax(seg, seg[0].z_from_m, heads, held, decay, was_dead)


def _relax(
    seg: list[Edge],
    target: float,
    heads: dict[str, float],
    held: Mapping[str, float],
    decay: float,
    was_dead: set[str],
) -> None:
    for e in seg:
        h0 = held.get(e.edge_id, target)
        heads[e.edge_id] = target + (h0 - target) * (decay if e.edge_id in was_dead else 1.0)
