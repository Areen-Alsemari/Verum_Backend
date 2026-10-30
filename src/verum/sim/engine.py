"""Path-dynamics engine: rigid-column flows and tank volumes over a steady network.

- State: tank volumes, valve actuators, path flows, the running pump, the protection machines and
  the operations controller.
- A step is at most one time step long, and events end a step exactly.
- The receipt and delivery paths are rigid columns integrated with the tank volumes, and the steady
  solve then runs at the imposed flows.
- A restarted engine continues bit for bit from a checkpoint.

See D6 and D17 to D26.
"""

from __future__ import annotations

import copy
import dataclasses
import heapq
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
from scipy.optimize import brentq

from verum.graph import Lineup
from verum.hydraulics import (
    ConvergenceError,
    DeliveryBoundary,
    HydraulicModel,
    HydraulicsError,
    LeakError,
    LeakInput,
    PumpOutsideCurve,
    ReceiptBoundary,
    SteadyInputs,
    SteadyResult,
    load_boundary_law_coefficient,
    pumping_minimum_level,
)
from verum.hydraulics.pump import FixedSpeedPump
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
from verum.sim.path import (
    LeakLayout,
    LumpedPath,
    delivery_edges,
    delivery_path,
    receipt_edges,
    receipt_path,
)
from verum.sim.scenario import Scenario
from verum.sim.valves import OpeningModifier, Valve, make_valve
from verum.sim.variability import (
    Redraw,
    Regime,
    RegimeDemand,
    RegimeDrawer,
    SetpointDeviation,
    check_receipt_headroom,
)
from verum.tanks import load_tank_geometry
from verum.tanks.envelope import HeadroomScreen, LevelEnvelope
from verum.tanks.geometry import load_tank_parameters
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
STROKE_JUDGED_AT = 0.2  # opening at which a closing stroke is judged (decision D58 v2)


