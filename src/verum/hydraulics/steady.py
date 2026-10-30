"""Steady-state network solve for one lineup, set of tank levels and boundary case.

- Unknowns are node total heads, with tanks as constant-head nodes. Only edges on a flow path
  between terminals are solved.
- The pump is split into an inlet and an outlet node, and a pump that must add its shutoff head
  carries no flow.
- Static pressure at a tap is rho g (H - z) - rho v^2 / 2, in Pa gauge.
- A pump flow outside the curve is rejected, and phase and NPSH failures are reported and never
  clipped.

See D2, D3, D7, D11, D14, D15, D22 and D36.
"""

from __future__ import annotations

import copy
import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from verum.contracts import (
    FluidContract,
    Topology,
    load_fluid_contract,
    load_topology,
)
from verum.graph import Lineup, Network, RouteGeometry, load_route_geometry
from verum.hydraulics import solver as sv
from verum.hydraulics.boundaries import DeliveryBoundary, ReceiptBoundary
from verum.hydraulics.config import (
    FittingProfile,
    HydraulicConfig,
    load_boundary_law_coefficient,
    load_fitting_profile,
    load_hydraulic_config,
)
from verum.hydraulics.errors import ConvergenceError, HydraulicInputError, PumpOutsideCurve
from verum.hydraulics.fittings import bends_per_edge, edge_loss_coefficients
from verum.hydraulics.friction import head_loss
from verum.hydraulics.leaks import LeakError, LeakInput, OrificeLaw
from verum.hydraulics.properties import vapor_pressure_pa
from verum.hydraulics.pump import FixedSpeedPump, PumpElement, hydraulic_power_w, shaft_power_w
from verum.hydraulics.result import PhaseGate, PumpPoint, SteadyResult
from verum.hydraulics.valves import loss_coefficient

SOURCE = "PIPELINE_RECEIPT_BOUNDARY"
BOUNDARY = "DISTRIBUTION_BOUNDARY"
RESERVOIR = "RESERVOIR"
LAW_EDGE = "DELIVERY_BOUNDARY_LAW"


def leak_node(edge_id: str) -> str:
    return f"{edge_id}@leak"


def atmosphere_node(edge_id: str) -> str:
    return f"{edge_id}@atm"


def leak_up(edge_id: str) -> str:
    return f"{edge_id}#u"


def leak_down(edge_id: str) -> str:
    return f"{edge_id}#d"


def leak_sink(edge_id: str) -> str:
    return f"{edge_id}#leak"


def base_name(name: str) -> str:
    """The network edge a solver edge belongs to (leak parts carry a ``#`` suffix)."""
    return name.split("#", 1)[0]


@dataclass(frozen=True)
class SteadyInputs:
    """One steady case."""

    lineup: Lineup
    tank_levels_m: Mapping[str, float]
    scenario: str | None
    temperature_c: float
    fitting_profile: str = "pipe_only"
    k_multiplier: float = 1.0
    receipt: ReceiptBoundary = field(default_factory=ReceiptBoundary)
    delivery: DeliveryBoundary = field(default_factory=DeliveryBoundary)
    pump: PumpElement | None = None
    npsh3_coefficient_m: float | None = None
    valve_positions: Mapping[str, float] = field(default_factory=dict)
    warm_start: Mapping[str, float] | None = None
    imposed_delivery_flow_m3h: float | None = None
    head_offsets_m: Mapping[str, float] = field(default_factory=dict)
    apply_cap: bool = True
    tap_head_offsets_m: Mapping[str, float] = field(default_factory=dict)
    leaks: tuple[LeakInput, ...] = ()


class _PumpLaw(sv.FlowLaw):
    def __init__(self, pump: PumpElement) -> None:
        self._pump = pump

    def flow(self, delta: float) -> float:
        return self._pump.flow_m3s(delta)

    def slope(self, delta: float) -> float:
        return self._pump.slope(delta)


class _BoundaryLaw(sv.FlowLaw):
    """``delta = c (Q / q_ref)^2`` with Q in m3/h; the flow keeps the sign of delta."""

    def __init__(self, c_m: float, q_ref_m3h: float) -> None:
        self._c, self._q_ref = c_m, q_ref_m3h / 3600.0

    def flow(self, delta: float) -> float:
        return math.copysign(self._q_ref * math.sqrt(abs(delta) / self._c), delta)

    def slope(self, delta: float) -> float:
        return self._q_ref / (2.0 * math.sqrt(self._c * max(abs(delta), 1e-6)))


