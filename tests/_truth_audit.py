"""Post-hoc mass audit that reads only the written truth files.

The audit recomputes the network liquid balance from the tank rows, checks each tank ledger against
its tank state and the residual written by the engine against the recomputed one, and returns the
largest residual and a list of violations. It uses gzip and json only and imports neither the
engine, the ledger nor the truth package. The balance and the tolerance are described in the "Mass
audit of written truth files" section of the verification notes.

See D8 and D20.
"""

from __future__ import annotations

import gzip
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

RATE_KG_S = 4.2e-4
UNIT_ROUNDOFF = 2.0**-53


def _rows(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def audit(directory: Path) -> dict[str, Any]:
    rho = json.loads((directory / "episode.json").read_text(encoding="utf-8"))[
        "fluid_density_kg_m3"
    ]
    volumes: dict[float, dict[str, float]] = {}
    for row in _rows(directory / "hydraulic_state.jsonl.gz"):
        if row["record_type"] == "tank_state" and row["side"] != "pre_event":
            volumes.setdefault(row["t_sim_s"], {})[row["element_id"]] = row["payload"]["volume_m3"]
    network: dict[float, dict[str, Any]] = {}
    tanks: dict[float, dict[str, float]] = {}
    for row in _rows(directory / "mass_ledger.jsonl.gz"):
        if row["side"] == "pre_event":
            continue
        if row["scope"] == "network":
            network[row["t_sim_s"]] = row
        else:
            tanks.setdefault(row["t_sim_s"], {})[row["scope"]] = row["liquid_kg"]
    times = sorted(network)
    mass0 = rho * sum(volumes[times[0]].values())
    violations: list[str] = []
    abs_sum, terms, previous = 0.0, 0, None
    worst = 0.0
    for t in times:
        mass = rho * sum(volumes[t].values())
        recv, deliv = network[t]["cumulative_received_kg"], network[t]["cumulative_delivered_kg"]
        if previous is not None:
            abs_sum += abs(recv - previous[0]) + abs(deliv - previous[1]) + abs(mass - previous[2])
            terms += 3
        previous = (recv, deliv, mass)
        residual = recv - deliv - (mass - mass0)
        tolerance = RATE_KG_S * t + max(terms - 1, 0) * UNIT_ROUNDOFF * (abs_sum + mass0 + mass)
        worst = max(worst, abs(residual))
        if abs(residual) > tolerance:
            violations.append(f"t={t:g}: residual {residual:.6g} kg exceeds {tolerance:.6g} kg")
        if abs(residual - network[t]["residual_kg"]) > 1e-6 + 1e-9 * abs(mass):
            violations.append(f"t={t:g}: written residual differs from the recomputed one")
        for tank, kg in tanks.get(t, {}).items():
            if abs(kg - rho * volumes[t][tank]) > 1e-6:
                violations.append(f"t={t:g}: ledger mass of {tank} differs from its tank state")
    return {"max_abs_residual_kg": worst, "violations": violations, "times": len(times)}


def rewrite(
    src: Path, dst: Path, dataset: str, change: Callable[[dict[str, Any]], dict[str, Any]]
) -> Path:
    """Copy an episode directory and apply ``change`` to every row of one dataset."""
    shutil.copytree(src, dst)
    path = dst / f"{dataset}.jsonl.gz"
    rows = [change(r) for r in _rows(path)]
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return dst
