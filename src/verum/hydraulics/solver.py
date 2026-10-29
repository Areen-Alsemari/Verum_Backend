"""Damped Newton solve for node total heads on a pipe network.

Inputs: edges (each with a flow law), the nodes whose head is fixed, the
external inflow at nodes, a tolerance and an iteration limit. Outputs: node
heads, edge flows and the node-balance residual.
Key assumptions:
    * Unknowns are node total heads (m). The flow of an edge is obtained from
      the head difference across it by inverting its loss law; the Jacobian is
      assembled from the analytic slope of that inverse (one over the slope of
      the loss law, which is differenced numerically).
    * Newton steps are damped by backtracking on the largest node imbalance.
    * Flow may be negative: nothing clips it.
    * Every connected component must contain a fixed-head node; otherwise the
      heads are undetermined and the solve is refused.
    * The tolerance is on the largest node imbalance in m3/s.

Source: ``revised/02_hydraulic_model.md`` section 3 (steady equations, signed
flow); ``docs/design_decisions.md`` D8 (conservation tolerance).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

from verum.hydraulics.errors import ConvergenceError, HydraulicInputError

SLOPE_FLOOR = 1e-12
MIN_LOSS_SLOPE = 1e-12


class FlowLaw:
    """Flow as a function of the head difference ``delta = H_a - H_b``."""

    def evaluate(self, delta: float) -> tuple[float, float]:
        """Flow and slope together (one inversion instead of two)."""
        return self.flow(delta), self.slope(delta)

    def flow(self, delta: float) -> float:
        raise NotImplementedError

    def slope(self, delta: float) -> float:
        raise NotImplementedError


@dataclass(frozen=True)
class LossLaw(FlowLaw):
    """A pipe: ``delta`` equals a monotone signed loss of the flow."""

    loss: Callable[[float], float]

    def flow(self, delta: float) -> float:
        if delta == 0.0:
            return 0.0
        target = abs(delta)
        hi = 1e-3
        while self.loss(hi) < target:
            hi *= 2.0
            if hi > 1e4:
                raise ConvergenceError("head difference is beyond any plausible flow")
        q = brentq(lambda x: self.loss(x) - target, 0.0, hi, xtol=1e-15, rtol=1e-13)
        return math.copysign(q, delta)

    def slope(self, delta: float) -> float:
        return self.evaluate(delta)[1]

    def evaluate(self, delta: float) -> tuple[float, float]:
        flow = self.flow(delta)
        q = abs(flow)
        step = max(1e-6 * q, 1e-9)
        low = max(q - step, 0.0)
        d_loss = (self.loss(q + step) - self.loss(low)) / (q + step - low)
        return flow, 1.0 / max(d_loss, MIN_LOSS_SLOPE)


@dataclass(frozen=True)
class OneWay(FlowLaw):
    """A non-return element: no flow against the edge direction."""

    inner: FlowLaw

    def flow(self, delta: float) -> float:
        return self.inner.flow(delta) if delta > 0 else 0.0

    def slope(self, delta: float) -> float:
        return self.inner.slope(delta) if delta > 0 else SLOPE_FLOOR

    def evaluate(self, delta: float) -> tuple[float, float]:
        return self.inner.evaluate(delta) if delta > 0 else (0.0, SLOPE_FLOOR)


@dataclass(frozen=True)
class Edge:
    """A solver edge from ``a`` to ``b`` with a flow law."""

    name: str
    a: str
    b: str
    law: FlowLaw


@dataclass(frozen=True)
class Solution:
    heads: dict[str, float]
    flows: dict[str, float]
    residuals: dict[str, float]
    iterations: int


def _components(edges: list[Edge]) -> dict[str, int]:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        parent[find(e.a)] = find(e.b)
    roots = {find(n): i for i, n in enumerate(sorted({find(n) for n in list(parent)}))}
    return {n: roots[find(n)] for n in list(parent)}


def _initial_heads(
    edges: list[Edge],
    fixed: Mapping[str, float],
    inflow: Mapping[str, float],
    initial: Mapping[str, float] | None = None,
) -> dict[str, float]:
    comp = _components(edges)
    fixed_by_comp: dict[int, list[float]] = defaultdict(list)
    for node, head in fixed.items():
        if node in comp:
            fixed_by_comp[comp[node]].append(head)
    heads = dict(fixed)
    for node, c in comp.items():
        if node in fixed:
            continue
        if not fixed_by_comp[c]:
            raise HydraulicInputError(f"node {node} has no fixed-head node in its component")
        if initial is not None and node in initial:
            heads[node] = initial[node]
            continue
        mean = sum(fixed_by_comp[c]) / len(fixed_by_comp[c])
        heads[node] = mean + (5.0 if inflow.get(node, 0.0) > 0 else 0.0)
    return heads


def _evaluate(
    edges: list[Edge], heads: Mapping[str, float]
) -> tuple[dict[str, float], dict[str, float]]:
    flows, slopes = {}, {}
    for e in edges:
        flows[e.name], slopes[e.name] = e.law.evaluate(heads[e.a] - heads[e.b])
    return flows, slopes


def _flows_only(edges: list[Edge], heads: Mapping[str, float]) -> dict[str, float]:
    return {e.name: e.law.flow(heads[e.a] - heads[e.b]) for e in edges}


def _balance(
    edges: list[Edge], flows: Mapping[str, float], inflow: Mapping[str, float]
) -> dict[str, float]:
    """Net outflow minus external inflow at every node (zero when balanced)."""
    out: dict[str, float] = defaultdict(float)
    for e in edges:
        out[e.a] += flows[e.name]
        out[e.b] -= flows[e.name]
    for node, q in inflow.items():
        out[node] -= q
    return dict(out)


def solve_heads(
    edges: list[Edge],
    fixed: Mapping[str, float],
    inflow: Mapping[str, float],
    tolerance: float,
    max_iterations: int,
    initial: Mapping[str, float] | None = None,
) -> Solution:
    """Solve node heads for the given edges and boundary data.

    ``initial`` warm-starts the free nodes it names; the result does not depend on it
    beyond the iteration path.
    """
    heads = _initial_heads(edges, fixed, inflow, initial)
    free = sorted(n for n in heads if n not in fixed)
    index = {n: i for i, n in enumerate(free)}
    for iteration in range(max_iterations + 1):
        flows, slopes = _evaluate(edges, heads)
        balance = _balance(edges, flows, inflow)
        worst = max((abs(balance[n]) for n in free), default=0.0)
        if worst < tolerance:
            return Solution(dict(heads), flows, {n: balance[n] for n in free}, iteration)
        if iteration == max_iterations:
            break
        heads = _newton_step(edges, heads, free, index, flows, slopes, balance, inflow, worst)
    raise ConvergenceError(f"no convergence in {max_iterations} iterations")


def _newton_step(
    edges: list[Edge],
    heads: dict[str, float],
    free: list[str],
    index: dict[str, int],
    flows: Mapping[str, float],
    slopes: Mapping[str, float],
    balance: Mapping[str, float],
    inflow: Mapping[str, float],
    worst: float,
) -> dict[str, float]:
    n = len(free)
    jac = np.zeros((n, n))
    for e in edges:
        s = slopes[e.name]
        ia, ib = index.get(e.a), index.get(e.b)
        if ia is not None:
            jac[ia, ia] += s
            if ib is not None:
                jac[ia, ib] -= s
        if ib is not None:
            jac[ib, ib] += s
            if ia is not None:
                jac[ib, ia] -= s
    rhs = -np.array([balance[x] for x in free])
    try:
        step = np.linalg.solve(jac, rhs)
    except np.linalg.LinAlgError as exc:
        raise ConvergenceError("singular Jacobian") from exc
    merit0 = sum(balance[x] ** 2 for x in free)
    alpha = 1.0
    for _ in range(40):
        trial = dict(heads)
        for node, i in index.items():
            trial[node] = heads[node] + alpha * step[i]
        f_trial = _flows_only(edges, trial)
        bal = _balance(edges, f_trial, inflow)
        if sum(bal[x] ** 2 for x in free) < (1 - 2e-4 * alpha) * merit0:
            return trial
        alpha *= 0.5
    raise ConvergenceError("line search failed to reduce the node imbalance")