class HydraulicModel:
    """Loaded configuration plus the solve method."""

    def __init__(
        self,
        topology: Topology,
        geometry: RouteGeometry,
        fluid: FluidContract,
        config: HydraulicConfig,
        directory: Path | None = None,
    ) -> None:
        self.topology, self.geometry, self.fluid, self.config = topology, geometry, fluid, config
        self.directory = directory
        self.network = Network.from_topology(topology)
        self.rho = fluid.properties["rho_kg_m3"].value
        self.mu = fluid.properties["mu_Pa_s"].value
        self.g = config["gravity_m_s2"]
        self.roughness = config["pipe_roughness_m"]
        self.patm = config["atmosphere_pa_abs"]
        self.node_z = self._node_elevations()
        self._edges = {e.edge_id: e for e in topology.edges}
        self._bends = bends_per_edge(topology, geometry)
        self._profiles: dict[tuple[str, float], FittingProfile] = {}
        self._active: dict[Lineup, frozenset[str]] = {}
        self._laws: dict[str, float] = {}

    @classmethod
    def load(cls, directory: Path | None = None) -> HydraulicModel:
        return cls(
            load_topology(directory),
            load_route_geometry(directory),
            load_fluid_contract(directory),
            load_hydraulic_config(directory),
            directory,
        )

    def _node_elevations(self) -> dict[str, float]:
        z: dict[str, float] = {}
        for e in self.topology.edges:
            for node, level in ((e.from_node, e.z_from_m), (e.to_node, e.z_to_m)):
                if z.setdefault(node, level) != level:
                    raise HydraulicInputError(f"node {node} has two elevations")
        return z

    def for_stratum(self, stratum: str) -> HydraulicModel:
        """A copy of the model with the atmosphere of an episode stratum (decision D24)."""
        clone = copy.copy(self)
        clone.patm = self.config.atmosphere_pa_abs(stratum)
        return clone

    def default_pump(self) -> FixedSpeedPump:
        c = self.config
        return FixedSpeedPump(
            h0_m=c["pump_shutoff_head_m"],
            k_m=c["pump_curve_coefficient_m"],
            q_ref_m3h=c["pump_reference_flow_m3h"],
            q_max_m3h=c["pump_max_flow_m3h"],
            efficiency=c["pump_efficiency"],
            speed_ratio=c["pump_speed_ratio"],
        )

    # --- case construction ------------------------------------------------------
    def _end(self, node: str, role: str) -> str:
        if node in self.topology.pumps:
            return f"{node}:in" if role == "to" else f"{node}:out"
        return node

    def _pipe_edges(self, active: frozenset[str], inputs: SteadyInputs) -> list[sv.Edge]:
        key = (inputs.fitting_profile, inputs.k_multiplier)
        if key not in self._profiles:
            self._profiles[key] = load_fitting_profile(*key, self.directory)
        ks = edge_loss_coefficients(
            self.topology, self.geometry, self._profiles[key], active, self._bends
        )
        self._add_valve_throttling(ks, inputs.valve_positions)
        edges: list[sv.Edge] = []
        leaks = {lk.edge_id: lk for lk in inputs.leaks if lk.area_m2 > 0.0}
        for lk in leaks.values():
            if lk.edge_id not in active:
                raise LeakError(f"leak on {lk.edge_id}: the edge carries no determined pressure")
        for eid in sorted(active, key=lambda x: self.topology.edge_ids.index(x)):
            e = self._edges[eid]
            a, b = self._end(e.from_node, "from"), self._end(e.to_node, "to")
            one_way = e.from_node.startswith("CV-") or e.to_node.startswith("CV-")
            leak = leaks.get(eid)
            if leak is None:
                law: sv.FlowLaw = sv.LossLaw(
                    self._loss_function(e.inner_diameter_m, e.length_m, ks[eid])
                )
                edges.append(sv.Edge(eid, a, b, sv.OneWay(law) if one_way else law))
                continue
            x, mid = leak.fraction, leak_node(eid)
            for name, lo, hi, share in (
                (leak_up(eid), a, mid, x), (leak_down(eid), mid, b, 1.0 - x),
            ):  # fmt: skip
                part = sv.LossLaw(
                    self._loss_function(e.inner_diameter_m, share * e.length_m, share * ks[eid])
                )
                edges.append(sv.Edge(name, lo, hi, sv.OneWay(part) if one_way else part))
            edges.append(
                sv.Edge(
                    leak_sink(eid), mid, atmosphere_node(eid), OrificeLaw(leak.coefficient(self.g))
                )
            )
        return edges

    def path_head_loss(
        self, edge_ids: tuple[str, ...], flow_m3s: float, profile: str, multiplier: float = 1.0
    ) -> float:
        """Sum of friction and local losses along edges at a flow, with valves fully open."""
        key = (profile, multiplier)
        if key not in self._profiles:
            self._profiles[key] = load_fitting_profile(*key, self.directory)
        ks = edge_loss_coefficients(
            self.topology, self.geometry, self._profiles[key], edge_ids, self._bends
        )
        total = 0.0
        for eid in edge_ids:
            e = self._edges[eid]
            total += head_loss(
                flow_m3s,
                e.inner_diameter_m,
                e.length_m,
                ks[eid],
                self.rho,
                self.mu,
                self.roughness,
                self.g,
            )
        return total

    def edge_k(self, lineup: Lineup, profile: str, multiplier: float = 1.0) -> dict[str, float]:
        """Local loss coefficient of each edge of the active set of a lineup, valves open."""
        key = (profile, multiplier)
        if key not in self._profiles:
            self._profiles[key] = load_fitting_profile(*key, self.directory)
        if lineup not in self._active:
            self._active[lineup] = self.network.active_edges(lineup)
        return edge_loss_coefficients(
            self.topology, self.geometry, self._profiles[key], self._active[lineup], self._bends
        )

    def all_edge_k(self, profile: str, multiplier: float = 1.0) -> dict[str, float]:
        """Local loss coefficient of every edge (the transient engine may open any valve)."""
        key = (profile, multiplier)
        if key not in self._profiles:
            self._profiles[key] = load_fitting_profile(*key, self.directory)
        return edge_loss_coefficients(
            self.topology,
            self.geometry,
            self._profiles[key],
            frozenset(self.topology.edge_ids),
            self._bends,
        )

    def valve_extra_k(self, alpha: float) -> float:
        """Loss coefficient a valve at opening ``alpha`` adds to its full-open value."""
        c = self.config
        if alpha >= 1.0:
            return 0.0
        k = loss_coefficient(
            alpha, c["valve_full_open_k"], c["valve_alpha_c"], c["valve_rangeability"]
        )
        return k - c["valve_full_open_k"]

    def _add_valve_throttling(self, ks: dict[str, float], positions: Mapping[str, float]) -> None:
        """Extra K of a partly open valve, charged to the edge that starts at the valve."""
        c = self.config
        for valve, alpha in positions.items():
            if alpha >= 1.0:
                continue
            extra = loss_coefficient(
                alpha, c["valve_full_open_k"], c["valve_alpha_c"], c["valve_rangeability"]
            )
            extra -= c["valve_full_open_k"]
            for eid, edge in self._edges.items():
                if edge.from_node == valve and eid in ks:
                    ks[eid] += extra

    def _loss_function(self, diameter: float, length: float, k: float):  # type: ignore[no-untyped-def]
        rho, mu, rough, g = self.rho, self.mu, self.roughness, self.g
        return lambda q: head_loss(q, diameter, length, k, rho, mu, rough, g)

    def _levels(self, nodes: set[str], levels: Mapping[str, float]) -> dict[str, float]:
        fixed: dict[str, float] = {}
        for node in nodes:
            if node.endswith((":receipt_nozzle", ":outlet_nozzle")):
                tank = node.split(":")[0]
                if tank not in levels:
                    raise HydraulicInputError(f"no level given for {tank}")
                fixed[node] = float(levels[tank])
        return fixed

    # --- solve ---------------------------------------------------------------------
    def solve(self, inputs: SteadyInputs) -> SteadyResult:
        inputs.receipt.validate()
        inputs.delivery.validate()
        vp = vapor_pressure_pa(inputs.scenario, inputs.temperature_c, self.config, self.fluid)
        assert inputs.scenario is not None
        pump = inputs.pump or self.default_pump()
        self.network.check_lineup(inputs.lineup)
        if inputs.lineup not in self._active:
            self._active[inputs.lineup] = self.network.active_edges(inputs.lineup)
        active = self._active[inputs.lineup]
        case = _Case(self, inputs, active, pump)
        return case.run(vp)