class FaultInjection(Protocol):
    """What the engine asks of a fault set: physical parameters as functions of time."""

    def leaks(self, t: float) -> tuple[LeakInput, ...]: ...

    def valve_fault(self, valve: str) -> OpeningModifier | None: ...

    def pump_scale(self, t: float, pump: str) -> float: ...

    def knot_times(self, closed_alpha: float) -> tuple[float, ...]: ...


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
    """The level transmitter of a tank as the alarm sees it: the specification and the draws of the
    observation chain, which uses the same streams.
    """

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
    cum_spilled_m3: float = 0.0
    pending_strokes: dict[str, tuple[float, float, str, tuple[str, ...]]] = field(
        default_factory=dict
    )  # closing strokes waiting for the flow at opening 0.2 (decision D58 version 2)
    leak_flows: dict[str, float] = field(default_factory=dict)
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
    regimes: list[Regime] = field(default_factory=list)  # profile v2, decision D73
    regime_redraws: list[Redraw] = field(default_factory=list)


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
    spill_m3: float = 0.0
    leaks: tuple[float, float, float] = (0.0, 0.0, 0.0)  # receipt, suction, discharge (m3/s)


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
    regimes: list[dict[str, Any]] = field(default_factory=list)
    regime_redraws: list[dict[str, Any]] = field(default_factory=list)


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
        faults: FaultInjection | None = None,
    ) -> None:
        self.faults = faults
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
        ou = DemandProcess(
            scenario.demand_process,
            RandomStreams(scenario.seed),
            scenario.duration_s,
            config["demand_sigma_log"],
            config["demand_correlation_time_s"],
            config["demand_factor_min"],
            config["demand_factor_max"],
        )
        self.demand: DemandProcess | RegimeDemand = ou
        self.setpoint_dev: SetpointDeviation | None = None
        self._drawer: RegimeDrawer | None = None
        if scenario.variability_profile == "v2":
            self._init_profile_v2(ou)
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

    def _init_profile_v2(self, ou: DemandProcess) -> None:
        """Decision D73: demand regimes on top of the OU factor and a receipt set-point process."""
        sc, cfg = self.scenario, self.cfg
        self._drawer = RegimeDrawer(sc.seed, cfg)
        self.demand = RegimeDemand(
            ou,
            cfg["demand_total_factor_min_v2"],
            lambda: self.state.regimes,
            self._draw_regime,
        )
        self.setpoint_dev = SetpointDeviation(sc.seed, sc.duration_s, cfg)
        nominal = [sc.receipt_setpoint_m3h] + [
            float(e["value_m3h"]) for e in sc.schedule if e.get("command") == "receipt_setpoint"
        ]
        check_receipt_headroom(
            nominal, self._receipt_headroom_limit_m3h(), cfg["receipt_setpoint_clip_fraction"]
        )

    def _receipt_headroom_limit_m3h(self) -> float:
        """Largest inflow that passes the headroom screen after the trip level for one hour."""
        params = load_tank_parameters(self.model.directory)
        screen = HeadroomScreen.from_params(
            self.geometry,
            LevelEnvelope.from_tank(self.model.topology.tanks[0]),
            params["headroom_residual_delivery_m3"],
            params["headroom_level_allowance_m"],
        )
        return screen.limiting_flow_m3h(3600.0)

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
        if self.faults is not None:
            for name, valve in valves.items():
                valve.fault = self.faults.valve_fault(name)
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
        if self.faults is not None:  # a step ends where a ramp changes slope (D65)
            for t_knot in self.faults.knot_times(self.closed_alpha):
                self._push(state, t_knot, RANK_VALVE, "fault_knot", None)
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

    def _inputs(
        self,
        volumes: dict[str, float],
        t: float,
        receipt_m3h: float,
        delivery_m3h: float | None = None,
        offsets: dict[str, float] | None = None,
        apply_cap: bool = True,
        qdot_receipt: float = 0.0,
        demand_factor: float | None = None,
    ) -> SteadyInputs:
        st = self.state
        factor = self.demand.factor(t) if demand_factor is None else demand_factor
        alphas = {v: valve.alpha(t) for v, valve in st.valves.items()}
        open_valves = {v for v, valve in st.valves.items() if not valve.is_physically_closed(t)}
        partial = {v: a for v, a in alphas.items() if v in open_valves and a < 1.0}
        return SteadyInputs(
            lineup=Lineup(frozenset(open_valves), st.running),
            tank_levels_m=self._levels(volumes),
            scenario=self.scenario.volatility_class,
            temperature_c=self.scenario.temperature_c,
            fitting_profile=self.scenario.fitting_profile,
            receipt=ReceiptBoundary(flow_m3h=receipt_m3h),
            delivery=DeliveryBoundary(law_coefficient_m=self._law_c * factor),
            valve_positions=partial,
            warm_start=st.warm,
            imposed_delivery_flow_m3h=delivery_m3h,
            head_offsets_m=offsets or {},
            apply_cap=apply_cap,
            tap_head_offsets_m=self._tap_offsets(t, receipt_m3h, qdot_receipt),
            pump=self._pump(t, next(iter(sorted(st.running)), None)),
            leaks=self._leaks(t),
        )

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
        open_valves = {v for v, valve in st.valves.items() if not valve.is_physically_closed(t)}
        inputs = self._inputs(
            volumes, t, receipt_m3h, delivery_m3h, offsets, apply_cap, qdot_receipt
        )
        try:
            result = self.model.solve(inputs)
        except LeakError as exc:
            raise Rejected("SGF", t, "leak_edge", str(exc), None, None) from exc
        except PumpOutsideCurve as exc:
            raise Rejected(
                "SG0", t, "pump_domain", str(exc), None, self.model.config["pump_max_flow_m3h"]
            ) from exc
        except (ConvergenceError, HydraulicsError) as exc:
            raise Rejected("SG2", t, "steady_solve", str(exc), None, None) from exc
        self._check_leaks(t, result)
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
        gaps: dict[str, float] = {}
        heads, dead = deadleg.edge_heads(
            m, open_valves, result, self._levels(volumes), h_res, st.edge_heads,
            st.dead_edges, t - st.edge_heads_t, self.cfg["dead_leg_time_constant_s"], gaps,
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
            dead_leg_gaps_m=gaps,
        )

    def _pump(self, t: float, name: str | None) -> FixedSpeedPump:
        """The pump ``name`` with the head scale of a pump fault at time ``t`` (decision D62)."""
        pump = self.model.default_pump()
        scale = 1.0 if self.faults is None or name is None else self.faults.pump_scale(t, name)
        if scale == 1.0:
            return pump
        return dataclasses.replace(pump, h0_m=pump.h0_m * scale, k_m=pump.k_m * scale)

    def _leaks(self, t: float) -> tuple[LeakInput, ...]:
        return () if self.faults is None else self.faults.leaks(t)

    def _layout(self, path: LumpedPath, t: float) -> LeakLayout | None:
        """Where the frozen leak flows sit on a column."""
        st = self.state
        if not st.leak_flows:
            return None
        fractions = {lk.edge_id: lk.fraction for lk in self._leaks(t)}
        return path.leak_layout(fractions, st.leak_flows)

    def _check_leaks(self, t: float, result: SteadyResult) -> None:
        """Decision D10: a leak is valid only above the minimum gauge pressure (gate SGF)."""
        limit = self.cfg["leak_min_gauge_pressure_pa"]
        for edge, p in result.leak_pressures_pa_gauge.items():
            if p <= limit:
                detail = f"gauge pressure {p:.0f} Pa is not above {limit:.0f} Pa"
                raise Rejected("SGF", t, f"leak_pressure[{edge}]", detail, p, limit)

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
            [r.as_record() for r in st.regimes],
            [r.as_record() for r in st.regime_redraws],
        )

    # --- profile v2: demand regimes (decision D73) ----------
    def _draw_regime(self) -> None:
        """Append the next regime; its candidates are screened at the present state."""
        st, drawer = self.state, self._drawer
        assert drawer is not None
        index = len(st.regimes)
        t_start = 0.0 if index == 0 else st.regimes[-1].plateau_end_s
        regime, redraws = drawer.draw(index, t_start, self._regime_gate)
        st.regimes.append(regime)
        st.regime_redraws.extend(redraws)
        self._emit(
            st.t,
            "demand_regime",
            "simulator_truth",
            "DEMAND",
            {**regime.as_record(), "redraws": [r.as_record() for r in redraws]},
        )

    def _regime_gate(self, value: float) -> str | None:
        """Why a regime value is not acceptable now, or None.

        The pump must stay inside its curve with a margin at the smallest total factor of the
        regime, pass the phase and NPSH screen there, and keep the minimum stable flow at the
        largest factor, with the delivering tank lowered by an allowance for the level change over
        the ramp. Without a running pump the factor has no effect and any value passes (D73).
        """
        st, cfg = self.state, self.cfg
        tank = next(
            (
                k
                for k in self.model.topology.tank_ids
                if not st.valves[f"XV-S{k[3:]}"].is_physically_closed(st.t)
            ),
            None,
        )
        if not st.running or tank is None:
            return None
        level = self.geometry.level_m(st.volumes[tank], self.rho) - cfg["regime_level_allowance_m"]
        volumes = {**st.volumes, tank: self.geometry.volume_m3(level, self.rho)}
        low = max(value * cfg["demand_factor_min"], cfg["demand_total_factor_min_v2"])
        high = value * cfg["demand_factor_max"]
        for factor, largest in ((low, True), (high, False)):
            reason = self._probe(volumes, factor, largest)
            if reason is not None:
                return reason
        return None

    def _probe(self, volumes: dict[str, float], factor: float, largest: bool) -> str | None:
        st, cfg = self.state, self.cfg
        inputs = self._inputs(volumes, st.t, st.receipt_flow_m3h, demand_factor=factor)
        try:
            result = self.model.solve(inputs)
        except PumpOutsideCurve:
            return "pump_domain"
        except (ConvergenceError, HydraulicsError):
            return "steady_solve"
        pump = result.pump
        if pump is None:
            return None
        if largest:
            limit = self.model.config["pump_max_flow_m3h"] - cfg["pump_domain_margin_m3h"]
            if pump.flow_m3h / pump.speed_ratio > limit:
                return "pump_domain_margin"
            return None if result.phase.status == "OK" else "phase_screen"
        return None if pump.flow_m3h >= cfg["pump_min_stable_flow_m3h"] else "minimum_stable_flow"

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
        path = self._path("receipt", tank, None, t)
        return dyn.ReceiptColumn(
            path,
            tank,
            head_cap,
            level,
            self._area(tank),
            self.cfg["receipt_controller_tau_s"],
            st.receipt_setpoint_m3h / 3600.0,
            self._layout(path, t),
            self._setpoint_fn(st.receipt_setpoint_m3h),
        )

    def _effective_setpoint(self, nominal_m3h: float, t: float) -> float:
        """The set-point the controller follows; the nominal value unless profile v2 is on."""
        if self.setpoint_dev is None:
            return nominal_m3h
        return self.setpoint_dev.effective(nominal_m3h, t)

    def _setpoint_fn(self, nominal_m3h: float) -> Callable[[float], float] | None:
        if self.setpoint_dev is None:
            return None
        dev = self.setpoint_dev
        return lambda t: dev.effective(nominal_m3h, t) / 3600.0

    def _delivery_column(self, tank: str, pump: str, t: float) -> dyn.DeliveryColumn:
        st, m = self.state, self.model
        level = self.geometry.level_m(st.volumes[tank], self.rho)
        reservoir = m.node_z[BOUNDARY_NODE] + m.config["reservoir_pressure_pa_gauge"] / (
            m.rho * m.g
        )
        path = self._path("delivery", tank, pump, t)
        return dyn.DeliveryColumn(
            path,
            tank,
            self._pump(t, pump),
            reservoir,
            self._law_c,
            level,
            self._area(tank),
            m.config["pump_reference_flow_m3h"],
            self.demand.factor,
            self._layout(path, t),
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
        leak_r = plan.receipt.layout.total if plan.receipt and plan.receipt.layout else 0.0
        leak_s = plan.delivery.layout.tank_extra if plan.delivery and plan.delivery.layout else 0.0
        leak_d = (
            plan.delivery.layout.boundary_deduct if plan.delivery and plan.delivery.layout else 0.0
        )
        boundary_flow = (y1[1] - leak_d) * 3600.0 if plan.delivery is not None else None
        new = self._solve(
            volumes,
            t1,
            y1[0] * 3600.0,
            boundary_flow,
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

        h = t1 - t0
        return Stepped(
            t0, t1, plan, volumes, y1[0] * 3600.0, y1[1] * 3600.0, qdot_r, qdot_d,
            y1[2] + leak_r * h, y1[3] - (leak_s + leak_d) * h, new, volume_at, flow_at, 0, 0.0,
            inside, (leak_r + leak_s + leak_d) * h, (leak_r, leak_s, leak_d),
        )  # fmt: skip

    def _quasi(self, t0: float, t1: float, plan: Plan) -> Stepped:
        st = self.state
        assert st.current is not None
        h, s0 = t1 - t0, st.current
        tau_c = self.cfg["receipt_controller_tau_s"]
        target = self._effective_setpoint(st.receipt_setpoint_m3h, t0 + 0.5 * h)
        q1 = target + (st.receipt_flow_m3h - target) * math.exp(-h / tau_c)
        f1 = s0.tank_net_inflow_m3s
        predictor = {k: v + h * f1[k] for k, v in st.volumes.items()}
        s2 = self._solve(predictor, t1, q1)
        f2 = s2.tank_net_inflow_m3s
        volumes = {k: v + 0.5 * h * (f1[k] + f2[k]) for k, v in st.volumes.items()}
        recv = 0.5 * h * (_source_flow(s0) + _source_flow(s2))
        deliv = 0.5 * h * (s0.edge_flows_m3s["E-D2"] + s2.edge_flows_m3s["E-D2"])
        spill = 0.5 * h * (sum(s0.leak_flows_m3s.values()) + sum(s2.leak_flows_m3s.values()))
        new = self._solve(volumes, t1, q1)
        q_d = new.pump.flow_m3h if new.pump is not None else 0.0
        base = dict(st.volumes)
        d1 = new.tank_net_inflow_m3s

        def volume_at(tank: str, t: float) -> float:
            s = (t - t0) / h
            return _hermite(base[tank], volumes[tank], h * f1[tank], h * d1[tank], s)

        return Stepped(
            t0, t1, plan, volumes, q1, q_d, 0.0, 0.0, recv, deliv, new, volume_at, None, 0, 0.0,
            None, spill,
        )  # fmt: skip

    def _commit(self, step: Stepped, landing: tuple[float, str, str, float] | None) -> None:
        st = self.state
        net = sum(step.volumes.values()) - sum(st.volumes.values())
        base_received, base_delivered = st.cum_received_m3, st.cum_delivered_m3
        base_spilled = st.cum_spilled_m3
        st.cum_received_m3 += step.recv_m3
        st.cum_delivered_m3 += step.deliv_m3
        st.cum_spilled_m3 += step.spill_m3
        st.leak_flows = dict(step.new.leak_flows_m3s)
        st.ledger_terms += 3
        st.ledger_abs_kg += self.rho * (
            abs(step.recv_m3) + abs(step.deliv_m3) + abs(net) + abs(step.spill_m3)
        )
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
        self._write_interior(step, base_received, base_delivered, base_spilled)
        if fresh:
            # An edge isolated at the end of the step keeps the last head determined inside it.
            open_now = {v for v, x in st.valves.items() if not x.is_physically_closed(step.t1)}
            step.new = self._with_dead_legs(step.new, st.volumes, step.t1, open_now)
            st.current = step.new
        st.edge_heads, st.edge_heads_t = dict(step.new.edge_heads_m), step.t1
        st.dead_edges = step.new.dead_edges
        self._update_dead_leg_windows(step.new, step.t1)
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
        """Whether 0.1 s rows are needed: while a valve moves or inside a window of a transient
        kind. The slow windows do not need them (D34, D59).
        """
        st, tm = self.state, 0.5 * (t0 + t1)
        if any(v.is_moving(tm) for v in st.valves.values()):
            return True
        return any(
            w.kind in vd.DENSE_KINDS
            and w.t_start_s <= tm
            and (w.t_end_s is None or tm <= w.t_end_s)
            for w in st.windows
        )

    def _write_interior(
        self, step: Stepped, base_received: float, base_delivered: float, base_spilled: float
    ) -> None:
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
            lr, ls, ld = step.leaks
            into = t - step.t0
            snap = self._snapshot(
                t, result, ins.volumes,
                (
                    base_received + ins.c_r + lr * into,
                    base_delivered + ins.c_d - (ls + ld) * into,
                    base_spilled + (lr + ls + ld) * into,
                ),
            )  # fmt: skip
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

    def _stroke_carries_flow(self, key: str, flow_m3h: float) -> bool:
        """Whether a valve stroke is judged, which needs a flow of at least a fraction of the design
        flow of its path.

        The flow is read at the start of an opening stroke and at the instant the opening falls to
        0.2 for a closing stroke (D58).
        """
        design = self.model.config[
            "receipt_flow_m3h" if key == "receipt" else "pump_reference_flow_m3h"
        ]
        return flow_m3h >= self.cfg["stroke_window_min_flow_fraction"] * design

    def _factor(self, kind: str) -> float:
        """Minimum ratio of duration to wave round trip: a valve stroke has its own factor, and a
        set-point step, a flow collapse and a path closure keep the factor of the rigid-column model
        (D22, D53).
        """
        name = vd.STROKE_FACTOR if kind == "valve_stroke" else "wave_criterion_factor"
        return self.cfg[name]

    def _update_dead_leg_windows(self, result: SteadyResult, t: float) -> None:
        """Open a dead-leg window when an isolated segment holds a pressure farther from its target
        than the opening distance, and close it within the closing distance or when the segment is
        no longer isolated (D54).
        """
        st = self.state
        rho_g = self.model.rho * self.model.g
        opening = self.cfg["dead_leg_window_open_pa"] / rho_g
        closing = self.cfg["dead_leg_window_close_pa"] / rho_g
        gaps = result.dead_leg_gaps_m
        for key, gap in gaps.items():
            name = f"deadleg:{key}"
            if name not in st.open_windows and gap > opening:
                w = self._add_window(
                    "dead_leg_unvalidated",
                    key.split("+")[0],
                    t,
                    None,
                    vd.REASON_DEAD_LEG,
                    None,
                    None,
                )
                st.open_windows[name] = w
            elif name in st.open_windows and gap < closing:
                self._close_window(name, t)
        for name in [n for n in st.open_windows if n.startswith("deadleg:")]:
            if name[len("deadleg:") :] not in gaps:
                self._close_window(name, t)

    def _close_window(self, name: str, t: float) -> None:
        w = self.state.open_windows.pop(name)
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
        flow_m3h: float | None = None,
    ) -> None:
        if edges is None:
            return
        st = self.state
        trip = vd.round_trip_s(self.model, edges, self.speeds)
        st.events_evaluated += 1
        if flow_m3h is not None and not self._stroke_carries_flow(key, flow_m3h):
            return  # decision D58: the surge scales with the flow, which is too small here
        if not vd.is_valid(duration, trip, self._factor(kind)):
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
            f"NPSH3={c:g}m,{sc.atmosphere_stratum},{sc.volatility_class},"
            f"f_d={'0.6502' if sc.variability_profile == 'v2' else '0.8'}]"
        )
        record = pumping_minimum_level(
            tank,
            sc.temperature_c,
            sc.fitting_profile,
            c,
            self.model.directory,
            stratum_filename(sc.atmosphere_stratum, sc.volatility_class, sc.variability_profile),
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
        cumulative: tuple[float, float, float] | None = None,
    ) -> dict[str, Any]:
        st, rho = self.state, self.rho
        volumes = st.volumes if volumes is None else volumes
        received, delivered, spilled = cumulative or (
            st.cum_received_m3,
            st.cum_delivered_m3,
            st.cum_spilled_m3,
        )
        total = sum(volumes.values())
        residual = rho * (received - delivered - spilled - (total - st.initial_volume_total))
        roundoff = (
            max(st.ledger_terms - 1, 0)
            * UNIT_ROUNDOFF
            * (st.ledger_abs_kg + rho * (st.initial_volume_total + total))
        )
        tolerance = self.model.config["mass_conservation_tolerance_kg_s"] * t + roundoff
        return {
            "received_kg": rho * received,
            "delivered_kg": rho * delivered,
            "spilled_kg": rho * spilled,
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
        """Solve the last step again with the rate after a set-point command.

        A set-point step changes dQ/dt at once while the flow is continuous, so the inertial head
        offsets and the pressures jump at the command. The post-event rows and the next step start
        from the new solve (D22).
        """
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
        row = {
            "demand_process": self.scenario.demand_process,
            "downstream_factor": f,
            "log_downstream_factor": self.demand.unclipped_log(t),
            "boundary_law_coefficient_m": self._law_c * f,
            "reservoir_pressure_pa_gauge": self.model.config["reservoir_pressure_pa_gauge"],
            "atmosphere_stratum": self.scenario.atmosphere_stratum,
            "atmosphere_pa_abs": self.model.patm,
        }
        if isinstance(self.demand, RegimeDemand) and self.setpoint_dev is not None:
            nominal = self.state.receipt_setpoint_m3h
            row |= {
                "demand_regime_value": self.demand.regime(t),
                "receipt_setpoint_nominal_m3h": nominal,
                "receipt_setpoint_effective_m3h": self.setpoint_dev.effective(nominal, t),
            }
        return row

    def _snapshot(
        self,
        t: float,
        result: SteadyResult | None = None,
        volumes: dict[str, float] | None = None,
        cumulative: tuple[float, float, float] | None = None,
    ) -> rw.Snapshot:
        st = self.state
        assert st.current is not None
        volumes = st.volumes if volumes is None else volumes
        levels = self._levels(volumes)
        valves = {
            v: rw.ValveView(
                valve.alpha(t),
                valve.commanded_open,
                valve.is_physically_closed(t),
                valve.contact_alpha(t),
            )
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
            elif kind == "stroke_eval":
                self._resolve_stroke(payload, t)
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
            self._resolve_stroke(order.valve, t)  # a stroke that is interrupted is judged now
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
        st = self.state
        edges = self._edges_of(key, valve.name)
        if valve.target < valve.position0 and edges is not None:
            self._defer_closing_stroke(valve, end - t, t, key, edges)
        else:  # an opening stroke keeps the start-of-stroke rule (decision D58 version 2)
            flow = st.receipt_flow_m3h if key == "receipt" else st.delivery_flow_m3h
            self._evaluate_event("valve_stroke", valve.name, end - t, t, key, edges, flow)
        self._start_track(valve, key)

    def _defer_closing_stroke(
        self, valve: Valve, duration: float, t: float, key: str, edges: tuple[str, ...]
    ) -> None:
        """Judge a closing stroke at the instant the opening falls to 0.2, which is when the surge
        it can cause is set (D58).
        """
        st = self.state
        st.events_evaluated += 1
        t_eval = t + max(valve.position0 - STROKE_JUDGED_AT, 0.0) * valve.stroke_s
        st.pending_strokes[valve.name] = (t, duration, key, edges)
        self._push(st, t_eval, RANK_VALVE, "stroke_eval", valve.name)
        if t_eval <= t:
            self._resolve_stroke(valve.name, t)

    def _resolve_stroke(self, name: str, t: float) -> None:
        """Judge a waiting closing stroke now; the window starts at the start of the stroke."""
        st = self.state
        pending = st.pending_strokes.pop(name, None)
        if pending is None:
            return
        start, duration, key, edges = pending
        flow = st.receipt_flow_m3h if key == "receipt" else st.delivery_flow_m3h
        if not self._stroke_carries_flow(key, flow):
            return
        trip = vd.round_trip_s(self.model, edges, self.speeds)
        if not vd.is_valid(duration, trip, self._factor("valve_stroke")):
            self._add_window(
                "valve_stroke", name, start, start + duration, vd.REASON_DURATION,
                vd.ratio(duration, trip), trip,
            )  # fmt: skip

    def _start_track(self, valve: Valve, key: str) -> None:
        st = self.state
        flow = st.receipt_flow_m3h if key == "receipt" else st.delivery_flow_m3h
        if valve.target < valve.position0 and flow > 0.0:
            st.tracks.setdefault(key, Track(valve.name, flow / 3600.0))
        elif valve.target > valve.position0:
            st.tracks.pop(key, None)


def _source_flow(result: SteadyResult) -> float:
    """Flow that enters at the pipeline boundary: the downstream flow of E001 plus its leak."""
    return result.edge_flows_m3s["E001"] + result.leak_flows_m3s.get("E001", 0.0)


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
