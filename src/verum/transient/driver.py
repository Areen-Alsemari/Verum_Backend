"""The transient driver: builds the network from a steady solve and advances it in time.

Inputs: a ``HydraulicModel`` and a ``TransientSpec`` (lineup, tank levels, receipt flow and
set-point, valve strokes, set-point steps, a pump stop, an optional leak, wave speeds). Outputs:
heads and flows at every grid point at every step, probes, diagnostics and a mass ledger.
Key assumptions:
    * Decisions D43 to D45. The initial state is the steady solve of ``verum.hydraulics`` for the
      same lineup, levels, fitting profile, property class and downstream factor; edge end heads
      come from its end pressures (piezometric: elevation plus pressure head) and are interpolated
      linearly along each edge. An edge without a steady pressure (no flow, no connection) takes
      the head of the nearest determined edge through the graph.
    * Single-threaded float64 numpy; no random numbers; the same inputs give the same bits. A
      checkpoint is a copy of the mutable state and a restarted engine continues bit for bit.
    * The receipt source flow follows the controller of decision D44: each step the commanded
      flow moves from the actual flow towards the set-point with time constant 2 s; a 10 barg
      cap at ``PIPELINE_RECEIPT_BOUNDARY`` limits the flow.
    * Verification cases may impose the flow through a series node (``flow_schedules``), which
      replaces the valve law there; production use does not.
    * Valves move linearly (decision D19) and are closed at an opening of 0.001 or less. The extra
      resistance of a partly closed valve is the steady package's ``K(alpha) - K_open`` on the
      area of the edge that starts at the valve.
    * No cavitation model (decision D45): points at or below the vapor pressure open a
      ``phase_invalid`` interval and nothing is clipped.

Source: ``docs/design_decisions.md`` D43 to D47; ``docs/transient_engine.md``.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from verum.graph import Lineup
from verum.hydraulics import DeliveryBoundary, HydraulicModel, ReceiptBoundary, SteadyInputs
from verum.hydraulics.properties import vapor_pressure_pa
from verum.transient import boundaries as bd
from verum.transient import grid as gr
from verum.transient.diagnostics import Ledger, PhaseWindows
from verum.transient.elements import CheckValve, series_flow
from verum.transient.interior import PointConstants, c_minus, c_plus, interior_update

CLOSED_ALPHA = 0.001
TANK_NOZZLES = (":receipt_nozzle", ":outlet_nozzle")
SOURCE, RESERVOIR = "PIPELINE_RECEIPT_BOUNDARY", "DISTRIBUTION_BOUNDARY"
ATMOSPHERE_STRATA = ("coastal", "inland")


@dataclass(frozen=True)
class ValveEvent:
    valve: str
    t_start_s: float
    target: float  # 0 closes, 1 opens
    stroke_s: float


@dataclass(frozen=True)
class TransientSpec:
    lineup: Lineup
    tank_levels_m: Mapping[str, float]
    volatility_class: str = "RVP_9_0"
    temperature_c: float = 25.0
    atmosphere_stratum: str = "coastal"
    fitting_profile: str = "reference_fittings"
    receipt_flow_m3h: float = 0.0
    receipt_setpoint_m3h: float = 0.0
    downstream_factor: float = 1.0
    check_valve_delay_s: float = 0.3
    controller_tau_s: float = 2.0
    valve_events: tuple[ValveEvent, ...] = ()
    setpoint_events: tuple[tuple[float, float], ...] = ()
    pump_stops: tuple[tuple[float, str], ...] = ()
    leak: tuple[str, float] | None = None  # (junction node, k in m3/s per sqrt(m))
    dt_s: float = gr.DT_S
    wave_speeds: Mapping[int, float] | None = None
    head_cap_pa_gauge: float | None = None
    friction_off: bool = False
    uniform_start: Mapping[str, tuple[float, float]] | None = None  # edge -> (head m, flow m3/s)
    flow_schedules: Mapping[str, Callable[[float], float]] | None = None  # valve node -> Q(t)


@dataclass(frozen=True)
class NetworkDef:
    """A network: edges (id, nodes, length, bore, elevations), local losses, pumps, node heights.

    ``initial`` maps an edge to (head at its from end, head at its to end, flow in m3/s) and is
    used instead of a steady solve (idealised networks of the verification ladder)."""

    edges: tuple[Any, ...]
    k: Mapping[str, float]
    pumps: tuple[str, ...]
    node_z: Mapping[str, float]
    initial: Mapping[str, tuple[float, float, float]] | None = None


def plant_network(model: HydraulicModel, profile: str) -> NetworkDef:
    return NetworkDef(
        tuple(model.topology.edges),
        model.all_edge_k(profile),
        tuple(model.topology.pumps),
        dict(model.node_z),
    )


@dataclass
class Probe:
    name: str
    edge_id: str
    fraction: float  # 0 at the from end, 1 at the to end


@dataclass
class _Motion:
    t0: float
    a0: float
    target: float
    stroke: float


class TransientEngine:
    def __init__(
        self, model: HydraulicModel, spec: TransientSpec, network: NetworkDef | None = None
    ) -> None:
        self.spec = spec
        self.net = network or plant_network(
            model.for_stratum(spec.atmosphere_stratum), spec.fitting_profile
        )
        self.model = model.for_stratum(spec.atmosphere_stratum)
        m = self.model
        self.g, self.rho = m.g, m.rho
        self.dt = spec.dt_s
        self.vapor_pa = vapor_pressure_pa(
            spec.volatility_class, spec.temperature_c, m.config, m.fluid
        )
        self.edges = list(self.net.edges)
        self.edge_index = {e.edge_id: i for i, e in enumerate(self.edges)}
        speeds = dict(spec.wave_speeds) if spec.wave_speeds else gr.load_wave_speeds(m.directory)
        self.grid = gr.build_grid(self.edges, speeds, self.dt)
        self._build_points()
        self._initial_state()
        self._build_nodes()
        self._init_dynamics()

    # --- construction ----------
    def _build_points(self) -> None:
        sizes = [gg.reaches + 1 for gg in self.grid]
        self.first = np.concatenate(([0], np.cumsum(sizes)[:-1]))
        self.last = self.first + np.array([gg.reaches for gg in self.grid])
        n = int(sum(sizes))
        self.n_points = n
        edge_of = np.repeat(np.arange(len(self.grid)), sizes)
        self.edge_of_point = edge_of
        k_edge = self.net.k
        a = np.array([gg.area_m2 for gg in self.grid])
        d = np.array([gg.diameter_m for gg in self.grid])
        wv = np.array([gg.wave_speed_m_s for gg in self.grid])
        dx = np.array([gg.reach_length_m for gg in self.grid])
        ln = np.array([gg.length_m for gg in self.grid])
        k = np.array([k_edge[e.edge_id] for e in self.edges])
        scale = 0.0 if self.spec.friction_off else 1.0
        self.pc = PointConstants(
            b=(wv / (self.g * a))[edge_of], diameter=d[edge_of], area=a[edge_of], dx=dx[edge_of],
            k_per_reach=(scale * k * dx / ln)[edge_of],
            inv_2ga2=(1.0 / (2.0 * self.g * a**2))[edge_of],
            rho=self.rho, mu=self.model.mu, roughness=self.model.roughness, friction_scale=scale,
        )  # fmt: skip
        z = np.empty(n)
        for i, e in enumerate(self.edges):
            z[self.first[i] : self.last[i] + 1] = np.linspace(
                e.z_from_m, e.z_to_m, self.grid[i].reaches + 1
            )
        self.z = z
        self.interior = np.array(
            [p for i in range(len(self.grid)) for p in range(self.first[i] + 1, self.last[i])],
            dtype=int,
        )
        self.k_edge = k

    def _initial_state(self) -> None:
        sp, m = self.spec, self.model
        c = m.config
        from verum.hydraulics import load_boundary_law_coefficient

        self.law_c = load_boundary_law_coefficient(sp.fitting_profile, m.directory).value
        self.steady = None if self.net.initial is not None else m.solve(
            SteadyInputs(
                lineup=sp.lineup, tank_levels_m=sp.tank_levels_m, scenario=sp.volatility_class,
                temperature_c=sp.temperature_c, fitting_profile=sp.fitting_profile,
                receipt=ReceiptBoundary(flow_m3h=sp.receipt_flow_m3h),
                delivery=DeliveryBoundary(law_coefficient_m=self.law_c * sp.downstream_factor),
            )
        )  # fmt: skip
        rho_g = self.rho * self.g
        known: dict[str, tuple[float, float]] = {}
        if self.net.initial is None:
            assert self.steady is not None
            for e in self.edges:
                ends = self.steady.edge_end_pressures_pa_gauge.get(e.edge_id)
                if ends is not None:
                    known[e.edge_id] = (e.z_from_m + ends[0] / rho_g, e.z_to_m + ends[1] / rho_g)
        else:
            known = {k: (v[0], v[1]) for k, v in self.net.initial.items()}
        if sp.uniform_start:
            known = {k: (v[0], v[0]) for k, v in sp.uniform_start.items()}
        self._fill_dead_edges(known)
        self.h = np.empty(self.n_points)
        self.q = np.empty(self.n_points)
        for i, e in enumerate(self.edges):
            h0, h1 = known[e.edge_id]
            f = np.linspace(0.0, 1.0, self.grid[i].reaches + 1)
            self.h[self.first[i] : self.last[i] + 1] = h0 + (h1 - h0) * f
            if self.net.initial is not None:
                flow = self.net.initial[e.edge_id][2]
            elif sp.uniform_start and e.edge_id in sp.uniform_start:
                flow = sp.uniform_start[e.edge_id][1]
            else:
                assert self.steady is not None
                flow = self.steady.edge_flows_m3s[e.edge_id]
            self.q[self.first[i] : self.last[i] + 1] = flow
        self.h0 = self.h.copy()
        nz = self.net.node_z
        self.head_cap_m = nz.get(SOURCE, 0.0) + (
            (
                sp.head_cap_pa_gauge
                if sp.head_cap_pa_gauge is not None
                else c["receipt_pressure_cap_pa_gauge"]
            )
            / rho_g
        )
        self.head_res_m = nz.get(RESERVOIR, 0.0) + c["reservoir_pressure_pa_gauge"] / rho_g

    def _is_barrier(self, node: str) -> bool:
        lineup = self.spec.lineup
        if node.startswith("XV-"):
            return node not in lineup.open_valves
        return node.startswith("CV-") or node in self.net.pumps

    def _fill_dead_edges(self, known: dict[str, tuple[float, float]]) -> None:
        """Give every edge without a steady pressure one head per segment (no flow, no gradient).

        A segment that touches a tank takes its level, one that touches the reservoir its head,
        one open to flowing fluid at a node the total head of that node, and an isolated one the
        head across its closed valve (valves first, then check valves and pumps)."""
        m = self.model
        rho_g = self.rho * self.g
        h_res = (
            self.net.node_z.get(RESERVOIR, 0.0) + m.config["reservoir_pressure_pa_gauge"] / rho_g
        )
        node_total: dict[str, float] = {}
        for e in self.edges:
            if e.edge_id in known:
                area = math.pi * e.inner_diameter_m**2 / 4
                if self.net.initial is not None:
                    flow = self.net.initial[e.edge_id][2]
                else:
                    assert self.steady is not None
                    flow = self.steady.edge_flows_m3s[e.edge_id]
                vh = (flow / area) ** 2 / (2.0 * self.g)
                node_total.setdefault(e.from_node, known[e.edge_id][0] + vh)
                node_total.setdefault(e.to_node, known[e.edge_id][1] + vh)
        dead = [e for e in self.edges if e.edge_id not in known]
        parent = {e.edge_id: e.edge_id for e in dead}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        first_at: dict[str, str] = {}
        for e in dead:
            for n in (e.from_node, e.to_node):
                if not self._is_barrier(n):
                    if n in first_at:
                        parent[find(e.edge_id)] = find(first_at[n])
                    first_at.setdefault(n, e.edge_id)
        comps: dict[str, list[Any]] = {}
        for e in dead:
            comps.setdefault(find(e.edge_id), []).append(e)
        head: dict[str, float] = {}
        levels = self.spec.tank_levels_m
        for key, seg in comps.items():
            nodes = {n for e in seg for n in (e.from_node, e.to_node)}
            anchors = sorted(levels[n.split(":")[0]] for n in nodes if n.endswith(TANK_NOZZLES))
            if anchors:
                head[key] = anchors[0]
            elif RESERVOIR in nodes:
                head[key] = h_res
            else:
                live = sorted(
                    node_total[n] for n in nodes if not self._is_barrier(n) and n in node_total
                )
                if live:
                    head[key] = live[0]
        pending = [k for k in comps if k not in head]
        while pending:
            progressed = False
            for key in list(pending):
                barrier_nodes = sorted(
                    {
                        n
                        for e in comps[key]
                        for n in (e.from_node, e.to_node)
                        if self._is_barrier(n)
                    },
                    key=lambda n: (
                        0 if n.startswith("XV-") else 1 if n.startswith("CV-") else 2,
                        n,
                    ),
                )
                target = None
                for n in barrier_nodes:
                    if n in node_total:
                        target = node_total[n]
                    else:
                        for other_key, other in comps.items():
                            if (
                                other_key != key
                                and other_key in head
                                and any(n in (o.from_node, o.to_node) for o in other)
                            ):
                                target = head[other_key]
                                break
                    if target is not None:
                        break
                if target is not None:
                    head[key] = target
                    pending.remove(key)
                    progressed = True
            if not progressed:
                for key in pending:
                    head[key] = comps[key][0].z_from_m
                break
        for key, seg in comps.items():
            for e in seg:
                known[e.edge_id] = (head[key], head[key])

    def head_res_m_default(self) -> float:
        c = self.model.config
        return self.net.node_z.get(RESERVOIR, 0.0) + c["reservoir_pressure_pa_gauge"] / (
            self.rho * self.g
        )

    def _build_nodes(self) -> None:
        ends = []  # (edge index, 0 from / 1 to, node name)
        for i, e in enumerate(self.edges):
            ends += [(i, 0, e.from_node), (i, 1, e.to_node)]
        self.end_edge = np.array([x[0] for x in ends])
        self.end_to = np.array([x[1] == 1 for x in ends])
        self.end_pt = np.array([self.last[x[0]] if x[1] == 1 else self.first[x[0]] for x in ends])
        self.end_nb = np.where(self.end_to, self.end_pt - 1, self.end_pt + 1)
        names = [x[2] for x in ends]
        by_node: dict[str, list[int]] = {}
        for idx, n in enumerate(names):
            by_node.setdefault(n, []).append(idx)
        self.end_names = names
        self.to_ends = np.nonzero(self.end_to)[0]
        self.from_ends = np.nonzero(~self.end_to)[0]
        self.b_end = self.pc.b[self.end_pt]
        self.g_end = 1.0 / self.b_end
        self.tank_ends, self.tank_names = [], []
        self.src_end = self.res_end = -1
        self.series: list[tuple[str, int, int]] = []
        junction_nodes: list[str] = []
        for node, idxs in by_node.items():
            if node.endswith(TANK_NOZZLES):
                self.tank_ends.append(idxs[0])
                self.tank_names.append(node.split(":")[0])
            elif node == SOURCE:
                self.src_end = idxs[0]
            elif node == RESERVOIR:
                self.res_end = idxs[0]
            elif node.startswith(("XV-", "CV-")) or node in self.net.pumps:
                e_in = next(i for i in idxs if self.end_to[i])
                e_out = next(i for i in idxs if not self.end_to[i])
                self.series.append((node, e_in, e_out))
            else:
                junction_nodes.append(node)
        self.tank_ends_a = np.array(self.tank_ends)
        self.tank_head = np.array([self.spec.tank_levels_m[t] for t in self.tank_names])
        self.junction_nodes = junction_nodes
        self.j_end = np.array([i for n in junction_nodes for i in by_node[n]])
        self.j_local = np.array([k for k, n in enumerate(junction_nodes) for _ in by_node[n]])
        self.s_e1 = np.array([s[1] for s in self.series])
        self.s_e2 = np.array([s[2] for s in self.series])
        self.series_index = {s[0]: k for k, s in enumerate(self.series)}
        self.node_head = np.zeros(len(junction_nodes))
        self.junction_z = np.array([self.net.node_z.get(n, 0.0) for n in junction_nodes])
        self.demand = np.zeros(len(junction_nodes))

    def _init_dynamics(self) -> None:
        sp, m = self.spec, self.model
        c = m.config
        ns = len(self.series)
        self.t = 0.0
        self.step_index = 0
        self.alpha: dict[str, float] = {}
        self.motion: dict[str, _Motion] = {}
        self.shutoff = np.zeros(ns)
        self.k2 = np.zeros(ns)
        self.closed = np.zeros(ns, dtype=bool)
        qref = c["pump_reference_flow_m3h"] / 3600.0
        self.pump_k2 = c["pump_curve_coefficient_m"] / qref**2
        self.pump_h0 = c["pump_shutoff_head_m"]
        self.pump_running: dict[str, bool] = {}
        self.checks: dict[str, CheckValve] = {}
        for k, (node, e_in, _e_out) in enumerate(self.series):
            if node.startswith("XV-"):
                self.alpha[node] = 1.0 if node in sp.lineup.open_valves else 0.0
                self._set_valve(node, k)
            elif node in self.net.pumps:
                run = node in sp.lineup.running_pumps
                self.pump_running[node] = run
                self.shutoff[k] = self.pump_h0 if run else 0.0
                self.k2[k] = self.pump_k2
            else:
                cv = CheckValve(sp.check_valve_delay_s)
                edge_in = self.edges[self.end_edge[e_in]].edge_id
                if self.net.initial is not None:
                    inflow = self.net.initial[edge_in][2]
                else:
                    assert self.steady is not None
                    inflow = self.steady.edge_flows_m3s[edge_in]
                cv.open = inflow > 1e-12  # a check valve starts closed if nothing flows forward
                self.checks[node] = cv
        self.pending_valves = sorted(sp.valve_events, key=lambda e: e.t_start_s)
        self.pending_setpoints = sorted(sp.setpoint_events)
        self.pending_stops = sorted(sp.pump_stops)
        self.qset = sp.receipt_setpoint_m3h / 3600.0
        self.q_src = sp.receipt_flow_m3h / 3600.0
        self.cc = self.law_c * sp.downstream_factor * (3600.0 / c["pump_reference_flow_m3h"]) ** 2
        self.res_cc = np.array([self.cc])
        self.ledger = Ledger()
        w = (
            self.pc.area
            * self.pc.dx
            * self.g
            / np.array([gg.wave_speed_m_s for gg in self.grid])[self.edge_of_point] ** 2
        )
        w[self.first] *= 0.5
        w[self.last] *= 0.5
        self.storage_w = w
        self.storage0 = float(np.dot(w, self.h))
        self.h_min = self.h.copy()
        self.phase = PhaseWindows()
        self.below_vapor = False
        self.courant_departure = max(
            abs(gg.wave_speed_m_s * self.dt / gg.reach_length_m - 1.0) for gg in self.grid
        )
        self.capped = False
        self.rev_ledger = 0.0
        self.leak_k = 0.0
        self.leak_local = -1
        if sp.leak is not None:
            self.leak_local = self.junction_nodes.index(sp.leak[0])
            self.leak_k = sp.leak[1]

    # --- valve helpers ----------
    def _valve_edge_area_inv(self, node: str) -> float:
        e_out = self.edges[self.end_edge[self.series[self.series_index[node]][2]]]
        return 1.0 / (2.0 * self.g * math.pi * e_out.inner_diameter_m**2 / 4.0) if e_out else 0.0

    def _set_valve(self, node: str, k: int | None = None) -> None:
        k = self.series_index[node] if k is None else k
        a = self.alpha[node]
        self.closed[k] = a <= CLOSED_ALPHA
        extra = 0.0 if a >= 1.0 else self.model.valve_extra_k(max(a, CLOSED_ALPHA))
        self.k2[k] = extra * self._valve_edge_area_inv(node)

    def _advance_events(self, t: float) -> None:
        while self.pending_valves and self.pending_valves[0].t_start_s <= t:
            ev = self.pending_valves.pop(0)
            self.motion[ev.valve] = _Motion(
                ev.t_start_s, self.alpha_at(ev.valve, ev.t_start_s), ev.target, ev.stroke_s
            )
        for valve, mo in list(self.motion.items()):
            travelled = max(t - mo.t0, 0.0) / mo.stroke
            delta = abs(mo.target - mo.a0)
            step = min(travelled, delta)
            self.alpha[valve] = mo.a0 + step if mo.target > mo.a0 else mo.a0 - step
            self._set_valve(valve)
            if travelled >= delta:
                del self.motion[valve]
        while self.pending_setpoints and self.pending_setpoints[0][0] <= t:
            self.qset = self.pending_setpoints.pop(0)[1] / 3600.0
        while self.pending_stops and self.pending_stops[0][0] <= t:
            _, pump = self.pending_stops.pop(0)
            k = self.series_index[pump]
            self.pump_running[pump], self.shutoff[k] = False, 0.0

    def alpha_at(self, valve: str, t: float) -> float:
        mo = self.motion.get(valve)
        if mo is None:
            return self.alpha[valve]
        step = min(max(t - mo.t0, 0.0) / mo.stroke, abs(mo.target - mo.a0))
        return mo.a0 + step if mo.target > mo.a0 else mo.a0 - step

    # --- one step ----------
    def step(self) -> None:
        t_new = self.t + self.dt
        self._advance_events(t_new)
        h, q = self.h, self.q
        pc = self.pc
        h_new, q_new = h.copy(), q.copy()
        if self.interior.size:
            h_new[self.interior], q_new[self.interior] = interior_update(pc, h, q, self.interior)
        c_end = np.empty(len(self.end_pt))
        c_end[self.to_ends] = c_plus(pc, h, q, self.end_pt[self.to_ends], self.end_nb[self.to_ends])
        c_end[self.from_ends] = c_minus(
            pc, h, q, self.end_pt[self.from_ends], self.end_nb[self.from_ends]
        )
        d_end = c_end + q[self.end_pt] ** 2 * pc.inv_2ga2[self.end_pt]
        qn = np.zeros(len(self.end_pt))
        g_e = self.g_end
        # tanks
        if self.tank_ends_a.size:
            qn[self.tank_ends_a] = bd.tank_flow(
                g_e[self.tank_ends_a], d_end[self.tank_ends_a], self.tank_head
            )
        # reservoir
        re = self.res_end
        if re >= 0:
            qn[re] = bd.reservoir_flow(
                g_e[re : re + 1], d_end[re : re + 1], np.array([self.head_res_m]), self.res_cc
            )[0]
        # source
        se = self.src_end
        q_in = 0.0
        if se >= 0:
            q_cmd = self.q_src + self.dt * (self.qset - self.q_src) / self.spec.controller_tau_s
            q_in, self.capped = bd.source_flow(g_e[se], d_end[se], q_cmd, self.head_cap_m)
            qn[se] = -q_in
            self.q_src = q_in
        # junctions
        leak = 0.0
        if self.junction_nodes:
            self.demand[:] = 0.0
            if self.leak_local >= 0:
                leak = self.leak_k * math.sqrt(
                    max(self.node_head[self.leak_local] - self.junction_z[self.leak_local], 0.0)
                )
                self.demand[self.leak_local] = leak
            hn = bd.junction_heads(
                g_e[self.j_end],
                d_end[self.j_end],
                self.j_local,
                len(self.junction_nodes),
                self.demand,
            )
            self.node_head = hn
            qn[self.j_end] = g_e[self.j_end] * (d_end[self.j_end] - hn[self.j_local])
        # series elements
        if self.series:
            bs = self.b_end[self.s_e1] + self.b_end[self.s_e2]
            w = d_end[self.s_e1] - d_end[self.s_e2]
            closed = self.closed.copy()
            q_free = series_flow(bs, w, self.shutoff, self.k2, closed)
            for node, cv in self.checks.items():
                k = self.series_index[node]
                if not cv.update(float(q_free[k]), self.dt, t_new):
                    closed[k] = True
            q_s = np.where(closed, 0.0, q_free)
            for node, law in (self.spec.flow_schedules or {}).items():
                q_s[self.series_index[node]] = law(t_new)  # an imposed flow (verification cases)
            qn[self.s_e1] = q_s
            qn[self.s_e2] = -q_s
        # assign end points
        sgn = np.where(self.end_to, 1.0, -1.0)
        q_new[self.end_pt] = sgn * qn
        h_new[self.end_pt] = c_end - self.b_end * qn
        # ledger
        self.ledger.inflow_m3 += q_in * self.dt
        self.ledger.outflow_m3 += (
            float(qn[self.tank_ends_a].sum() + (qn[re] if re >= 0 else 0.0)) * self.dt
        )
        self.ledger.leak_m3 += leak * self.dt
        self.ledger.storage_m3 = float(np.dot(self.storage_w, h_new)) - self.storage0
        self.h, self.q = h_new, q_new
        np.minimum(self.h_min, h_new, out=self.h_min)
        below = bool(
            np.any(self.rho * self.g * (h_new - self.z) + self.model.patm <= self.vapor_pa)
        )
        self.phase.update(t_new, below)
        self.t, self.step_index = t_new, self.step_index + 1

    # --- running, probes, state ----------
    def point_index(self, edge_id: str, fraction: float) -> int:
        i = self.edge_index[edge_id]
        return int(self.first[i] + round(fraction * self.grid[i].reaches))

    def run(
        self, t_end: float, probes: list[Probe] | None = None, stride: int = 1
    ) -> dict[str, np.ndarray]:
        probes = probes or []
        idx = [self.point_index(p.edge_id, p.fraction) for p in probes]
        n = int(round((t_end - self.t) / self.dt))
        rec: dict[str, list[float]] = {
            "t": [],
            **{f"{p.name}.H": [] for p in probes},
            **{f"{p.name}.Q": [] for p in probes},
        }
        for k in range(n):
            self.step()
            if probes and k % stride == 0:
                rec["t"].append(self.t)
                for p, ix in zip(probes, idx, strict=True):
                    rec[f"{p.name}.H"].append(self.h[ix])
                    rec[f"{p.name}.Q"].append(self.q[ix])
        self.phase.close(self.t)
        return {k: np.array(v) for k, v in rec.items()}

    def pressure_pa_gauge(self, edge_id: str, fraction: float) -> float:
        ix = self.point_index(edge_id, fraction)
        return float(self.rho * self.g * (self.h[ix] - self.z[ix]))

    def end_state(self, edge_id: str, end: str) -> tuple[float, float]:
        """(piezometric head m, flow m3/s in the edge direction) at an end of an edge."""
        ix = self.point_index(edge_id, 0.0 if end == "from" else 1.0)
        return float(self.h[ix]), float(self.q[ix])

    def get_state(self) -> dict[str, Any]:
        keys = (
            "h", "q", "t", "step_index", "alpha", "motion", "shutoff", "k2", "closed",
            "pump_running", "checks", "pending_valves", "pending_setpoints", "pending_stops",
            "qset", "q_src", "ledger", "h_min", "phase", "node_head", "capped",
        )  # fmt: skip
        return copy.deepcopy({k: getattr(self, k) for k in keys})

    def set_state(self, state: dict[str, Any]) -> None:
        for k, v in copy.deepcopy(state).items():
            setattr(self, k, v)
