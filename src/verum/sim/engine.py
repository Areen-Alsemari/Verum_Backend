"""Path-dynamics engine: rigid-column flows and tank volumes over a steady network.

Inputs: a scenario, the lineup table, the hydraulic model, the engine configuration
and a truth sink. Outputs: truth rows written to the sink and an ``EpisodeOutcome``.
Key assumptions:
    * State: tank volumes, valve actuators, the receipt and delivery path flows, the
      running pump (fixed speed, one pump, no start or trip: decision D6), protection
      machines and the operations controller. Pipes are full and incompressible, so pipe
      inventory is constant; the network ledger balances boundary fluxes against tank
      volumes only.
    * The loop advances in steps of at most one time step (D17). Events (commands,
      the end of a valve stroke, a valve crossing the closed threshold, a protection
      threshold crossing) end a step exactly. At one time the order is: commands,
      protection update, valve changes, then the solver step.
    * A single receipt path and a single delivery path are rigid columns (decision D22):
      their flows are states, integrated together with the tank volumes by an implicit
      method (``verum.sim.dynamics``); the steady network solve then runs at the imposed
      flows and the inertial head offsets are added. The 10 barg cap limits the receipt
      drive head, so under the cap or a closing valve the flow decays by inertia.
    * A receipt set-point step changes dQ/dt at the command while the flow is continuous; the
      post-command hydraulics are solved again with the new rate, so the post-event rows carry
      the jump of the inertial offsets (decision D22).
    * A branched lineup (two receipt branches or two suction branches open) has no single
      column. The step falls back to the Phase 3 scheme: Heun on the tank volumes with two
      steady solves, the receipt flow first order, the cap applied in the solve. Such an
      interval is a validity window (decision D25).
    * The downstream factor f_d (decision D23) multiplies the boundary-law coefficient and
      is stored in the hidden truth. The atmosphere stratum (decision D24) sets the
      atmosphere of the solves and the pumping-minimum table.
    * A protection threshold crossing inside a step is located by root-finding on the
      interpolated tank volume and the step is shortened to end on it (decision D26).
    * Gates run during the whole episode: SG0 (pumping-minimum level and the phase and
      NPSH screen while a pump runs), SG1 (mass ledger), SG2 (solver or pump-domain
      failure) and SG3 (healthy envelope, if the scenario asks for it). A failure
      stops the run with a rejection record; nothing is clipped or truncated.
    * Protection signals: the alarm uses the process level (the true level in this phase,
      labelled as such); the high-high trip uses only the independent detector (D33).
    * A checkpoint is a deep copy of the state (the immutable last solve is shared); a
      restarted engine continues bit for bit.

Source: ``docs/design_decisions.md`` D3, D6, D17 to D26;
``revised/01_facility_tanks_topology.md`` sections 6.2 and 6.3.
"""

from __future__ import annotations

import copy
import dataclasses
import heapq
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import brentq

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
    load_boundary_law_coefficient,
    pumping_minimum_level,
)
from verum.hydraulics.pumping_minimum import stratum_filename
from verum.ledger.tank import UNIT_ROUNDOFF
from verum.lineups import LineupTable
from verum.ops import Command, OperationsController
from verum.params import UnresolvedParameter
from verum.protection import (
    ProtectionConfig,
    ProtectionEvent,
    Signals,
    TankProtection,
    load_protection_config,
)
from verum.rng import RandomStreams
from verum.sensors import chain as sensor_chain
from verum.sensors.specs import TagSpec, load_sensor_config
from verum.sim import deadleg
from verum.sim import dynamics as dyn
from verum.sim import rows as rw
from verum.sim import validity as vd
from verum.sim.config import SimConfig
from verum.sim.demand import DemandProcess
from verum.sim.path import LumpedPath, delivery_edges, delivery_path, receipt_edges, receipt_path
from verum.sim.scenario import Scenario
from verum.sim.valves import Valve, make_valve
from verum.tanks import load_tank_geometry
from verum.truth import TruthSink

RANK_COMMAND, RANK_DETECTOR, RANK_VALVE = 0, 1, 2
SOURCE_NODE = "PIPELINE_RECEIPT_BOUNDARY"
BOUNDARY_NODE = "DISTRIBUTION_BOUNDARY"
EVENT_TYPE = {
    "HIGH_ALARM": "alarm", "ALARM_CLEARED": "alarm", "HIGH_HIGH_TRIP": "protection_trip",
    "ISOLATION_REQUESTED": "protection_request",
}  # fmt: skip
COLLAPSE_SAMPLES = 64
DENSE_PER_S = 10
MIN_STEP_S = 1e-9


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


@dataclass(frozen=True)
class LevelChain:
    """The level transmitter of a tank as the alarm sees it (decision D40): the specification
    and the draws of the observation chain, which uses the same streams."""

    spec: TagSpec
    sigma: float
    steps: int
    p_drop: float
    times: np.ndarray
    noise: np.ndarray
    drop: np.ndarray


@dataclass
class Track:
    """Flow of a column since a closing stroke began (for the collapse window)."""

    element: str
    ref_m3s: float
    t90: float | None = None
    t10: float | None = None


@dataclass
class EngineState:
    t: float
    volumes: dict[str, float]
    valves: dict[str, Valve]
    receipt_flow_m3h: float
    receipt_setpoint_m3h: float
    delivery_flow_m3h: float
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
    windows: list[vd.ValidityWindow] = field(default_factory=list)
    open_windows: dict[str, vd.ValidityWindow] = field(default_factory=dict)
    window_counter: int = 0
    events_evaluated: int = 0
    tracks: dict[str, Track] = field(default_factory=dict)
    lt_y: dict[str, float] = field(default_factory=dict)
    lt_visible: dict[str, float | None] = field(default_factory=dict)
    crossings: list[dict[str, Any]] = field(default_factory=list)
    prot_index: dict[str, int] = field(default_factory=dict)
    step_index: int = 0
    started: bool = False
    processed_t: float = -1.0
    iterations: int = 0
    residual_kg_s: float = 0.0
    current: SteadyResult | None = None
    mode: str = "inactive"
    qdot_receipt: float = 0.0
    qdot_delivery: float = 0.0
    rates_stale: bool = False
    edge_heads: dict[str, float] = field(default_factory=dict)
    edge_heads_t: float = 0.0
    dead_edges: frozenset[str] = frozenset()
    detector_due: dict[str, float] = field(default_factory=dict)
    detector_on: list[str] = field(default_factory=list)


