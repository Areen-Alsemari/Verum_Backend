"""Boundary and junction relations at pipe ends: tank, reservoir, source, closed end, junction.

Each pipe end has the compatibility relation H_pz = C_e - B_e Qn, where Qn is the flow leaving the
pipe into the node, and this module returns Qn for every end. The node head is a total head, and the
piezometric head of an end is the node head less the velocity head of the pipe at the previous step.
A tank holds constant head, a reservoir holds constant head behind its boundary law, and the source
imposes flow through a first-order controller with a 10 barg head cap. At a junction the flows sum
to the external demand, and all ends share the node head. A leak sink is taken explicitly.

See D43 and D44.
"""

from __future__ import annotations

import numpy as np


def tank_flow(g: np.ndarray, d: np.ndarray, head: np.ndarray) -> np.ndarray:
    return g * (d - head)


def reservoir_flow(
    g: np.ndarray, d: np.ndarray, head_res: np.ndarray, cc: np.ndarray
) -> np.ndarray:
    """Solve ``Qn = g (D - H_res - cc Qn|Qn|)`` for the flow into the reservoir."""
    w = g * (d - head_res)
    k = cc * g
    safe = np.where(k > 0.0, k, 1.0)
    root = (-1.0 + np.sqrt(1.0 + 4.0 * safe * np.abs(w))) / (2.0 * safe)
    return np.where(k > 0.0, np.sign(w) * root, w)


def junction_heads(
    g: np.ndarray, d: np.ndarray, node: np.ndarray, n_nodes: int, demand: np.ndarray
) -> np.ndarray:
    """Head of each junction node from ``sum g_e (D_e - H) = demand``."""
    num = np.bincount(node, weights=g * d, minlength=n_nodes) - demand
    den = np.bincount(node, weights=g, minlength=n_nodes)
    return num / den


def source_flow(g: float, d: float, flow_command: float, head_cap: float) -> tuple[float, bool]:
    """Flow into the pipe at the source end, and whether the head cap limits it.

    With the commanded flow Q entering the pipe the node head is H_n = D + Q/g. Above the cap the
    head is held at the cap and the flow follows.
    """
    head = d + flow_command / g
    if head <= head_cap:
        return flow_command, False
    return g * (head_cap - d), True
