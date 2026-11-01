"""Preconditions of the inspection actions, evaluated against the true state.

Each check returns None if it holds, or a plain reason code if it fails. The permits of the
catalog (access, cold work, manifold isolation) are issued by the approval and are not state of the
process, so they have no check here.

See D104.
"""

from __future__ import annotations

from verum.inspection.assets import Assets
from verum.inspection.catalog import Catalog
from verum.inspection.truth import State, Truth

BAR_PA = 1.0e5


def _edge_pressure_pa(state: State, edge: str) -> float:
    e = state["edges"][edge]
    return float(0.5 * (e["p_from_pa_gauge"] + e["p_to_pa_gauge"]))


def _level(c: Catalog, a: Assets, t: Truth, target: str, time: float) -> str | None:
    level = t.state(time)["tanks"][target]["level_m"]
    return None if level > c.param("preconditions", "tank_level_min_m") else "LEVEL_BELOW_1_8_M"


def _valve(c: Catalog, a: Assets, t: Truth, target: str, time: float) -> str | None:
    tol = c.param("preconditions", "flow_tolerance_m3s")
    state = t.state(time)
    for edge in a.valve_edges(target):
        e = state["edges"][edge.edge_id]
        if abs(e["flow_m3s"]) > tol or max(e["p_from_pa_gauge"], e["p_to_pa_gauge"]) > 0.0:
            return None
    return "VALVE_NOT_FLOWING_OR_PRESSURISED"


def _pump(c: Catalog, a: Assets, t: Truth, target: str, time: float) -> str | None:
    """The pump has run, with a flow in its discharge edge, over the last 20 min; a pump that is
    running at the start of the episode counts as started at 0 s."""
    span = c.param("preconditions", "pump_load_min_s")
    if time < span:
        return "PUMP_NOT_UNDER_LOAD_20_MIN"
    tol = c.param("preconditions", "flow_tolerance_m3s")
    edge = a.pump_discharge_edge(target).edge_id
    for r in [time - span, time] + [
        r["t_sim_s"] for r in t.rows if time - span < r["t_sim_s"] < time
    ]:
        s = t.state(r)
        running = s["pumps"][target]["run_state"] == "running"
        if not running or s["edges"][edge]["flow_m3s"] <= tol:
            return "PUMP_NOT_UNDER_LOAD_20_MIN"
    return None


def _edge(c: Catalog, a: Assets, t: Truth, target: str, time: float) -> str | None:
    p = _edge_pressure_pa(t.state(time), target)
    return (
        None
        if p > c.param("preconditions", "edge_pressure_min_bar") * BAR_PA
        else "EDGE_BELOW_3_BAR"
    )


def _receipt(c: Catalog, a: Assets, t: Truth, target: str, time: float) -> str | None:
    tol = c.param("preconditions", "flow_tolerance_m3s")
    state = t.state(time)
    if any(state["edges"][e.edge_id]["flow_m3s"] > tol for e in a.receipt_edges(target)):
        return "TANK_IN_RECEIPT_MODE"
    return None


def check(c: Catalog, a: Assets, t: Truth, action_id: str, target: str, time: float) -> str | None:
    """The reason code of the first failed precondition, or None."""
    checks = {
        "ACT-INSP-01": _level, "ACT-INSP-02": _valve, "ACT-INSP-03": _pump,
        "ACT-INSP-04": _edge, "ACT-INSP-06": _receipt,
    }  # fmt: skip
    return checks[action_id](c, a, t, target, time) if action_id in checks else None
