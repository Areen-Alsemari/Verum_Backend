"""The sensor chain on arrays: lag, sampling or window mean, noise, quantisation, dropout.

Inputs: a truth series in engineering units as nodes (time, value, jump flag), the tag
specification and per-tag random generators. Outputs: sample times, values, quality and
availability.
Key assumptions:
    * Fixed order: unit-converted truth -> transport delay (none unless given) -> first-order
      lag -> sampling (instantaneous, or trailing window mean) -> bias and drift hooks
      (zero) -> noise -> quantisation and clipping -> dropout -> quality.
    * Event aware: the truth is piecewise linear between nodes; a node flagged ``jump`` is
      the post-event value at the same time as its predecessor, and the chain never
      interpolates across that pair. A sample at an event time reads the post-event state.
    * The first-order lag is discretised exactly for piecewise-linear input: over a step of
      length ``h`` from input ``x_a`` to ``x_b`` (slope ``s``),
      ``y(h) = a y0 + (1 - a)(x_a - s tau) + s h``, ``a = exp(-h/tau)``. The state is carried
      across steps and across jumps (a jump changes the input, not the state).
    * Noise and dropout draw one value per scheduled sample from the tag's own generators,
      whatever the outcome, so the draw order does not depend on earlier outcomes.

Source: ``docs/design_decisions.md`` D28 to D32; the audited reference test (lag step
response, window mean on a ramp, event sample at the event time).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Nodes:
    t: np.ndarray
    x: np.ndarray
    jump: np.ndarray  # True where the node is the post-event twin of its predecessor


def lag_response(nodes: Nodes, tau: float, y0: float | None = None) -> np.ndarray:
    """Lag output at every node; ``tau`` of zero returns the input."""
    n = len(nodes.t)
    if tau <= 0.0:
        return nodes.x.copy()
    y = np.empty(n)
    y[0] = nodes.x[0] if y0 is None else y0
    for i in range(1, n):
        if nodes.jump[i]:
            y[i] = y[i - 1]
            continue
        h = nodes.t[i] - nodes.t[i - 1]
        if tau <= 0.0 or h <= 0.0:
            y[i] = nodes.x[i] if tau <= 0.0 else y[i - 1]
            continue
        a = math.exp(-h / tau)
        s = (nodes.x[i] - nodes.x[i - 1]) / h
        y[i] = a * y[i - 1] + (1.0 - a) * (nodes.x[i - 1] - s * tau) + s * h
    return y


def value_at(nodes: Nodes, y: np.ndarray, tau: float, t: float) -> float:
    """Lag output at an arbitrary time (post-event state at an event time)."""
    j = int(np.searchsorted(nodes.t, t, side="right")) - 1
    if j < 0:
        return float(y[0])
    if j >= len(nodes.t) - 1 or nodes.t[j] == t:
        return float(y[j])
    h = t - nodes.t[j]
    if tau <= 0.0:
        frac = h / (nodes.t[j + 1] - nodes.t[j])
        return float(nodes.x[j] + frac * (nodes.x[j + 1] - nodes.x[j]))
    a = math.exp(-h / tau)
    s = (nodes.x[j + 1] - nodes.x[j]) / (nodes.t[j + 1] - nodes.t[j])
    return float(a * y[j] + (1.0 - a) * (nodes.x[j] - s * tau) + s * h)


def trailing_mean(nodes: Nodes, y: np.ndarray, tau: float, t: float, window: float) -> float:
    """Mean of the lag output over ``[t - window, t]`` (the window starts at 0 at the earliest)."""
    lo = max(t - window, float(nodes.t[0]))
    if t <= lo:
        return value_at(nodes, y, tau, t)
    inside = (nodes.t > lo) & (nodes.t < t)
    ts = np.concatenate(([lo], nodes.t[inside], [t]))
    ys = np.array([value_at(nodes, y, tau, lo)] + list(y[inside]) + [value_at(nodes, y, tau, t)])
    return float(np.trapezoid(ys, ts) / (t - lo))


def sample_phase(tag: str, interval_s: float) -> float:
    """Decision D32: SHA-256 of the tag name, modulo the interval in milliseconds."""
    digest = hashlib.sha256(tag.encode("utf-8")).digest()
    millis = int(round(interval_s * 1000.0))
    return (int.from_bytes(digest[:8], "big") % millis) / 1000.0


def quantise_clip(
    value: float, lo: float, hi: float, steps: int, sigma: float
) -> tuple[float, bool]:
    """Round to ``(hi - lo)/steps`` and clip to the range (decision D29, version 1.1).

    Returns the value and whether it is a real overrange: clipped by more than three noise
    standard deviations. A value that is outside the range by noise only is clipped and not
    flagged."""
    if value < lo or value > hi:
        over = (lo - value) if value < lo else (value - hi)
        return (lo if value < lo else hi), over > 3.0 * sigma
    step = (hi - lo) / steps
    return lo + round((value - lo) / step) * step, False
