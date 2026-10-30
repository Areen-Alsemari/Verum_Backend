"""Lineup context of a fault: whether its asset is active and whether misrouting (b) is eligible.

A fault is active if it can change a tag in at least one lineup state in force from its onset to the
end of the episode, and latent otherwise. Commands triggered by events are not applied, which can
only turn an asset from active to latent, so a fault is never called latent that could act.
Misrouting (b) needs a valve on a parallel branch: a tank inlet valve or outlet valve that is open
while another valve of its group is open.

See D75 and D76.
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
