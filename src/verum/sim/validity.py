"""Quasi-steady validity diagnostic: the rigid-column time constant of an event.

Inputs: the path of an event (its edges), the flow before the event and the model.
Outputs: ``tau`` and the event ratio ``duration / tau``.
Key assumptions:
    * ``tau = (sum L_i / A_i) Q0 / (g dH0)`` along the path (decision D18), where
      ``dH0`` is the total head loss along the path at ``Q0`` with the valves fully
      open. For a delivery path the boundary-law drop is part of ``dH0`` (it is a
      resistance); the pump head is not a loss.
    * ``Q0`` is the larger of the present flow and the flow the event moves towards
      (the set-point for a receipt event; the reference flow if the pump is dead-headed),
      so that an event that starts a flow from zero is not judged to have no inertia.
    * An event is quasi-steady-valid only if ``duration >= factor * tau``; the factor
      is a proposal (10). A failing event is flagged, never blocked, in this phase.
    * Durations: a valve stroke lasts its travel time; a receipt set-point change lasts
      four controller time constants.

Source: ``docs/design_decisions.md`` D18.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from verum.contracts.topology import Topology
from verum.hydraulics import HydraulicModel


@dataclass(frozen=True)
class TauResult:
    tau_s: float
    sum_l_over_a: float
    head_loss_m: float
    flow_m3s: float


def receipt_path(topology: Topology, tank: str | None) -> tuple[str, ...]:
    ids = ["E001", "E002", "E003"]
    if tank is not None:
        ids += [e.edge_id for e in topology.edges if e.route_id == f"R-{tank[3:]}"]
    return tuple(ids)


def delivery_path(topology: Topology, tank: str, pump: str) -> tuple[str, ...]:
    branch = "P-A" if pump == "P-101A" else "P-B"
    routes = (f"S-{tank[3:]}", "S-HEADER", branch, "D-MAIN")
    return tuple(e.edge_id for r in routes for e in topology.edges if e.route_id == r)


def rigid_column_tau(
    model: HydraulicModel,
    edge_ids: tuple[str, ...],
    flow_m3s: float,
    profile: str,
    law_coefficient_m: float = 0.0,
) -> TauResult:
    """Time constant of the liquid column along ``edge_ids`` at ``flow_m3s``."""
    sum_l_over_a = sum(
        model.topology.edge(e).length_m
        / (math.pi * model.topology.edge(e).inner_diameter_m ** 2 / 4)
        for e in edge_ids
    )
    ref = model.config["pump_reference_flow_m3h"]
    loss = model.path_head_loss(edge_ids, flow_m3s, profile)
    loss += law_coefficient_m * (flow_m3s * 3600.0 / ref) ** 2
    if flow_m3s <= 0.0 or loss <= 0.0:
        return TauResult(0.0, sum_l_over_a, loss, flow_m3s)
    tau = sum_l_over_a * flow_m3s / (model.g * loss)
    return TauResult(tau, sum_l_over_a, loss, flow_m3s)


def ratio(duration_s: float, tau_s: float) -> float | None:
    """duration / tau, or None when tau is zero (no inertia to compare with)."""
    return None if tau_s <= 0.0 else duration_s / tau_s


def is_valid(duration_s: float, tau_s: float, factor: float) -> bool:
    return duration_s >= factor * tau_s
