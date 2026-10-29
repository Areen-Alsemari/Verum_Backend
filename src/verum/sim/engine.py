"""Quasi-steady dynamic engine: tank volumes by Heun's method over a steady network.

Inputs: a scenario, the lineup table, the hydraulic model, the engine configuration
and a truth sink. Outputs: truth rows written to the sink and an ``EpisodeOutcome``.
Key assumptions:
    * State: tank volumes, valve actuators, the receipt flow state, the running pump
      (fixed speed, one pump, no start or trip: decision D6), protection machines and
      the operations controller. Pipes are full and incompressible, so pipe inventory
      is constant; the network ledger therefore balances boundary fluxes against tank
      volumes only.
    * The loop advances in steps of at most one time step (D17). Events (commands,
      the end of a valve stroke, a valve crossing the closed threshold) end a step
      exactly. At one time the order is: commands, protection update, valve changes,
      then the solver step.
    * Each step takes two steady solves (Heun stages); the solve at the start of the
      next step is the state solve at the new time and is shared with it.
    * The receipt flow state follows its set-point with a first-order response,
      advanced exactly; the 10 barg cap clips it inside the steady solve (D3).
    * Gates run during the whole episode: SG0 (pumping-minimum level and the phase and
      NPSH screen while a pump runs), SG1 (mass ledger), SG2 (solver or pump-domain
      failure) and SG3 (healthy envelope, if the scenario asks for it). A failure
      stops the run with a rejection record; nothing is clipped or truncated.
    * Protection signals are the true level and the true flow, tagged
      ``truth_placeholder``; no module outside the engine may consume that tag.
    * Quasi-steady validity (D18) is computed for every event and reported, not enforced.
    * A checkpoint is a deep copy of the state (the immutable last solve is shared); a
      restarted engine continues bit for bit.

Source: ``docs/design_decisions.md`` D3, D6, D17 to D21;
``revised/01_facility_tanks_topology.md`` sections 6.2 and 6.3.
"""

from __future__ import annotations

import copy
import heapq
import math
from dataclasses import dataclass, field
from typing import Any

from verum.graph import Lineup
from verum.hydraulics import (
    ConvergenceError,
    DeliveryBoundary,
    HydraulicModel,
    HydraulicsError,
    PumpOutsideCurve,
    ReceiptBoundary,
    SteadyInputs,
    SteadyResult,
    pumping_minimum_level,
)
from verum.ledger.tank import UNIT_ROUNDOFF
from verum.lineups import LineupTable
from verum.ops import Command, OperationsController
from verum.params import UnresolvedParameter
from verum.protection import ProtectionEvent, Signals, TankProtection, load_protection_config
from verum.sim import rows as rw
from verum.sim import validity
from verum.sim.config import SimConfig
from verum.sim.scenario import Scenario
from verum.sim.valves import Valve, make_valve
from verum.truth import TruthSink

SCENARIO_NAME = "EPA_GENERIC_RVP10_REFERENCE"
RANK_COMMAND, RANK_VALVE = 0, 2
EVENT_TYPE = {
    "HIGH_ALARM": "alarm", "ALARM_CLEARED": "alarm", "HIGH_HIGH_TRIP": "protection_trip",
    "ISOLATION_REQUESTED": "protection_request",
}  # fmt: skip


class Rejected(Exception):
    """A gate failed; carries the rejection record."""

    def __init__(
        self,
        gate: str,
        t_s: float,
        parameter: str,
        detail: str,
        value: float | None,
        limit: float | None,
    ):
        super().__init__(f"{gate} at {t_s:g} s: {parameter}: {detail}")
        self.record = {
            "gate": gate,
            "t_sim_s": t_s,
            "parameter": parameter,
            "detail": detail,
            "value": value,
            "limit": limit,
        }


@dataclass
class Window:
    event_id: str
    kind: str
    element_id: str
    t_start: float
    duration_s: float
    tau_s: float
    ratio: float | None
    invalid: bool

    def view(self) -> rw.WindowView:
        return rw.WindowView(
            self.event_id,
            self.kind,
            self.element_id,
            self.duration_s,
            self.tau_s,
            self.ratio,
            self.invalid,
        )