@dataclass
class Plan:
    """Which flow paths are active in a step and whether each is a single rigid column."""

    receipt: dyn.ReceiptColumn | None
    delivery: dyn.DeliveryColumn | None
    receipt_branched: bool
    delivery_branched: bool

    @property
    def quasi(self) -> bool:
        return self.receipt_branched or self.delivery_branched


@dataclass(frozen=True)
class Inside:
    """State at a time inside a step, from the dense solution of the integrator."""

    volumes: dict[str, float]
    q_r: float
    q_d: float
    qdot_r: float
    qdot_d: float
    c_r: float
    c_d: float


@dataclass
class Stepped:
    """Result of one integration over [t0, t1]; nothing is committed until accepted."""

    t0: float
    t1: float
    plan: Plan
    volumes: dict[str, float]
    q_r_m3h: float
    q_d_m3h: float
    qdot_r: float
    qdot_d: float
    recv_m3: float
    deliv_m3: float
    new: SteadyResult
    volume_at: Callable[[str, float], float]
    flow_at: Callable[[float], tuple[float, float]] | None
    iterations: int
    residual: float
    inside: Callable[[float], Inside] | None = None


@dataclass(frozen=True)
class EpisodeOutcome:
    rejection: dict[str, Any] | None
    final_t: float
    steps: int
    windows: list[vd.ValidityWindow]
    events_evaluated: int
    crossings: list[dict[str, Any]]
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
        self.model = model.for_stratum(scenario.atmosphere_stratum)
        self.table, self.scenario, self.cfg = table, scenario, config
        self.sink, self.episode_id = sink, episode_id
        self.rho = model.rho
        self.dt = config["time_step_s"]
        self.closed_alpha = model.config["valve_closed_alpha"]
        self.temperature_k = scenario.temperature_c + 273.15
        self.geometry = load_tank_geometry(model.directory)
        self._pconfig = {t: self._protection_config(t) for t in model.topology.tank_ids}
        self._isolation_valves = {t: c.isolation_valves for t, c in self._pconfig.items()}
        self.demand = DemandProcess(
            scenario.demand_process,
            RandomStreams(scenario.seed),
            scenario.duration_s,
            config["demand_sigma_log"],
            config["demand_correlation_time_s"],
            config["demand_factor_min"],
            config["demand_factor_max"],
        )
        self.speeds = vd.wave_speeds(config)
        self._paths: dict[tuple[Any, ...], LumpedPath] = {}
        streams = RandomStreams(scenario.seed)
        self.detector_offset = {
            t: float(streams.stream(f"detector/{t}").normal(0.0, config["detector_offset_sigma_m"]))
            for t in model.topology.tank_ids
        }
        sensors = load_sensor_config(model.directory)
        self._lt = {t: self._level_chain(sensors, streams, t) for t in model.topology.tank_ids}
        self._law_c = load_boundary_law_coefficient(scenario.fitting_profile, model.directory).value
        self.state = state if state is not None else self._initial_state()

    def _level_chain(self, sensors: Any, streams: RandomStreams, tank: str) -> LevelChain:
        spec = sensors.tags[f"LT-{tank[3:]}"]
        assert spec.interval_s
        phase = sensor_chain.sample_phase(spec.tag, spec.interval_s)
        times = np.arange(0.0, self.scenario.duration_s - phase + 1e-9, spec.interval_s) + phase
        return LevelChain(
            spec,
            sensors.sigma("level"),
            int(sensors["adc_steps"]),
            sensors["dropout_probability"],
            times,
            streams.stream(f"sensor/{spec.tag}/noise").standard_normal(len(times)),
            streams.stream(f"sensor/{spec.tag}/dropout").random(len(times)),
        )

    def _protection_config(self, tank: str) -> ProtectionConfig:
        return load_protection_config(self.model.topology, tank, self.model.directory)

    # --- construction ----------
    def _initial_state(self) -> EngineState:
        sc, m = self.scenario, self.model
        mode = self.table.mode(sc.initial_mode)
        tanks = m.topology.tank_ids
        volumes = {t: self.geometry.volume_m3(sc.tank_levels_m[t], self.rho) for t in tanks}
        valves = {
            v: make_valve(v, self.cfg.stroke_time_s(v), self.closed_alpha, v in mode.open_valves)
            for v in rw.VALVES
        }
        protections = {t: TankProtection(self._protection_config(t)) for t in tanks}
        ops = OperationsController(self.table, sc.initial_mode, sc.schedule)
        state = EngineState(
            t=0.0,
            volumes=volumes,
            valves=valves,
            receipt_flow_m3h=sc.receipt_flow_m3h,
            receipt_setpoint_m3h=sc.receipt_setpoint_m3h,
            delivery_flow_m3h=0.0,
            running=frozenset(mode.running_pumps),
            protections=protections,
            ops=ops,
            initial_volume_total=sum(volumes.values()),
            prot_index={t: 0 for t in tanks},
        )
        for command in ops.timed_commands:
            self._push(state, command.t_s, RANK_COMMAND, "command", command)
        for tank, lt in self._lt.items():
            state.lt_y[tank] = self.geometry.level_m(volumes[tank], self.rho)
            state.lt_visible[tank] = None
            for k, t in enumerate(lt.times):
                self._push(state, float(t), RANK_DETECTOR, "lt_sample", (tank, k))
        return state

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

    def _solve(
        self,
        volumes: dict[str, float],
        t: float,
        receipt_m3h: float,
        delivery_m3h: float | None = None,
        offsets: dict[str, float] | None = None,
        apply_cap: bool = True,
        qdot_receipt: float = 0.0,
    ) -> SteadyResult:
        st = self.state
        alphas = {v: valve.alpha(t) for v, valve in st.valves.items()}
        open_valves = {v for v, valve in st.valves.items() if not valve.is_physically_closed(t)}
        partial = {v: a for v, a in alphas.items() if v in open_valves and a < 1.0}
        inputs = SteadyInputs(
            lineup=Lineup(frozenset(open_valves), st.running),
            tank_levels_m=self._levels(volumes),
            scenario=self.scenario.volatility_class,
            temperature_c=self.scenario.temperature_c,
            fitting_profile=self.scenario.fitting_profile,
            receipt=ReceiptBoundary(flow_m3h=receipt_m3h),
            delivery=DeliveryBoundary(law_coefficient_m=self._law_c * self.demand.factor(t)),
            valve_positions=partial,
            warm_start=st.warm,
            imposed_delivery_flow_m3h=delivery_m3h,
            head_offsets_m=offsets or {},
            apply_cap=apply_cap,
            tap_head_offsets_m=self._tap_offsets(t, receipt_m3h, qdot_receipt),
        )
        try:
            result = self.model.solve(inputs)
        except PumpOutsideCurve as exc:
            raise Rejected(
                "SG0", t, "pump_domain", str(exc), None, self.model.config["pump_max_flow_m3h"]
            ) from exc
        except (ConvergenceError, HydraulicsError) as exc:
            raise Rejected("SG2", t, "steady_solve", str(exc), None, None) from exc
        result = self._with_dead_legs(result, volumes, t, open_valves)
        st.warm = dict(result.node_heads_m)
        st.iterations = max(st.iterations, result.iterations)
        st.residual_kg_s = max(st.residual_kg_s, result.max_mass_residual_kg_s)
        return result

    def _with_dead_legs(
        self, result: SteadyResult, volumes: dict[str, float], t: float, open_valves: set[str]
    ) -> SteadyResult:
        """Decision D39: pressures for the segments the steady solve left undetermined."""
        st, m = self.state, self.model
        h_res = m.node_z[BOUNDARY_NODE] + m.config["reservoir_pressure_pa_gauge"] / (m.rho * m.g)
        heads, dead = deadleg.edge_heads(
            m, open_valves, result, self._levels(volumes), h_res, st.edge_heads,
            st.dead_edges, t - st.edge_heads_t, self.cfg["dead_leg_time_constant_s"],
        )  # fmt: skip
        rho_g = m.rho * m.g
        ends = {
            k: v
            for k, v in result.edge_end_pressures_pa_gauge.items()
            if k not in result.dead_edges
        }
        for e in m.topology.edges:
            if e.edge_id not in ends:
                h = heads[e.edge_id]
                ends[e.edge_id] = (rho_g * (h - e.z_from_m), rho_g * (h - e.z_to_m))
        taps, tap_heads = dict(result.tap_pressures_pa_gauge), dict(result.tap_heads_m)
        for node, ref in m.config.tap_reference_edges.items():
            if node not in taps or ref in result.dead_edges:
                taps[node] = rho_g * (heads[ref] - m.node_z[node])
                tap_heads[node] = heads[ref]
        return dataclasses.replace(
            result,
            edge_end_pressures_pa_gauge=ends,
            tap_pressures_pa_gauge=taps,
            tap_heads_m=tap_heads,
            edge_heads_m=heads,
            dead_edges=dead,
        )

    def _tap_offsets(self, t: float, receipt_m3h: float, qdot: float) -> dict[str, float]:
        """Head of the PT-001 tap relative to its node (decision D36), for a single receipt path."""
        st = self.state
        if st.valves["XV-R000"].is_physically_closed(t):
            return {}
        tanks = self._open_tanks("R", t)
        if len(tanks) != 1:
            return {}
        path = self._path("receipt", tanks[0], None, t)
        return {SOURCE_NODE: path.tap_offset(receipt_m3h / 3600.0, qdot)}

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
            if st.t >= end:
                self._close_windows(st.t)
            rejection = None
        except Rejected as exc:
            rejection = exc.record
        return EpisodeOutcome(
            rejection,
            st.t,
            st.step_index,
            list(st.windows),
            st.events_evaluated,
            list(st.crossings),
            dict(st.volumes),
            self._ledger(st.t),
        )

    def _start(self) -> None:
        st = self.state
        st.started = True
        st.current = self._solve(st.volumes, 0.0, st.receipt_flow_m3h)
        st.edge_heads, st.edge_heads_t = dict(st.current.edge_heads_m), 0.0
        st.dead_edges = st.current.dead_edges
        st.delivery_flow_m3h = st.current.pump.flow_m3h if st.current.pump is not None else 0.0
        self._check_pumping_minimum_at(0.0, st.current)
        self._process_time(0.0)

    # --- planning ----------
    def _next_time(self, t: float, end: float) -> float:
        st = self.state
        grid = (math.floor(t / self.dt + 1e-9) + 1) * self.dt
        events = st.queue[0][0] if st.queue else math.inf
        return min(grid, events, end)

    def _open_tanks(self, prefix: str, t: float) -> list[str]:
        st = self.state
        tanks = self.model.topology.tank_ids
        return [k for k in tanks if not st.valves[f"XV-{prefix}{k[3:]}"].is_physically_closed(t)]

    def _lineup(self, t: float) -> Lineup:
        st = self.state
        return Lineup(
            frozenset(v for v, x in st.valves.items() if not x.is_physically_closed(t)), st.running
        )

    def _path(self, kind: str, tank: str, pump: str | None, t: float) -> LumpedPath:
        lineup = self._lineup(t)
        key = (kind, tank, pump, lineup)
        if key not in self._paths:
            profile = self.scenario.fitting_profile
            if kind == "receipt":
                self._paths[key] = receipt_path(self.model, tank, lineup, profile)
            else:
                assert pump is not None
                self._paths[key] = delivery_path(self.model, tank, pump, lineup, profile)
        return self._paths[key]

    def _area(self, tank: str) -> float:
        v = self.state.volumes[tank]
        lo, hi = max(v - 0.5, 0.0), v + 0.5
        return (hi - lo) / (
            self.geometry.level_m(hi, self.rho) - self.geometry.level_m(lo, self.rho)
        )

    def _plan(self, t0: float, t1: float) -> Plan:
        st = self.state
        tm = 0.5 * (t0 + t1)
        chain = not st.valves["XV-R000"].is_physically_closed(tm)
        r_open = self._open_tanks("R", tm) if chain else []
        s_open = self._open_tanks("S", tm)
        pump = next(iter(sorted(st.running)), None)
        leg = ("XV-PAI", "XV-PAO") if pump == "P-101A" else ("XV-PBI", "XV-PBO")
        leg_open = pump is not None and not any(st.valves[v].is_physically_closed(tm) for v in leg)
        receipt = delivery = None
        if len(r_open) == 1:
            receipt = self._receipt_column(r_open[0], tm)
        if len(s_open) == 1 and leg_open and pump is not None:
            delivery = self._delivery_column(s_open[0], pump, tm)
        return Plan(
            receipt, delivery, len(r_open) > 1, leg_open and len(s_open) > 1 and pump is not None
        )

    def _receipt_column(self, tank: str, t: float) -> dyn.ReceiptColumn:
        st, m = self.state, self.model
        level = self.geometry.level_m(st.volumes[tank], self.rho)
        head_cap = m.node_z[SOURCE_NODE] + m.config["receipt_pressure_cap_pa_gauge"] / (m.rho * m.g)
        return dyn.ReceiptColumn(
            self._path("receipt", tank, None, t),
            tank,
            head_cap,
            level,
            self._area(tank),
            self.cfg["receipt_controller_tau_s"],
            st.receipt_setpoint_m3h / 3600.0,
        )

    def _delivery_column(self, tank: str, pump: str, t: float) -> dyn.DeliveryColumn:
        st, m = self.state, self.model
        level = self.geometry.level_m(st.volumes[tank], self.rho)
        reservoir = m.node_z[BOUNDARY_NODE] + m.config["reservoir_pressure_pa_gauge"] / (
            m.rho * m.g
        )
        return dyn.DeliveryColumn(
            self._path("delivery", tank, pump, t),
            tank,
            m.default_pump(),
            reservoir,
            self._law_c,
            level,
            self._area(tank),
            m.config["pump_reference_flow_m3h"],
            self.demand.factor,
        )

    # --- one step ----------
    def _step(self, end: float) -> None:
        st = self.state
        t0 = st.t
        t1 = self._next_time(t0, end)
        stepped = self._integrate(t0, t1)
        landing = self._find_crossing(stepped)
        if landing is not None and landing[0] < t1 - MIN_STEP_S:
            stepped = self._integrate(t0, landing[0])
        self._commit(stepped, landing)

    def _integrate(self, t0: float, t1: float) -> Stepped:
        st = self.state
        st.iterations, st.residual_kg_s = 0, 0.0
        plan = self._plan(t0, t1)
        self._update_branch_windows(plan, t0)
        self._finish_inactive(plan, t0)
        if plan.quasi:
            stepped = self._quasi(t0, t1, plan)
        else:
            stepped = self._inertial(t0, t1, plan)
        stepped.iterations, stepped.residual = st.iterations, st.residual_kg_s
        return stepped

    def _inertial(self, t0: float, t1: float, plan: Plan) -> Stepped:
        st = self.state
        q_r0 = st.receipt_flow_m3h / 3600.0 if plan.receipt is not None else 0.0
        q_d0 = st.delivery_flow_m3h / 3600.0 if plan.delivery is not None else 0.0
        y0 = (q_r0, q_d0, 0.0, 0.0)
        rhs = dyn.make_rhs(plan.receipt, plan.delivery, st.valves)
        if plan.receipt is None and plan.delivery is None:
            y1, qdot_r, qdot_d, dense = y0, 0.0, 0.0, None
        else:
            adv = dyn.advance(
                rhs, t0, t1, y0, self.cfg["integrator_rtol"], self.cfg["integrator_atol_m3s"]
            )
            y1, qdot_r, qdot_d, dense = adv.y1, adv.qdot_r, adv.qdot_d, adv.dense
        volumes = dict(st.volumes)
        if plan.receipt is not None:
            volumes[plan.receipt.tank] += y1[2]
        if plan.delivery is not None:
            volumes[plan.delivery.tank] -= y1[3]
        offsets: dict[str, float] = {}
        if plan.receipt is not None:
            offsets.update(plan.receipt.path.offsets(qdot_r))
        if plan.delivery is not None:
            offsets.update(plan.delivery.path.offsets(qdot_d))
        new = self._solve(
            volumes,
            t1,
            y1[0] * 3600.0,
            y1[1] * 3600.0 if plan.delivery is not None else None,
            offsets,
            apply_cap=False,
            qdot_receipt=qdot_r,
        )
        base = dict(st.volumes)

        def volume_at(tank: str, t: float) -> float:
            if dense is None:
                return base[tank]
            y = dense(t)
            v = base[tank]
            if plan.receipt is not None and plan.receipt.tank == tank:
                v += float(y[2])
            if plan.delivery is not None and plan.delivery.tank == tank:
                v -= float(y[3])
            return v

        def flow_at(t: float) -> tuple[float, float]:
            if dense is None:
                return 0.0, 0.0
            y = dense(t)
            return float(y[0]), float(y[1])

        def inside(t: float) -> Inside:
            if dense is None:
                return Inside(dict(base), 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
            y = dense(t)
            rates = rhs(t, y)
            return Inside(
                {k: volume_at(k, t) for k in base},
                float(y[0]), float(y[1]), rates[0], rates[1], float(y[2]), float(y[3]),
            )  # fmt: skip

        return Stepped(
            t0, t1, plan, volumes, y1[0] * 3600.0, y1[1] * 3600.0, qdot_r, qdot_d,
            y1[2], y1[3], new, volume_at, flow_at, 0, 0.0, inside,
        )  # fmt: skip

    def _quasi(self, t0: float, t1: float, plan: Plan) -> Stepped:
        st = self.state
        assert st.current is not None
        h, s0 = t1 - t0, st.current
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
        new = self._solve(volumes, t1, q1)
        q_d = new.pump.flow_m3h if new.pump is not None else 0.0
        base = dict(st.volumes)
        d1 = new.tank_net_inflow_m3s

        def volume_at(tank: str, t: float) -> float:
            s = (t - t0) / h
            return _hermite(base[tank], volumes[tank], h * f1[tank], h * d1[tank], s)

        return Stepped(
            t0, t1, plan, volumes, q1, q_d, 0.0, 0.0, recv, deliv, new, volume_at, None, 0, 0.0
        )  # fmt: skip

    def _commit(self, step: Stepped, landing: tuple[float, str, str, float] | None) -> None:
        st = self.state
        net = sum(step.volumes.values()) - sum(st.volumes.values())
        base_received, base_delivered = st.cum_received_m3, st.cum_delivered_m3
        st.cum_received_m3 += step.recv_m3
        st.cum_delivered_m3 += step.deliv_m3
        st.ledger_terms += 3
        st.ledger_abs_kg += self.rho * (abs(step.recv_m3) + abs(step.deliv_m3) + abs(net))
        self._track_collapse(step)
        self._advance_level_chain(step)
        st.volumes = step.volumes
        st.receipt_flow_m3h, st.delivery_flow_m3h = step.q_r_m3h, step.q_d_m3h
        st.qdot_receipt, st.qdot_delivery = step.qdot_r, step.qdot_d
        active = step.plan.receipt is not None or step.plan.delivery is not None
        st.mode = "quasi" if step.plan.quasi else ("inertial" if active else "inactive")
        st.t, st.step_index = step.t1, st.step_index + 1
        st.iterations, st.residual_kg_s = step.iterations, step.residual
        self._check_crossing(step.t0, step.t1 - step.t0, st.current, step.new)  # type: ignore[arg-type]
        st.current = step.new
        fresh = step.new.dead_edges - st.dead_edges
        self._finish_inactive(self._plan(step.t1, step.t1), step.t1)
        self._write_interior(step, base_received, base_delivered)
        if fresh:
            # An edge isolated at the end of the step keeps the last head determined inside it.
            open_now = {v for v, x in st.valves.items() if not x.is_physically_closed(step.t1)}
            step.new = self._with_dead_legs(step.new, st.volumes, step.t1, open_now)
            st.current = step.new
        st.edge_heads, st.edge_heads_t = dict(step.new.edge_heads_m), step.t1
        st.dead_edges = step.new.dead_edges
        if landing is not None and abs(landing[0] - step.t1) <= 1e-6:
            self._record_landing(landing)
        self._check_ledger(step.t1)
        self._process_time(step.t1)

    def _advance_level_chain(self, step: Stepped) -> None:
        """Exact first-order lag of each level transmitter over a step of linear input."""
        st, h = self.state, step.t1 - step.t0
        for tank, lt in self._lt.items():
            x0 = self.geometry.level_m(st.volumes[tank], self.rho)
            x1 = self.geometry.level_m(step.volumes[tank], self.rho)
            tau = lt.spec.lag_s
            a, s = math.exp(-h / tau), (x1 - x0) / h
            st.lt_y[tank] = a * st.lt_y[tank] + (1.0 - a) * (x0 - s * tau) + s * h

    def _level_sample(self, tank: str, k: int, t: float) -> None:
        """Sample the transmitter; a kept sample reaches the protection after the comms delay."""
        lt, st = self._lt[tank], self.state
        if lt.drop[k] < lt.p_drop:
            return
        assert lt.spec.range_lo is not None and lt.spec.range_hi is not None
        value = st.lt_y[tank] + float(lt.noise[k]) * lt.sigma
        value, _ = sensor_chain.quantise_clip(
            value, lt.spec.range_lo, lt.spec.range_hi, lt.steps, lt.sigma
        )
        self._push(st, t + lt.spec.comms_delay_s, RANK_DETECTOR, "lt_visible", (tank, value))

    def _dense_needed(self, t0: float, t1: float) -> bool:
        """Decision D34: 0.1 s rows while a valve moves or inside a validity window."""
        st, tm = self.state, 0.5 * (t0 + t1)
        if any(v.is_moving(tm) for v in st.valves.values()):
            return True
        return any(w.t_start_s <= tm and (w.t_end_s is None or tm <= w.t_end_s) for w in st.windows)

    def _write_interior(self, step: Stepped, base_received: float, base_delivered: float) -> None:
        if step.inside is None or getattr(self.sink, "discards", False):
            return
        if not self._dense_needed(step.t0, step.t1):
            return
        plan = step.plan
        first = math.floor(step.t0 * DENSE_PER_S + 1e-9) + 1
        k = first
        while k / DENSE_PER_S < step.t1 - 1e-9:
            t = k / DENSE_PER_S
            k += 1
            if t <= step.t0 + 1e-9 or abs(t - round(t)) < 1e-9:
                continue
            ins = step.inside(t)
            offsets: dict[str, float] = {}
            if plan.receipt is not None:
                offsets.update(plan.receipt.path.offsets(ins.qdot_r))
            if plan.delivery is not None:
                offsets.update(plan.delivery.path.offsets(ins.qdot_d))
            result = self._solve(
                ins.volumes, t, ins.q_r * 3600.0,
                ins.q_d * 3600.0 if plan.delivery is not None else None,
                offsets, apply_cap=False, qdot_receipt=ins.qdot_r,
            )  # fmt: skip
            # The heads of determined edges are the latest known: an edge that is isolated at
            # the end of the step keeps the value from the last row before it (decision D39).
            for edge, head in result.edge_heads_m.items():
                if edge not in result.dead_edges:
                    self.state.edge_heads[edge] = head
            snap = self._snapshot(
                t, result, ins.volumes, (base_received + ins.c_r, base_delivered + ins.c_d)
            )
            self._write_snapshot(snap, None)

    def _record_landing(self, landing: tuple[float, str, str, float]) -> None:
        t, tank, name, thr = landing
        if name == "high_high":
            # The detector asserts here and its output reaches the protection logic after
            # its delay (decision D33); the trip is decided on that signal only.
            due = t + self.cfg["detector_delay_s"]
            self.state.detector_due[tank] = due
            self._push(self.state, due, RANK_DETECTOR, "detector", tank)
            self.state.crossings.append(
                {"t_sim_s": t, "tank": tank, "threshold": name, "level_m": thr}
            )
            return

    # --- D26: protection thresholds located inside the step ----------
    def _candidates(self, tank: str) -> list[tuple[str, float, int]]:
        cfg, state = self._pconfig[tank], self.state.protections[tank].state.value
        out: list[tuple[str, float, int]] = []
        if state in ("NORMAL", "HIGH_ALARM") and tank not in self.state.detector_due:
            # The detector sees level plus its offset: it asserts at this true level.
            out.append(("high_high", cfg.high_high_m - self.detector_offset[tank], 1))
        return out

    def _level_at(self, step: Stepped, tank: str, t: float) -> float:
        return self.geometry.level_m(step.volume_at(tank, t), self.rho)

    def _locate(self, step: Stepped, tank: str, threshold: float) -> float:
        """Time in the step at which the interpolated level of ``tank`` equals ``threshold``."""

        def gap(t: float) -> float:
            return self._level_at(step, tank, t) - threshold

        return float(brentq(gap, step.t0, step.t1, xtol=1e-12))

    def _find_crossing(self, step: Stepped) -> tuple[float, str, str, float] | None:
        best: tuple[float, str, str, float] | None = None
        for tank in self.model.topology.tank_ids:
            l0, l1 = self._level_at(step, tank, step.t0), self._level_at(step, tank, step.t1)
            for name, thr, sign in self._candidates(tank):
                crossed = (l0 < thr <= l1) if sign > 0 else (l0 >= thr > l1)
                if not crossed:
                    continue
                t_c = self._locate(step, tank, thr)
                if best is None or t_c < best[0]:
                    best = (t_c, tank, name, thr)
        if best is not None and best[0] - step.t0 < MIN_STEP_S:
            return None
        return best

    # --- collapse tracking (D22 window for a closing path) ----------
    def _closing_valves(self, names: tuple[str, ...]) -> list[str]:
        return [v for v in names if self.state.valves[v].target < self.state.valves[v].position0]

    def _track_collapse(self, step: Stepped) -> None:
        st = self.state
        if step.flow_at is None:
            return
        for key, col, idx in (
            ("receipt", step.plan.receipt, 0),
            ("delivery", step.plan.delivery, 1),
        ):
            track = st.tracks.get(key)
            if col is None or track is None or not self._closing_valves(col.path.valves()):
                continue
            hi = self.cfg["collapse_high_fraction"] * track.ref_m3s
            lo = self.cfg["collapse_low_fraction"] * track.ref_m3s
            for k in range(COLLAPSE_SAMPLES + 1):
                t = step.t0 + (step.t1 - step.t0) * k / COLLAPSE_SAMPLES
                q = step.flow_at(t)[idx]
                if track.t90 is None and q <= hi:
                    track.t90 = t
                if track.t90 is not None and track.t10 is None and q <= lo:
                    track.t10 = t

    def _finish_inactive(self, plan: Plan, t0: float) -> None:
        """A column that has become inactive stops its flow; close its collapse track."""
        st = self.state
        for key, col, flow_attr in (
            ("receipt", plan.receipt, "receipt_flow_m3h"),
            ("delivery", plan.delivery, "delivery_flow_m3h"),
        ):
            if col is not None or plan.quasi:
                continue
            flow = getattr(st, flow_attr)
            track = st.tracks.pop(key, None)
            if flow > 0.0 and track is not None:
                self._close_track(key, track, flow / 3600.0, t0, plan)
            if not plan.quasi:
                setattr(st, flow_attr, 0.0)

    def _close_track(self, key: str, track: Track, q_at_close: float, t: float, plan: Plan) -> None:
        if track.t90 is None:
            return
        trip = self._round_trip_for(key, track.element, t)
        factor = self.cfg["wave_criterion_factor"]
        if track.t10 is None:
            self._add_window(
                "path_closed", track.element, track.t90, t, vd.REASON_STOPPED, None, trip
            )
            return
        duration = track.t10 - track.t90
        if trip is not None and not vd.is_valid(duration, trip, factor):
            self._add_window(
                "flow_collapse", track.element, track.t90, track.t10, vd.REASON_COLLAPSE,
                vd.ratio(duration, trip), trip,
            )  # fmt: skip

    def _round_trip_for(self, key: str, element: str, t: float) -> float | None:
        edges = self._edges_of(key, element)
        if edges is None:
            return None
        return vd.round_trip_s(self.model, edges, self.speeds)

    def _edges_of(self, key: str, element: str) -> tuple[str, ...] | None:
        st, m = self.state, self.model
        if key == "receipt":
            tank = self._tank_of(element, "XV-R") or next(iter(self._tanks_with("R")), None)
            return receipt_edges(m, tank) if tank else None
        tank = self._tank_of(element, "XV-S") or next(iter(self._tanks_with("S")), None)
        if tank is None:
            return None
        pump = "P-101B" if element in ("XV-PBI", "XV-PBO") else None
        pump = pump or ("P-101B" if "P-101B" in st.running else "P-101A")
        return delivery_edges(m, tank, pump)

    def _tank_of(self, element: str, prefix: str) -> str | None:
        return f"TK-{element[-3:]}" if element.startswith(prefix) and element != "XV-R000" else None

    def _tanks_with(self, prefix: str) -> list[str]:
        return [
            k
            for k in self.model.topology.tank_ids
            if self.state.valves[f"XV-{prefix}{k[3:]}"].commanded_open
            or not self.state.valves[f"XV-{prefix}{k[3:]}"].is_physically_closed(self.state.t)
        ]

    # --- validity windows (D25) ----------
    def _add_window(
        self, kind: str, element: str, t0: float, t1: float | None, reason: str,
        ratio: float | None, trip: float | None,
    ) -> vd.ValidityWindow:  # fmt: skip
        st = self.state
        st.window_counter += 1
        w = vd.ValidityWindow(
            f"VW-{st.window_counter:04d}", kind, element, t0, t1, reason, ratio, trip
        )
        st.windows.append(w)
        if t1 is not None:
            self._write_window(w)
        return w

    def _write_window(self, w: vd.ValidityWindow) -> None:
        row = {
            "schema_version": rw.SCHEMA_VERSION,
            "dataset": "validity_windows",
            "episode_id": self.episode_id,
            **w.as_row(),
            "hidden": True,
        }
        self.sink.write("validity_windows", row)

    def _close_windows(self, t: float) -> None:
        st = self.state
        for key in list(st.open_windows):
            w = st.open_windows.pop(key)
            w.t_end_s = t
            self._write_window(w)

    def _update_branch_windows(self, plan: Plan, t0: float) -> None:
        st = self.state
        for key, branched in (
            ("receipt", plan.receipt_branched),
            ("delivery", plan.delivery_branched),
        ):
            name = f"branched:{key}"
            if branched and name not in st.open_windows:
                w = self._add_window(
                    "branched_lineup", key.upper(), t0, None, vd.REASON_BRANCHED, None, None
                )
                st.open_windows[name] = w
            elif not branched and name in st.open_windows:
                w = st.open_windows.pop(name)
                w.t_end_s = t0
                self._write_window(w)

    def _evaluate_event(
        self,
        kind: str,
        element: str,
        duration: float,
        t: float,
        key: str,
        edges: tuple[str, ...] | None,
    ) -> None:
        if edges is None:
            return
        st = self.state
        trip = vd.round_trip_s(self.model, edges, self.speeds)
        st.events_evaluated += 1
        if not vd.is_valid(duration, trip, self.cfg["wave_criterion_factor"]):
            self._add_window(
                kind, element, t, t + duration, vd.REASON_DURATION, vd.ratio(duration, trip), trip
            )

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
            f"pumping_minimum_level[{tank},{sc.temperature_c:g}C,{sc.fitting_profile},"
            f"NPSH3={c:g}m,{sc.atmosphere_stratum},{sc.volatility_class},f_d=0.8]"
        )
        record = pumping_minimum_level(
            tank,
            sc.temperature_c,
            sc.fitting_profile,
            c,
            self.model.directory,
            stratum_filename(sc.atmosphere_stratum, sc.volatility_class),
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

    def _ledger(
        self,
        t: float,
        volumes: dict[str, float] | None = None,
        cumulative: tuple[float, float] | None = None,
    ) -> dict[str, Any]:
        st, rho = self.state, self.rho
        volumes = st.volumes if volumes is None else volumes
        received, delivered = cumulative or (st.cum_received_m3, st.cum_delivered_m3)
        total = sum(volumes.values())
        residual = rho * (received - delivered - (total - st.initial_volume_total))
        roundoff = (
            max(st.ledger_terms - 1, 0)
            * UNIT_ROUNDOFF
            * (st.ledger_abs_kg + rho * (st.initial_volume_total + total))
        )
        tolerance = self.model.config["mass_conservation_tolerance_kg_s"] * t + roundoff
        return {
            "received_kg": rho * received,
            "delivered_kg": rho * delivered,
            "liquid_total_kg": rho * total,
            "tank_kg": {k: rho * v for k, v in volumes.items()},
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
        # A path that has just closed stops its flow here, so that the window of the collapse
        # exists when this instant is logged and not only from the next step.
        self._finish_inactive(self._plan(t, t), t)
        pre = self._snapshot(t)
        before = st.event_index
        self._run_queue(t, {RANK_COMMAND, RANK_DETECTOR})
        self._protection_update(t)
        self._run_queue(t, {RANK_COMMAND, RANK_VALVE})
        self._refresh_rates(t)
        post = self._snapshot(t)
        self._log(pre, post, st.event_index > before, t)
        st.processed_t = t
        self._check_screen(t, st.current)
        self._check_envelope(t)

    def _refresh_rates(self, t: float) -> None:
        """Decision D22: a set-point step changes dQ/dt at once while the flow is continuous, so
        the inertial head offsets, and with them the pressures, jump at the command. The steady
        solve of the last step carries the rate before the command; it is solved again with the
        rate after it (the post-event rows and the next step start from that solve)."""
        st = self.state
        if not st.rates_stale:
            return
        st.rates_stale = False
        plan = self._plan(t, t)
        if plan.quasi or plan.receipt is None:
            return
        q_r = st.receipt_flow_m3h / 3600.0
        q_d = st.delivery_flow_m3h / 3600.0 if plan.delivery is not None else 0.0
        rates = dyn.make_rhs(plan.receipt, plan.delivery, st.valves)(
            t, np.array([q_r, q_d, 0.0, 0.0])
        )
        offsets = plan.receipt.path.offsets(rates[0])
        if plan.delivery is not None:
            offsets.update(plan.delivery.path.offsets(rates[1]))
        st.current = self._solve(
            st.volumes, t, q_r * 3600.0, q_d * 3600.0 if plan.delivery is not None else None,
            offsets, apply_cap=False, qdot_receipt=rates[0],
        )  # fmt: skip
        st.qdot_receipt, st.qdot_delivery = rates[0], rates[1]

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
        self.sink.write("boundary_state", rw.boundary_row(self.episode_id, snap, side))
        for row in rw.ledger_rows(self.episode_id, snap, side):
            self.sink.write("mass_ledger", row)

    def _boundary(self, t: float) -> dict[str, Any]:
        f = self.demand.factor(t)
        return {
            "demand_process": self.scenario.demand_process,
            "downstream_factor": f,
            "log_downstream_factor": self.demand.unclipped_log(t),
            "boundary_law_coefficient_m": self._law_c * f,
            "reservoir_pressure_pa_gauge": self.model.config["reservoir_pressure_pa_gauge"],
            "atmosphere_stratum": self.scenario.atmosphere_stratum,
            "atmosphere_pa_abs": self.model.patm,
        }

    def _snapshot(
        self,
        t: float,
        result: SteadyResult | None = None,
        volumes: dict[str, float] | None = None,
        cumulative: tuple[float, float] | None = None,
    ) -> rw.Snapshot:
        st = self.state
        assert st.current is not None
        volumes = st.volumes if volumes is None else volumes
        levels = self._levels(volumes)
        valves = {
            v: rw.ValveView(valve.alpha(t), valve.commanded_open, valve.is_physically_closed(t))
            for v, valve in st.valves.items()
        }
        prot = {
            k: (p.state.value, p.trip_latched, levels[k], levels[k] + self.detector_offset[k])
            for k, p in st.protections.items()
        }
        active = tuple(
            w.window_id
            for w in st.windows
            if w.t_start_s <= t and (w.t_end_s is None or t <= w.t_end_s)
        )
        return rw.Snapshot(
            t=t,
            result=result if result is not None else st.current,
            volumes=dict(volumes),
            levels=levels,
            roof={k: self.geometry.roof_state(lv, self.rho) for k, lv in levels.items()},
            valves=valves,
            protection=prot,
            running=st.running,
            iterations=st.iterations,
            max_residual_kg_s=st.residual_kg_s,
            ledger=self._ledger(t, volumes, cumulative),
            window_ids=active,
            mode=st.mode,
            boundary=self._boundary(t),
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
            if kind == "detector":
                st.detector_on.append(payload)
            elif kind == "lt_sample":
                self._level_sample(payload[0], payload[1], t)
            elif kind == "lt_visible":
                st.lt_visible[payload[0]] = payload[1]
            elif kind == "command":
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
        levels = self._levels(st.volumes)
        for tank, machine in st.protections.items():
            level = levels[tank]  # the detector sees the physical level; the alarm sees the LT
            valves = self._isolation_valves[tank]
            closed = {v: st.valves[v].is_physically_closed(t) for v in valves}
            machine.update(
                Signals(
                    t_s=t,
                    process_level_m=st.lt_visible.get(tank),
                    independent_level_m=self._detector_signal(tank, level),
                    closed_confirmed=closed,
                    receipt_flow_m3h=r.receipt_flow_m3h,
                )
            )
            self._consume_protection_events(tank, machine, t)

    def _detector_signal(self, tank: str, level: float) -> float:
        """Decision D33: level plus the fixed offset, asserted only after the detector delay."""
        trip = self._pconfig[tank].high_high_m
        seen = level + self.detector_offset[tank]
        st = self.state
        if tank in st.detector_on and seen >= trip:
            return max(seen, trip)
        if tank in st.detector_on:
            st.detector_on.remove(tank)
            st.detector_due.pop(tank, None)
        return min(seen, math.nextafter(trip, -math.inf))

    def _consume_protection_events(self, tank: str, machine: TankProtection, t: float) -> None:
        st = self.state
        for event in machine.events[st.prot_index[tank] :]:
            self._log_protection(tank, event)
            for command in st.ops.react(event.kind, tank, event.t_s):
                self._push(st, command.t_s, RANK_COMMAND, "command", command)
        st.prot_index[tank] = len(machine.events)

    def _log_protection(self, tank: str, event: ProtectionEvent) -> None:
        etype = EVENT_TYPE.get(event.kind, "protection_state_change")
        payload: dict[str, Any] = {
            "tank": tank,
            "kind": event.kind,
            "detail": event.detail,
            "requested_valves": list(event.requested_valves),
            "signal_source": rw.SIGNAL_SOURCE,
        }
        crossing = next(
            (c for c in self.state.crossings if c["tank"] == tank and c["t_sim_s"] == event.t_s),
            None,
        )
        detector = next(
            (
                c
                for c in self.state.crossings
                if c["tank"] == tank and c["threshold"] == "high_high"
            ),
            None,
        )
        if crossing is not None:
            payload["crossing_located_s"] = crossing["t_sim_s"]
        if detector is not None and event.kind == "HIGH_HIGH_TRIP":
            payload["detector_asserted_s"] = detector["t_sim_s"]
            payload["detector_offset_m"] = self.detector_offset[tank]
        self._emit(event.t_s, etype, "autonomous_protection", tank, payload)

    # --- command execution ----------
    def _execute(self, command: Command, t: float) -> None:
        st = self.state
        if command.kind == "receipt_setpoint":
            assert command.setpoint_m3h is not None
            old, st.receipt_setpoint_m3h = st.receipt_setpoint_m3h, command.setpoint_m3h
            st.rates_stale = old != command.setpoint_m3h
            self._emit(
                t,
                "command",
                "operator",
                "RECEIPT_SETPOINT",
                {"from_m3h": old, "to_m3h": command.setpoint_m3h, "source": command.source},
            )
            if old != command.setpoint_m3h:
                self._evaluate_event(
                    "receipt_setpoint",
                    "RECEIPT_SETPOINT",
                    self.cfg["receipt_event_duration_factor"]
                    * self.cfg["receipt_controller_tau_s"],
                    t,
                    "receipt",
                    self._edges_of("receipt", "XV-R000"),
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
        # Events are judged after every order of the command is applied, so that the
        # path of each event is the one the command is creating.
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
        key = "receipt" if valve.name.startswith("XV-R") else "delivery"
        self._evaluate_event(
            "valve_stroke", valve.name, end - t, t, key, self._edges_of(key, valve.name)
        )
        self._start_track(valve, key)

    def _start_track(self, valve: Valve, key: str) -> None:
        st = self.state
        flow = st.receipt_flow_m3h if key == "receipt" else st.delivery_flow_m3h
        if valve.target < valve.position0 and flow > 0.0:
            st.tracks.setdefault(key, Track(valve.name, flow / 3600.0))
        elif valve.target > valve.position0:
            st.tracks.pop(key, None)


def _hermite(v0: float, v1: float, d0: float, d1: float, s: float) -> float:
    """Cubic Hermite value at fraction s; d0, d1 are slopes times the step."""
    s2, s3 = s * s, s * s * s
    return (
        (2 * s3 - 3 * s2 + 1) * v0
        + (s3 - 2 * s2 + s) * d0
        + (-2 * s3 + 3 * s2) * v1
        + (s3 - s2) * d1
    )


def _hermite_root(v0: float, v1: float, d0: float, d1: float, target: float) -> float:
    """Fraction s in [0, 1] at which the cubic Hermite volume reaches target."""
    lo, hi = 0.0, 1.0
    falling = v1 < v0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        value = _hermite(v0, v1, d0, d1, mid)
        below = value < target if falling else value > target
        lo, hi = (lo, mid) if below else (mid, hi)
    return 0.5 * (lo + hi)
