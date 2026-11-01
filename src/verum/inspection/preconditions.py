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


def _live(c: Catalog, a: Assets, state: State, action: str, target: str) -> str | None:
    """Recheck work conditions on a recorded state without assuming that approval maintains them."""
    tol = c.param("preconditions", "flow_tolerance_m3s")
    if action == "ACT-INSP-01":
        if state["tanks"][target]["level_m"] <= c.param("preconditions", "tank_level_min_m"):
            return "LEVEL_BELOW_1_8_M"
    elif action == "ACT-INSP-02":
        edges = [state["edges"][e.edge_id] for e in a.valve_edges(target)]
        if not any(abs(e["flow_m3s"]) > tol or
                   max(e["p_from_pa_gauge"], e["p_to_pa_gauge"]) > 0 for e in edges):
            return "VALVE_NOT_FLOWING_OR_PRESSURISED"
    elif action == "ACT-INSP-03":
        edge = a.pump_discharge_edge(target).edge_id
        if (state["pumps"][target]["run_state"] != "running" or
                state["edges"][edge]["flow_m3s"] <= tol):
            return "PUMP_NOT_UNDER_LOAD_20_MIN"
    elif action == "ACT-INSP-04":
        minimum = c.param("preconditions", "edge_pressure_min_bar") * BAR_PA
        if _edge_pressure_pa(state, target) <= minimum:
            return "EDGE_BELOW_3_BAR"
    elif action == "ACT-INSP-06":
        if any(state["edges"][e.edge_id]["flow_m3s"] > tol for e in a.receipt_edges(target)):
            return "TANK_IN_RECEIPT_MODE"
    return None


def work_cancellation(
    c: Catalog, a: Assets, truth: Truth, action: str, target: str, start: float, end: float,
) -> tuple[float, str] | None:
    """First failing recorded work condition, including both boundaries and event-side rows.

    This checks the supplied simulation cadence, not a certified continuous safety monitor.
    """
    reason = check(c, a, truth, action, target, start)
    if reason is not None:
        return start, reason
    for state in truth.rows:
        time = float(state["t_sim_s"])
        if start < time <= end:
            reason = _live(c, a, state, action, target)
            if reason is not None:
                return time, reason
    reason = _live(c, a, truth.state(end), action, target)
    return (end, reason) if reason is not None else None
