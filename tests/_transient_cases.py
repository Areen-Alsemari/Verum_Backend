"""Small idealised networks for the transient verification ladder.

Inputs: lengths, bore, heads and velocities. Outputs: ``NetworkDef`` objects and engines built
on them, with a uniform initial state (no steady solve).
Key assumptions: node names follow the conventions of the engine (a tank is ``<name>:outlet_nozzle``
or ``<name>:receipt_nozzle``, a valve ``XV-...``); the properties and wave-speed table come from
the shipped configuration; heads are piezometric.

Source: ``docs/transient_engine.md``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from types import SimpleNamespace

from verum.graph import Lineup
from verum.hydraulics import HydraulicModel
from verum.transient import TransientEngine, TransientSpec
from verum.transient.driver import NetworkDef, ValveEvent

G = 9.80665
D300 = 0.30318
A300 = math.pi * D300**2 / 4


def edge(
    eid: str,
    a: str,
    b: str,
    length: float,
    diameter: float = D300,
    za: float = 0.0,
    zb: float = 0.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        edge_id=eid, from_node=a, to_node=b, length_m=length, inner_diameter_m=diameter,
        z_from_m=za, z_to_m=zb,
    )  # fmt: skip


def reservoir_pipe_valve(
    model: HydraulicModel,
    length: float = 200.0,
    h_res: float = 100.0,
    v0: float = 0.3,
    k_local: float = 0.0,
    friction: bool = False,
    events: tuple[ValveEvent, ...] = (),
    flow_schedule: Callable[[float], float] | None = None,
    speeds: Mapping[int, float] | None = None,
    dt: float = 0.000923,
    delay: float = 0.3,
) -> TransientEngine:
    """Tank T1 - pipe P1 - valve XV-1 - short pipe P2 - tank T2, uniform flow v0, equal heads."""
    q0 = v0 * A300
    hpz = h_res - v0**2 / (2 * G)
    net = NetworkDef(
        edges=(
            edge("P1", "T1:outlet_nozzle", "XV-1", length),
            edge("P2", "XV-1", "T2:receipt_nozzle", 5.0),
        ),
        k={"P1": k_local, "P2": 0.0},
        pumps=(),
        node_z={},
        initial={"P1": (hpz, hpz, q0), "P2": (hpz, hpz, q0)},
    )
    spec = TransientSpec(
        lineup=Lineup(frozenset({"XV-1"}), frozenset()),
        tank_levels_m={"T1": h_res, "T2": h_res},
        valve_events=events,
        flow_schedules={"XV-1": flow_schedule} if flow_schedule else None,
        friction_off=not friction,
        wave_speeds=speeds or {300: 1078.2},
        dt_s=dt,
        check_valve_delay_s=delay,
    )
    return TransientEngine(model, spec, net)


def instant_closure(t: float) -> ValveEvent:
    return ValveEvent("XV-1", t, 0.0, 1e-9)
