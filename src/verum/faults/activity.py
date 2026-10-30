"""Lineup context of a fault: whether its asset is active and whether misrouting (b) is eligible.

Inputs: the lineup states in force from the onset of a fault to the end of the episode, and a
fault specification. Outputs: ``active`` or ``latent`` (decision D76) and the parallel-branch test
of decision D75.
Key assumptions:
    * A state is the set of open valves and running pumps of a lineup mode with the receipt
      set-point in force. The states are the one in force at the onset and one for each timed
      lineup or set-point command after it; a command triggered by an event (a protection request)
      is not applied, which can only turn an asset from active to latent, so a fault is never
      called latent that could act.
    * A fault is active if it can change a tag in at least one of the states: a leak and a sensor
      fault always can; a pump head fault if the pump runs; a forced-open valve (misrouting (a))
      if the valve is not already open; a valve that is stuck nearly closed (misrouting (b)) if the
      valve is open; a restriction in mode ``position_visible`` if the valve is open (its open
      contact changes), and in mode ``obstruction`` if the valve is open and carries flow (the
      receipt valves with a receipt set-point above zero, the outlet and pump valves of a running
      delivery).
    * Valves in parallel (decision D75) are the tank inlet valves among themselves and the tank
      outlet valves among themselves; a valve is on a parallel branch in a state if it is open and
      another valve of its group is open. The two pump branches are never open together in the
      static lineups, so a pump-branch valve is not on a parallel branch.

Source: ``docs/design_decisions.md`` D75 and D76.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from verum.faults import spec as fs

ACTIVE = "active"
LATENT = "latent"
INLETS = ("XV-R101", "XV-R102", "XV-R103")
OUTLETS = ("XV-S101", "XV-S102", "XV-S103")
RECEIPT_VALVES = ("XV-R000", *INLETS)
PUMP_VALVES = {"P-101A": ("XV-PAI", "XV-PAO"), "P-101B": ("XV-PBI", "XV-PBO")}


class Mode(Protocol):
    @property
    def open_valves(self) -> frozenset[str]: ...

    @property
    def running_pumps(self) -> frozenset[str]: ...


@dataclass(frozen=True)
class LineupState:
    open_valves: frozenset[str]
    running_pumps: frozenset[str]
    receipt_setpoint_m3h: float


def lineup_states(
    initial_mode: str,
    initial_setpoint_m3h: float,
    schedule: Sequence[Mapping[str, Any]],
    modes: Mapping[str, Mode],
    onset_s: float,
) -> list[LineupState]:
    """The states from ``onset_s`` on: the one in force then and one per later timed change."""
    mode, setpoint = initial_mode, initial_setpoint_m3h
    timed = sorted((e for e in schedule if "t_s" in e), key=lambda e: float(e["t_s"]))
    states: list[LineupState] = []

    def state() -> LineupState:
        m = modes[mode]
        return LineupState(frozenset(m.open_valves), frozenset(m.running_pumps), setpoint)

    for entry in timed:
        if float(entry["t_s"]) > onset_s and not states:
            states.append(state())
        if entry["command"] == "lineup":
            mode = str(entry["mode"])
        elif entry["command"] == "receipt_setpoint":
            setpoint = float(entry["value_m3h"])
        if float(entry["t_s"]) > onset_s:
            states.append(state())
    return states or [state()]


def _carries_flow(valve: str, st: LineupState) -> bool:
    if valve in RECEIPT_VALVES:
        return st.receipt_setpoint_m3h > 0.0
    if valve in OUTLETS:
        return bool(st.running_pumps)
    return any(valve in PUMP_VALVES[p] for p in st.running_pumps if p in PUMP_VALVES)


def _acts(spec: fs.FaultSpec, st: LineupState) -> bool:
    asset, kind = spec.asset_id, spec.fault_type
    if kind == fs.PUMP:
        return asset in st.running_pumps
    if kind == fs.RESTRICTION:
        if asset not in st.open_valves:
            return False
        return spec.fault_mode == fs.POSITION_VISIBLE or _carries_flow(asset, st)
    if kind == fs.MISROUTING:
        is_open = asset in st.open_valves
        return not is_open if spec.variant == "closed_but_open" else is_open
    return True


def activity(spec: fs.FaultSpec, states: Sequence[LineupState]) -> str:
    """Decision D76: ``active`` if the fault can act in some state from onset, else ``latent``."""
    return ACTIVE if any(_acts(spec, st) for st in states) else LATENT


def on_parallel_branch(valve: str, st: LineupState) -> bool:
    """Decision D75: the valve is open and so is another valve of its group."""
    for group in (INLETS, OUTLETS):
        if valve in group:
            return valve in st.open_valves and any(v in st.open_valves for v in group if v != valve)
    return False