@dataclass
class _Case:
    """State of one solve; keeps ``HydraulicModel.solve`` short."""

    model: HydraulicModel
    inputs: SteadyInputs
    active: frozenset[str]
    pump: PumpElement
    edges: list[sv.Edge] = field(default_factory=list)
    fixed: dict[str, float] = field(default_factory=dict)
    inflow: dict[str, float] = field(default_factory=dict)
    receipt_active: bool = False
    delivery_active: bool = False
    deadhead: bool = False
    clipped: bool = False
    c_law: float = 0.0
    notes: list[str] = field(default_factory=list)
    tap_heads: dict[str, float] = field(default_factory=dict)
    _leak_up: dict[str, float] = field(default_factory=dict)

    # --- orchestration ---------------------------------------------------------------
    def run(self, vapor_pa: float) -> SteadyResult:
        self.receipt_active = "E001" in self.active
        self.delivery_active = "E-D2" in self.active
        self._assemble()
        sol = self._solve()
        return self._result(sol, vapor_pa)

    def _assemble(self) -> None:
        m, inp = self.model, self.inputs
        self.edges = m._pipe_edges(self.active, inp)
        nodes = {n for e in self.edges for n in (e.a, e.b)}
        self.fixed = m._levels(nodes, inp.tank_levels_m)
        for lk in inp.leaks:
            if lk.area_m2 > 0.0:
                edge = m._edges[lk.edge_id]
                z = edge.z_from_m + lk.fraction * (edge.z_to_m - edge.z_from_m)
                self.fixed[atmosphere_node(lk.edge_id)] = z
        pumps_on = [p for p in m.topology.pumps if f"{p}:in" in nodes]
        if self.delivery_active:
            self._add_delivery(pumps_on)
        if self.receipt_active:
            self._add_receipt()

    def _reservoir_head(self) -> float:
        m, d = self.model, self.inputs.delivery
        p = d.reservoir_pressure_pa_gauge
        if p is None:
            p = m.config["reservoir_pressure_pa_gauge"]
        return m.node_z[BOUNDARY] + p / (m.rho * m.g)

    def _add_delivery(self, pumps_on: list[str]) -> None:
        m, inp = self.model, self.inputs
        for p in pumps_on:
            self.edges.append(sv.Edge(p, f"{p}:in", f"{p}:out", _PumpLaw(self.pump)))
        c = inp.delivery.law_coefficient_m
        if c is None:
            if inp.fitting_profile not in m._laws:
                m._laws[inp.fitting_profile] = load_boundary_law_coefficient(
                    inp.fitting_profile, m.directory
                ).value
            c = m._laws[inp.fitting_profile]
        self.c_law = c
        if inp.imposed_delivery_flow_m3h is not None:
            self.inflow[BOUNDARY] = -inp.imposed_delivery_flow_m3h / 3600.0
            return
        h_res = self._reservoir_head()
        if c > 0:
            law = _BoundaryLaw(c, m.config["pump_reference_flow_m3h"])
            self.edges.append(sv.Edge(LAW_EDGE, BOUNDARY, RESERVOIR, law))
            self.fixed[RESERVOIR] = h_res
        else:
            self.fixed[BOUNDARY] = h_res
        self._check_deadhead(h_res)

    def _delivery_names(self) -> set[str]:
        receipt = {e.edge_id for e in self.model.topology.edges if e.route_id.startswith("R-")}
        return {base_name(e.name) for e in self.edges if base_name(e.name) not in receipt}

    def _check_deadhead(self, h_res: float) -> None:
        names = self._delivery_names()
        outlets = [
            self.fixed[n]
            for e in self.edges
            if base_name(e.name) in names
            for n in (e.a, e.b)
            if n.endswith(":outlet_nozzle") and n in self.fixed
        ]
        if len(set(outlets)) == 1 and h_res - outlets[0] >= self.pump.shutoff_head_m:
            self.deadhead = True
            self.edges = [e for e in self.edges if base_name(e.name) not in names]
            self.fixed = {
                k: v
                for k, v in self.fixed.items()
                if k not in (RESERVOIR, BOUNDARY) and ":outlet" not in k
            }
            self.notes.append("pump dead-headed: the head to add reaches the shutoff head")

    def _add_receipt(self) -> None:
        m, r = self.model, self.inputs.receipt
        z_s = m.node_z[SOURCE]
        if r.pressure_pa_gauge is not None:
            self.fixed[SOURCE] = z_s + r.pressure_pa_gauge / (m.rho * m.g)
        else:
            flow = r.flow_m3h if r.flow_m3h is not None else m.config["receipt_flow_m3h"]
            self.inflow[SOURCE] = flow / 3600.0

    def _solve(self) -> sv.Solution:
        m = self.model
        tol, itmax = m.config["newton_flow_tolerance_m3s"], int(m.config["newton_max_iterations"])
        if not self.edges:
            return sv.Solution(dict(self.fixed), {}, {}, 0)
        sol = sv.solve_heads(self.edges, self.fixed, self.inflow, tol, itmax, self._warm_start())
        if self.receipt_active and SOURCE in self.inflow and self.inputs.apply_cap:
            cap = m.config["receipt_pressure_cap_pa_gauge"]
            p_source = m.rho * m.g * (sol.heads[SOURCE] - m.node_z[SOURCE])
            if p_source > cap:
                self.clipped = True
                del self.inflow[SOURCE]
                self.fixed[SOURCE] = m.node_z[SOURCE] + cap / (m.rho * m.g)
                self.notes.append("receipt flow clipped by the supply pressure cap")
                sol = sv.solve_heads(self.edges, self.fixed, self.inflow, tol, itmax)
        return sol

    def _warm_start(self) -> Mapping[str, float] | None:
        """The warm start of the caller, with a leak node placed between the heads of its ends.

        Without it the first guess of the leak node is the mean of the fixed heads, which can lie
        on the wrong side of a check valve next to the leak and makes the first step unbounded."""
        warm = self.inputs.warm_start
        if warm is None or not self.inputs.leaks:
            return warm
        extended = dict(warm)
        for lk in self._leaked().values():
            e = self.model._edges[lk.edge_id]
            a, b = self.model._end(e.from_node, "from"), self.model._end(e.to_node, "to")
            if a in warm and b in warm:
                extended[leak_node(lk.edge_id)] = warm[a] + lk.fraction * (warm[b] - warm[a])
        return extended

    # --- results -----------------------------------------------------------------------
    def _heads(self, sol: sv.Solution) -> dict[str, float]:
        heads = dict(sol.heads)
        heads.pop(RESERVOIR, None)
        for lk in self.inputs.leaks:
            heads.pop(leak_node(lk.edge_id), None)
            heads.pop(atmosphere_node(lk.edge_id), None)
        if self.deadhead:
            self._deadhead_heads(heads)
        self._static_heads(heads)
        for node, offset in self.inputs.head_offsets_m.items():
            if node in heads:
                heads[node] += offset
        return heads

    def _deadhead_heads(self, heads: dict[str, float]) -> None:
        m = self.model
        h_res = self._reservoir_head()
        tank_head = next(
            v for k, v in self._all_tank_heads().items() if k.endswith(":outlet_nozzle")
        )
        edges = [
            m._edges[e] for e in self.active if m._edges[e].route_id.startswith(("S-", "P-", "D-"))
        ]
        suction = {e.edge_id for e in edges if not self._after_pump(e.edge_id)}
        for e in edges:
            value = tank_head if e.edge_id in suction else h_res
            heads[m._end(e.from_node, "from")] = value
            heads[m._end(e.to_node, "to")] = value

    def _after_pump(self, edge_id: str) -> bool:
        return edge_id in {"E-PA2", "E-PA3", "E-PA4", "E-PB2", "E-PB3", "E-PB4", "E-D1", "E-D2"}

    def _all_tank_heads(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for tank in self.model.topology.tank_ids:
            if tank in self.inputs.tank_levels_m:
                level = float(self.inputs.tank_levels_m[tank])
                out[f"{tank}:receipt_nozzle"] = level
                out[f"{tank}:outlet_nozzle"] = level
        return out

    def _static_heads(self, heads: dict[str, float]) -> None:
        """Give still fluid the head of the tank it is open to (no flow, no loss)."""
        m = self.model
        arcs = m.network.arcs(self.inputs.lineup)
        pairs = {(a, b): eid for a, b, eid in arcs}
        two_way = [(a, b) for (a, b) in pairs if (b, a) in pairs]
        known = dict(heads)
        for nozzle, level in self._all_tank_heads().items():
            known.setdefault(nozzle, level)
        queue = deque(known)
        while queue:
            node = queue.popleft()
            for a, b in two_way:
                if a == node and b not in known:
                    known[b] = known[node]
                    queue.append(b)
        for node, value in known.items():
            heads.setdefault(node, value)

    def _leaked(self) -> dict[str, LeakInput]:
        return {lk.edge_id: lk for lk in self.inputs.leaks if lk.area_m2 > 0.0}

    def _flows(self, sol: sv.Solution) -> dict[str, float]:
        """Edge flows at the downstream end (decision D67); a leak edge reads its lower part."""
        leaked = self._leaked()
        return {
            eid: sol.flows.get(leak_down(eid) if eid in leaked else eid, 0.0)
            for eid in self.model.topology.edge_ids
        }

    def _leak_flows(self, sol: sv.Solution) -> dict[str, float]:
        return {eid: sol.flows.get(leak_sink(eid), 0.0) for eid in self._leaked()}

    def _leak_pressures(self, sol: sv.Solution) -> dict[str, float]:
        """Gauge pressure ``rho g (H - z)`` at each leak point (decision D60)."""
        m = self.model
        out = {}
        for eid in self._leaked():
            out[eid] = m.rho * m.g * (sol.heads[leak_node(eid)] - self.fixed[atmosphere_node(eid)])
        return out

    def _end_pressure(self, head: float, z: float, flow: float, diameter: float) -> float:
        m = self.model
        v = flow / (math.pi * diameter**2 / 4)
        return m.rho * m.g * (head - z) - 0.5 * m.rho * v * v

    def _pressures(
        self, heads: Mapping[str, float], flows: Mapping[str, float]
    ) -> tuple[dict[str, tuple[float, float]], dict[str, float]]:
        m = self.model
        ends: dict[str, tuple[float, float]] = {}
        for e in m.topology.edges:
            ha, hb = heads.get(m._end(e.from_node, "from")), heads.get(m._end(e.to_node, "to"))
            if ha is None or hb is None:
                continue
            q = flows[e.edge_id]
            q_up = q + self._leak_up.get(e.edge_id, 0.0)  # the flow at the upstream end
            ends[e.edge_id] = (
                self._end_pressure(ha, e.z_from_m, q_up, e.inner_diameter_m),
                self._end_pressure(hb, e.z_to_m, q, e.inner_diameter_m),
            )
        taps: dict[str, float] = {}
        self.tap_heads: dict[str, float] = {}
        for node, ref in m.config.tap_reference_edges.items():
            if node in heads:
                e = m._edges[ref]
                head = heads[node] + self.inputs.tap_head_offsets_m.get(node, 0.0)
                self.tap_heads[node] = head
                taps[node] = self._end_pressure(
                    head, m.node_z[node], flows[ref], e.inner_diameter_m
                )
        return ends, taps

    def _pump_point(
        self, heads: Mapping[str, float], flows: Mapping[str, float]
    ) -> PumpPoint | None:
        m = self.model
        running = [
            p
            for p in m.topology.pumps
            if f"{p}:in" in heads and p in self.inputs.lineup.running_pumps
        ]
        if not running or not self.delivery_active:
            return None
        name = running[0]
        edge = self._pump_edge(name)
        q = flows[edge] + self._leak_up.get(edge, 0.0)  # the flow through the pump
        q_m3h = q * 3600.0
        if not self.pump.in_domain(q_m3h):
            raise PumpOutsideCurve(
                f"{name}: solved flow {q_m3h:.1f} m3/h is outside the pump curve "
                f"(Q/s limit {m.config['pump_max_flow_m3h']:g} m3/h)"
            )
        rise = heads[f"{name}:out"] - heads[f"{name}:in"]
        hydraulic = hydraulic_power_w(m.rho, m.g, q, rise)
        status = "DEADHEAD" if self.deadhead else "OK"
        return PumpPoint(
            pump=name,
            flow_m3h=q_m3h,
            head_rise_m=rise,
            speed_ratio=self.pump.speed_ratio,
            reference_equivalent_flow_m3h=q_m3h / self.pump.speed_ratio,
            hydraulic_power_w=hydraulic,
            shaft_power_w=shaft_power_w(hydraulic, m.config["pump_efficiency"]),
            status=status,
        )

    def _pump_edge(self, pump: str) -> str:
        return {"P-101A": "E-PA2", "P-101B": "E-PB2"}[pump]

    def _phase(
        self,
        vapor_pa: float,
        heads: Mapping[str, float],
        pump_point: PumpPoint | None,
        ends: Mapping[str, tuple[float, float]],
    ) -> PhaseGate:
        m, inp = self.model, self.inputs
        active_ends = [p for eid, pair in ends.items() if eid in self.active for p in pair]
        min_abs = min(active_ends) + m.patm if active_ends else None
        npsha = npsh3 = ratio = None
        if pump_point is not None and pump_point.status == "OK":
            z_pump = m.node_z[pump_point.pump]
            npsha = (m.patm - vapor_pa) / (m.rho * m.g) + (heads[f"{pump_point.pump}:in"] - z_pump)
            coeff = inp.npsh3_coefficient_m
            if coeff is None:
                coeff = m.config["npsh3_coefficient_m"]
            npsh3 = coeff * (pump_point.flow_m3h / m.config["pump_reference_flow_m3h"]) ** 2
            ratio = npsha / npsh3 if npsh3 > 0 else math.inf
        status = "OK"
        if (min_abs is not None and min_abs < vapor_pa) or (npsha is not None and npsha <= 0):
            status = "SCREEN_FAILED"
        elif ratio is not None and ratio < m.config["npsh_margin_ratio"]:
            status = "NPSH_MARGIN_FAILED"
        assert inp.scenario is not None
        return PhaseGate(
            status, inp.scenario, inp.temperature_c, vapor_pa, min_abs, npsha, npsh3, ratio
        )

    def _tank_flows(self, sol: sv.Solution) -> dict[str, float]:
        out: dict[str, float] = {}
        for tank in self.model.topology.tank_ids:
            net_out = 0.0
            for e in self.edges:
                if e.name not in sol.flows:
                    continue
                for node, sign in ((e.a, 1.0), (e.b, -1.0)):
                    if node.startswith(f"{tank}:"):
                        net_out += sign * sol.flows[e.name]
            out[tank] = -net_out + 0.0
        return out

    def _result(self, sol: sv.Solution, vapor_pa: float) -> SteadyResult:
        m = self.model
        heads = self._heads(sol)
        flows = self._flows(sol)
        leak_flows = self._leak_flows(sol)
        self._leak_up = leak_flows
        ends, taps = self._pressures(heads, flows)
        pump_point = self._pump_point(heads, flows)
        phase = self._phase(vapor_pa, heads, pump_point, ends)
        residual = {n: r * m.rho for n, r in sol.residuals.items()}
        tolerance = m.config["mass_conservation_tolerance_kg_s"]
        if any(abs(v) > tolerance for v in residual.values()):
            raise ConvergenceError("node mass residual exceeds the configured tolerance")
        source_p = m.rho * m.g * (heads[SOURCE] - m.node_z[SOURCE]) if self.receipt_active else None
        gates = {
            "G2_boundary": "OK",
            "G3_pump_domain": "NOT_APPLICABLE" if pump_point is None else pump_point.status,
            "G4_phase": phase.status,
            "G6_conservation": "OK",
        }
        return SteadyResult(
            node_heads_m=heads,
            edge_flows_m3s=flows,
            edge_end_pressures_pa_gauge=ends,
            tap_pressures_pa_gauge=taps,
            tank_net_inflow_m3s=self._tank_flows(sol),
            pump=pump_point,
            phase=phase,
            source_pressure_pa_gauge=source_p,
            receipt_flow_m3h=(flows["E001"] + leak_flows.get("E001", 0.0)) * 3600.0,
            receipt_clipped=self.clipped,
            node_mass_residual_kg_s=residual,
            gates=gates,
            active_edges=self.active,
            atmosphere_pa_abs=m.patm,
            iterations=sol.iterations,
            fitting_profile=self.inputs.fitting_profile,
            k_multiplier=self.inputs.k_multiplier,
            boundary_law_coefficient_m=self.c_law,
            tap_heads_m=self.tap_heads,
            leak_flows_m3s=leak_flows,
            leak_pressures_pa_gauge=self._leak_pressures(sol),
            notes=tuple(self.notes),
        )