@dataclass
class EngineState:
    t: float
    volumes: dict[str, float]
    valves: dict[str, Valve]
    receipt_flow_m3h: float
    receipt_setpoint_m3h: float
    running: frozenset[str]
    protections: dict[str, TankProtection]
    ops: OperationsController
    initial_volume_total: float
    queue: list[tuple[float, int, int, str, Any]] = field(default_factory=list)
    seq: int = 0
    event_index: int = 0
    cum_received_m3: float = 0.0
    cum_delivered_m3: float = 0.0
    ledger_terms: int = 0
    ledger_abs_kg: float = 0.0
    warm: dict[str, float] | None = None
    windows: list[Window] = field(default_factory=list)
    window_counter: int = 0
    prot_index: dict[str, int] = field(default_factory=dict)
    step_index: int = 0
    started: bool = False
    processed_t: float = -1.0
    iterations: int = 0
    residual_kg_s: float = 0.0
    current: SteadyResult | None = None
    started_now: list[Window] = field(default_factory=list)
    receipt_reference_m3h: float = 0.0


@dataclass
class EpisodeOutcome:
    rejection: dict[str, Any] | None
    final_t: float
    steps: int
    windows: list[Window]
    final_volumes: dict[str, float]
    ledger: dict[str, Any]


class Engine:
    def __init__(
        self,
        model: HydraulicModel,
        table: LineupTable,
        scenario: Scenario,
        config: SimConfig,
        sink: TruthSink,
        episode_id: str,
        state: EngineState | None = None,
    ) -> None:
        self.model, self.table, self.scenario, self.cfg = model, table, scenario, config
        self.sink, self.episode_id = sink, episode_id
        self.rho = model.rho
        self.dt = config["time_step_s"]
        self.closed_alpha = model.config["valve_closed_alpha"]
        self.temperature_k = scenario.temperature_c + 273.15
        self.state = state if state is not None else self._initial_state()

    # --- construction ----------
    def _initial_state(self) -> EngineState:
        sc, m = self.scenario, self.model
        mode = self.table.mode(sc.initial_mode)
        tanks = m.topology.tank_ids
        from verum.tanks import load_tank_geometry

        self.geometry = load_tank_geometry(m.directory)
        volumes = {t: self.geometry.volume_m3(sc.tank_levels_m[t], self.rho) for t in tanks}
        valves = {
            v: make_valve(v, self.cfg.stroke_time_s(v), self.closed_alpha, v in mode.open_valves)
            for v in rw.VALVES
        }
        protections = {
            t: TankProtection(load_protection_config(m.topology, t, m.directory)) for t in tanks
        }
        ops = OperationsController(self.table, sc.initial_mode, sc.schedule)
        state = EngineState(
            t=0.0,
            volumes=volumes,
            valves=valves,
            receipt_flow_m3h=sc.receipt_flow_m3h,
            receipt_setpoint_m3h=sc.receipt_setpoint_m3h,
            running=frozenset(mode.running_pumps),
            protections=protections,
            ops=ops,
            initial_volume_total=sum(volumes.values()),
            prot_index={t: 0 for t in tanks},
            receipt_reference_m3h=max(sc.receipt_flow_m3h, sc.receipt_setpoint_m3h),
        )
        for command in ops.timed_commands:
            self._push(state, command.t_s, RANK_COMMAND, "command", command)
        return state

    @property
    def geometry(self):  # type: ignore[no-untyped-def]
        return self._geometry

    @geometry.setter
    def geometry(self, value) -> None:  # type: ignore[no-untyped-def]
        self._geometry = value

    @staticmethod
    def _push(state: EngineState, t: float, rank: int, kind: str, payload: Any) -> None:
        state.seq += 1
        heapq.heappush(state.queue, (t, rank, state.seq, kind, payload))

    def checkpoint(self) -> EngineState:
        memo: dict[int, Any] = {}
        if self.state.current is not None:
            memo[id(self.state.current)] = self.state.current
        return copy.deepcopy(self.state, memo)

    # --- steady solve ----------
    def _levels(self, volumes: dict[str, float]) -> dict[str, float]:
        return {t: self.geometry.level_m(v, self.rho) for t, v in volumes.items()}

    def _solve(self, volumes: dict[str, float], t: float, receipt_m3h: float) -> SteadyResult:
        st = self.state
        alphas = {v: valve.alpha(t) for v, valve in st.valves.items()}
        open_valves = {v for v, valve in st.valves.items() if not valve.is_physically_closed(t)}
        partial = {v: a for v, a in alphas.items() if v in open_valves and a < 1.0}
        inputs = SteadyInputs(
            lineup=Lineup(frozenset(open_valves), st.running),
            tank_levels_m=self._levels(volumes),
            scenario=SCENARIO_NAME,
            temperature_c=self.scenario.temperature_c,
            fitting_profile=self.scenario.fitting_profile,
            receipt=ReceiptBoundary(flow_m3h=receipt_m3h),
            delivery=DeliveryBoundary(),
            valve_positions=partial,
            warm_start=st.warm,
        )
        try:
            result = self.model.solve(inputs)
        except PumpOutsideCurve as exc:
            raise Rejected(
                "SG0", t, "pump_domain", str(exc), None, self.model.config["pump_max_flow_m3h"]
            ) from exc
        except (ConvergenceError, HydraulicsError) as exc:
            raise Rejected("SG2", t, "steady_solve", str(exc), None, None) from exc
        st.warm = dict(result.node_heads_m)
        st.iterations = max(st.iterations, result.iterations)
        st.residual_kg_s = max(st.residual_kg_s, result.max_mass_residual_kg_s)
        return result

    # --- run loop ----------
    def run(self, until: float | None = None) -> EpisodeOutcome:
        st, end = self.state, self.scenario.duration_s
        try:
            if not st.started:
                self._start()
            while st.t < end:
                if until is not None and st.t >= until:
                    break
                self._step(end)
            rejection = None
        except Rejected as exc:
            rejection = exc.record
        return EpisodeOutcome(
            rejection, st.t, st.step_index, list(st.windows), dict(st.volumes), self._ledger(st.t)
        )

    def _start(self) -> None:
        st = self.state
        st.started = True
        st.current = self._solve(st.volumes, 0.0, st.receipt_flow_m3h)
        self._check_pumping_minimum_at(0.0, st.current)
        self._process_time(0.0)

    # --- one step ----------
    def _next_time(self, t: float, end: float) -> float:
        st = self.state
        grid = (math.floor(t / self.dt + 1e-9) + 1) * self.dt
        events = st.queue[0][0] if st.queue else math.inf
        return min(grid, events, end)

    def _step(self, end: float) -> None:
        st = self.state
        assert st.current is not None
        t0, s0 = st.t, st.current
        t1 = self._next_time(t0, end)
        h = t1 - t0
        tau_c = self.cfg["receipt_controller_tau_s"]
        q1 = st.receipt_setpoint_m3h + (st.receipt_flow_m3h - st.receipt_setpoint_m3h) * math.exp(
            -h / tau_c
        )
        f1 = s0.tank_net_inflow_m3s
        predictor = {k: v + h * f1[k] for k, v in st.volumes.items()}
        s2 = self._solve(predictor, t1, q1)
        f2 = s2.tank_net_inflow_m3s
        volumes = {k: v + 0.5 * h * (f1[k] + f2[k]) for k, v in st.volumes.items()}
        recv = 0.5 * h * (s0.edge_flows_m3s["E001"] + s2.edge_flows_m3s["E001"])
        deliv = 0.5 * h * (s0.edge_flows_m3s["E-D2"] + s2.edge_flows_m3s["E-D2"])
        net = sum(volumes.values()) - sum(st.volumes.values())
        st.cum_received_m3 += recv
        st.cum_delivered_m3 += deliv
        st.ledger_terms += 3
        st.ledger_abs_kg += self.rho * (abs(recv) + abs(deliv) + abs(net))
        st.volumes, st.receipt_flow_m3h = volumes, q1
        st.t, st.step_index = t1, st.step_index + 1
        st.iterations, st.residual_kg_s = 0, 0.0
        new = self._solve(volumes, t1, q1)
        self._check_crossing(t0, h, s0, new)
        st.current = new
        self._check_ledger(t1)
        self._process_time(t1)

    # --- gates ----------
    def _delivering_tank(self, t: float, result: SteadyResult) -> str | None:
        st = self.state
        if not st.running or result.pump is None:
            return None
        for tank in self.model.topology.tank_ids:
            if not st.valves[f"XV-S{tank[3:]}"].is_physically_closed(t):
                return tank
        return None

    def _minimum_level(self, tank: str) -> tuple[float | None, str]:
        c = self.model.config["npsh3_coefficient_m"]
        sc = self.scenario
        label = (
            f"pumping_minimum_level[{tank},{sc.temperature_c:g}C,{sc.fitting_profile},NPSH3={c:g}m]"
        )
        record = pumping_minimum_level(
            tank,
            self.scenario.temperature_c,
            self.scenario.fitting_profile,
            c,
            self.model.directory,
        )
        try:
            return record.value, label
        except UnresolvedParameter:
            return None, label

    def _check_pumping_minimum_at(self, t: float, result: SteadyResult) -> None:
        tank = self._delivering_tank(t, result)
        if tank is None:
            return
        minimum, label = self._minimum_level(tank)
        level = self.geometry.level_m(self.state.volumes[tank], self.rho)
        if minimum is None:
            raise Rejected(
                "SG0", t, label, "no level in the normal range passes the screen", level, None
            )
        if level < minimum:
            raise Rejected(
                "SG0",
                t,
                label,
                f"level {level:.4f} m is below the pumping minimum {minimum:.4f} m",
                level,
                minimum,
            )

    def _check_crossing(self, t0: float, h: float, s0: SteadyResult, s1: SteadyResult) -> None:
        st = self.state
        tank = self._delivering_tank(st.t, s1) or self._delivering_tank(t0, s0)
        if tank is None:
            return
        minimum, label = self._minimum_level(tank)
        if minimum is None:
            raise Rejected(
                "SG0", t0, label, "no level in the normal range passes the screen", None, None
            )
        level1 = self.geometry.level_m(st.volumes[tank], self.rho)
        if level1 >= minimum:
            return
        v1 = st.volumes[tank]
        v0 = v1 - 0.5 * h * (s0.tank_net_inflow_m3s[tank] + s1.tank_net_inflow_m3s[tank])
        target = self.geometry.volume_m3(minimum, self.rho)
        t_cross = t0 + h * _hermite_root(
            v0, v1, h * s0.tank_net_inflow_m3s[tank], h * s1.tank_net_inflow_m3s[tank], target
        )
        raise Rejected(
            "SG0",
            t_cross,
            label,
            f"level crossed the pumping minimum {minimum:.4f} m",
            minimum,
            minimum,
        )

    def _ledger(self, t: float) -> dict[str, Any]:
        st, rho = self.state, self.rho
        total = sum(st.volumes.values())
        residual = rho * (
            st.cum_received_m3 - st.cum_delivered_m3 - (total - st.initial_volume_total)
        )
        roundoff = (
            max(st.ledger_terms - 1, 0)
            * UNIT_ROUNDOFF
            * (st.ledger_abs_kg + rho * (st.initial_volume_total + total))
        )
        tolerance = self.model.config["mass_conservation_tolerance_kg_s"] * t + roundoff
        return {
            "received_kg": rho * st.cum_received_m3,
            "delivered_kg": rho * st.cum_delivered_m3,
            "liquid_total_kg": rho * total,
            "tank_kg": {k: rho * v for k, v in st.volumes.items()},
            "residual_kg": residual,
            "tolerance_kg": tolerance,
            "closed": abs(residual) <= tolerance,
        }

    def _check_ledger(self, t: float) -> None:
        led = self._ledger(t)
        if not led["closed"]:
            raise Rejected(
                "SG1",
                t,
                "mass_ledger_residual",
                f"residual {led['residual_kg']:.6g} kg",
                led["residual_kg"],
                led["tolerance_kg"],
            )

    def _check_envelope(self, t: float) -> None:
        if not self.scenario.healthy_envelope:
            return
        st = self.state
        for tank, v in st.volumes.items():
            level = self.geometry.level_m(v, self.rho)
            if not 1.8 <= level <= 12.0:
                raise Rejected(
                    "SG3",
                    t,
                    f"level[{tank}]",
                    f"level {level:.4f} m outside 1.8 to 12 m",
                    level,
                    12.0 if level > 12 else 1.8,
                )
        for tank, p in st.protections.items():
            if p.state.value != "NORMAL":
                raise Rejected(
                    "SG3",
                    t,
                    f"protection_state[{tank}]",
                    f"protection is {p.state.value}",
                    None,
                    None,
                )

    def _check_screen(self, t: float, result: SteadyResult) -> None:
        pump = result.pump
        if pump is not None and pump.status == "OK" and result.phase.status != "OK":
            raise Rejected(
                "SG0",
                t,
                "phase_validity_status",
                f"{result.phase.status}",
                result.phase.npsha_m,
                result.phase.npsh3_m,
            )

    # --- events at one time ----------
    def _process_time(self, t: float) -> None:
        st = self.state
        assert st.current is not None
        if st.processed_t == t:
            return
        pre = self._snapshot(t, ())
        before = st.event_index
        st.started_now = []
        self._run_queue(t, {RANK_COMMAND})
        self._protection_update(t)
        self._run_queue(t, {RANK_COMMAND, RANK_VALVE})
        post = self._snapshot(t, tuple(w.view() for w in st.started_now))
        self._log(pre, post, st.event_index > before, t)
        st.processed_t = t
        self._check_screen(t, st.current)
        self._check_envelope(t)

    def _log(self, pre: rw.Snapshot, post: rw.Snapshot, event: bool, t: float) -> None:
        is_grid = abs(t / self.dt - round(t / self.dt)) < 1e-9 or t >= self.scenario.duration_s
        if event:
            self._write_snapshot(pre, "pre_event")
            self._write_snapshot(post, "post_event")
        elif is_grid:
            self._write_snapshot(post, None)

    def _write_snapshot(self, snap: rw.Snapshot, side: str | None) -> None:
        if getattr(self.sink, "discards", False):
            return
        for row in rw.hydraulic_rows(self.model, self.episode_id, snap, side, self.temperature_k):
            self.sink.write("hydraulic_state", row)
        self.sink.write("solver_diagnostics", rw.diagnostic_row(self.episode_id, snap, side))
        for row in rw.ledger_rows(self.episode_id, snap, side):
            self.sink.write("mass_ledger", row)

    def _snapshot(self, t: float, started: tuple[rw.WindowView, ...]) -> rw.Snapshot:
        st = self.state
        assert st.current is not None
        levels = self._levels(st.volumes)
        valves = {
            v: rw.ValveView(valve.alpha(t), valve.commanded_open, valve.is_physically_closed(t))
            for v, valve in st.valves.items()
        }
        prot = {k: (p.state.value, p.trip_latched, levels[k]) for k, p in st.protections.items()}
        active = tuple(w.view() for w in st.windows if w.t_start <= t <= w.t_start + w.duration_s)
        return rw.Snapshot(
            t=t,
            result=st.current,
            volumes=dict(st.volumes),
            levels=levels,
            roof={k: self.geometry.roof_state(lv, self.rho) for k, lv in levels.items()},
            valves=valves,
            protection=prot,
            running=st.running,
            iterations=st.iterations,
            max_residual_kg_s=st.residual_kg_s,
            ledger=self._ledger(t),
            active_windows=active,
            started_windows=started,
        )

    def _emit(
        self, t: float, event_type: str, actor: str, asset: str, payload: dict[str, Any]
    ) -> None:
        st = self.state
        row = {
            "schema_version": rw.SCHEMA_VERSION,
            "dataset": "events",
            "episode_id": self.episode_id,
            "sequence_index": st.event_index,
            "t_sim_s": t,
            "event_type": event_type,
            "actor": actor,
            "asset_id": asset,
            "payload": payload,
            "hidden": True,
        }
        st.event_index += 1
        self.sink.write("events", row)

    def _run_queue(self, t: float, ranks: set[int]) -> None:
        st = self.state
        while st.queue and st.queue[0][0] == t and st.queue[0][1] in ranks:
            _, _, _, kind, payload = heapq.heappop(st.queue)
            if kind == "command":
                self._execute(payload, t)
            elif kind == "valve_end":
                self._emit(
                    t,
                    "valve_move",
                    "simulator_truth",
                    payload,
                    {"phase": "end", "position_frac": st.valves[payload].alpha(t)},
                )
            elif kind == "threshold":
                valve = st.valves[payload]
                closing = valve.target < valve.position0
                self._emit(
                    t,
                    "valve_move",
                    "simulator_truth",
                    payload,
                    {
                        "phase": "physical_closed" if closing else "physical_open",
                        "position_frac": valve.alpha(t),
                    },
                )

    def _protection_update(self, t: float) -> None:
        st = self.state
        assert st.current is not None
        r = st.current
        for tank, machine in st.protections.items():
            level = self._levels(st.volumes)[tank]
            valves = machine._config.isolation_valves  # noqa: SLF001 - evidence names only
            closed = {v: st.valves[v].is_physically_closed(t) for v in valves}
            machine.update(
                Signals(
                    t_s=t,
                    process_level_m=level,
                    independent_level_m=level,
                    closed_confirmed=closed,
                    receipt_flow_m3h=r.receipt_flow_m3h,
                )
            )
            self._consume_protection_events(tank, machine, t)

    def _consume_protection_events(self, tank: str, machine: TankProtection, t: float) -> None:
        st = self.state
        for event in machine.events[st.prot_index[tank] :]:
            self._log_protection(tank, event)
            for command in st.ops.react(event.kind, tank, event.t_s):
                self._push(st, command.t_s, RANK_COMMAND, "command", command)
        st.prot_index[tank] = len(machine.events)

    def _log_protection(self, tank: str, event: ProtectionEvent) -> None:
        etype = EVENT_TYPE.get(event.kind, "protection_state_change")
        payload = {
            "tank": tank,
            "kind": event.kind,
            "detail": event.detail,
            "requested_valves": list(event.requested_valves),
            "signal_source": rw.SIGNAL_SOURCE,
        }
        self._emit(event.t_s, etype, "autonomous_protection", tank, payload)

    # --- command execution ----------
    def _execute(self, command: Command, t: float) -> None:
        st = self.state
        if command.kind == "receipt_setpoint":
            assert command.setpoint_m3h is not None
            old, st.receipt_setpoint_m3h = st.receipt_setpoint_m3h, command.setpoint_m3h
            st.receipt_reference_m3h = max(st.receipt_reference_m3h, command.setpoint_m3h)
            self._emit(
                t,
                "command",
                "operator",
                "RECEIPT_SETPOINT",
                {"from_m3h": old, "to_m3h": command.setpoint_m3h, "source": command.source},
            )
            if old != command.setpoint_m3h:
                self._open_window(
                    "receipt_setpoint",
                    "RECEIPT_SETPOINT",
                    self.cfg["receipt_event_duration_factor"]
                    * self.cfg["receipt_controller_tau_s"],
                    t,
                    None,
                )
            return
        valve_open = {v: valve.commanded_open for v, valve in st.valves.items()}
        before = st.ops.lineup.current
        orders = st.ops.resolve(command, valve_open, st.running)
        if command.kind == "lineup":
            self._emit(
                t,
                "lineup_change",
                "operator",
                "LINEUP",
                {"from": before, "to": st.ops.lineup.current, "source": command.source},
            )
        started: list[tuple[Valve, float]] = []
        for order in orders:
            valve = st.valves[order.valve]
            self._emit(
                t,
                "command",
                "operator",
                order.valve,
                {"open": order.open, "source": command.source},
            )
            start_alpha = valve.alpha(t)
            if valve.order(order.open, t):
                started.append((valve, start_alpha))
        # Windows are opened after every order of the command is applied, so that the
        # path of each event is judged with the lineup the command is creating.
        for valve, start_alpha in started:
            self._start_motion(valve, start_alpha, t)

    def _start_motion(self, valve: Valve, start_alpha: float, t: float) -> None:
        end = valve.motion_end_s()
        self._emit(
            t,
            "valve_move",
            "simulator_truth",
            valve.name,
            {
                "phase": "start",
                "from_frac": start_alpha,
                "to_frac": valve.target,
                "stroke_s": valve.stroke_s,
            },
        )
        self._push(self.state, end, RANK_VALVE, "valve_end", valve.name)
        crossing = valve.threshold_time_s()
        if crossing is not None:
            self._push(self.state, crossing, RANK_VALVE, "threshold", valve.name)
        self._open_window("valve_stroke", valve.name, end - t, t, valve.name)

    # --- D18 windows ----------
    def _open_window(
        self, kind: str, element: str, duration: float, t: float, valve: str | None
    ) -> None:
        st = self.state
        assert st.current is not None
        path = self._path_for(valve, t)
        if path is None:
            return
        edges, flow_m3s, law = path
        tau = validity.rigid_column_tau(
            self.model, edges, flow_m3s, self.scenario.fitting_profile, law
        )
        factor = self.cfg["quasi_steady_factor"]
        st.window_counter += 1
        window = Window(
            f"EV-{st.window_counter:04d}",
            kind,
            element,
            t,
            duration,
            tau.tau_s,
            validity.ratio(duration, tau.tau_s),
            not validity.is_valid(duration, tau.tau_s, factor),
        )
        st.windows.append(window)
        st.started_now.append(window)

    def _path_for(self, valve: str | None, t: float) -> tuple[tuple[str, ...], float, float] | None:
        st = self.state
        assert st.current is not None
        topo = self.model.topology
        receiving = next(
            (
                k
                for k in topo.tank_ids
                if not st.valves[f"XV-R{k[3:]}"].is_physically_closed(t)
                or st.valves[f"XV-R{k[3:]}"].commanded_open
            ),
            None,
        )
        if valve is None or valve == "XV-R000" or valve.startswith("XV-R"):
            tank = f"TK-{valve[-3:]}" if valve and valve != "XV-R000" else receiving
            q0 = (
                max(st.receipt_flow_m3h, st.receipt_setpoint_m3h, st.receipt_reference_m3h) / 3600.0
            )
            return validity.receipt_path(topo, tank), q0, 0.0
        pump = (
            "P-101B"
            if valve in ("XV-PBI", "XV-PBO")
            or (valve not in ("XV-PAI", "XV-PAO") and "P-101B" in st.running)
            else "P-101A"
        )
        tank_name = (
            f"TK-{valve[-3:]}"
            if valve.startswith("XV-S")
            else next((k for k in topo.tank_ids if st.valves[f"XV-S{k[3:]}"].commanded_open), None)
        )
        if tank_name is None:
            return None
        ref = self.model.config["pump_reference_flow_m3h"]
        point = st.current.pump
        q0 = (point.flow_m3h if point is not None and point.flow_m3h > 0 else ref) / 3600.0
        c = self._law_coefficient()
        return validity.delivery_path(topo, tank_name, pump), q0, c

    def _law_coefficient(self) -> float:
        from verum.hydraulics import load_boundary_law_coefficient

        return load_boundary_law_coefficient(
            self.scenario.fitting_profile, self.model.directory
        ).value


def _hermite_root(v0: float, v1: float, d0: float, d1: float, target: float) -> float:
    """Fraction s in [0, 1] at which the cubic Hermite volume reaches ``target``."""

    def value(s: float) -> float:
        s2, s3 = s * s, s * s * s
        return (
            (2 * s3 - 3 * s2 + 1) * v0
            + (s3 - 2 * s2 + s) * d0
            + (-2 * s3 + 3 * s2) * v1
            + (s3 - s2) * d1
        )

    lo, hi = 0.0, 1.0
    falling = v1 < v0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        below = value(mid) < target if falling else value(mid) > target
        lo, hi = (lo, mid) if below else (mid, hi)
    return 0.5 * (lo + hi)
