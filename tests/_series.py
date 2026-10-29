"""Streaming reader that turns an episode directory into compact time series.

Inputs: an episode directory written by the engine. Outputs: a ``Series`` with the
quantities the tests need, and a count of rows that failed schema validation.
Key assumptions: the reader uses only ``gzip`` and ``json`` and the schemas, not the
engine, so it also serves as an independent reader of the written files. Every row
of every dataset is validated against its schema during the single pass.

Source: ``schemas/hydraulic_state.schema.json`` and the other proposed schemas.
"""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from verum.contracts import validator

DATASETS = ("hydraulic_state", "solver_diagnostics", "mass_ledger", "events")


@dataclass
class Series:
    directory: Path
    rows: dict[str, int] = field(default_factory=dict)
    invalid: dict[str, int] = field(default_factory=dict)
    tank: dict[str, list[tuple[float, str | None, float, float, float]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    valve: dict[
        str, list[tuple[float, str | None, float | None, bool | None, bool | None, float]]
    ] = field(default_factory=lambda: defaultdict(list))
    edge: dict[str, list[tuple[float, str | None, float]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    node: dict[str, list[tuple[float, str | None, float | None]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    protection: dict[str, list[tuple[float, str | None, str, bool, str]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    pump: dict[str, list[tuple[float, str | None, str, float, str, float | None]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    ledger: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    episode: dict[str, Any] = field(default_factory=dict)

    def grid(self, series: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
        """Rows that are not pre-event rows (grid rows and post-event rows)."""
        return [r for r in series if r[1] != "pre_event"]


def _always_valid(_row: dict[str, Any]) -> bool:
    return True


def _lines(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        yield from handle


def _state_row(s: Series, row: dict[str, Any]) -> None:
    t, side, kind, el, p = (
        row["t_sim_s"],
        row["side"],
        row["record_type"],
        row["element_id"],
        row["payload"],
    )
    if kind == "tank_state":
        s.tank[el].append((t, side, p["level_m"], p["volume_m3"], p["net_inflow_m3s"]))
    elif kind == "valve_state":
        s.valve[el].append(
            (
                t,
                side,
                p["position_frac"],
                p["commanded_open"],
                p["physically_closed"],
                p["flow_m3s"],
            )
        )
    elif kind == "edge_state":
        s.edge[el].append((t, side, p["flow_m3s"]))
    elif kind == "node_state":
        s.node[el].append((t, side, p["pressure_pa_abs"]))
    elif kind == "protection_state":
        s.protection[el].append((t, side, p["state"], p["trip_latched"], p["signal_source"]))
    elif kind == "pump_state":
        s.pump[el].append(
            (
                t,
                side,
                p["run_state"],
                p["flow_m3s"],
                p["phase_validity_status"],
                p["NPSH_margin_ratio"],
            )
        )


def load_series(directory: Path, validate_rows: bool = True) -> Series:
    s = Series(directory)
    s.episode = json.loads((directory / "episode.json").read_text(encoding="utf-8"))
    for dataset in DATASETS:
        check = validator(dataset).is_valid if validate_rows else _always_valid
        count = bad = 0
        for line in _lines(directory / f"{dataset}.jsonl.gz"):
            row = json.loads(line)
            count += 1
            bad += 0 if check(row) else 1
            if dataset == "hydraulic_state":
                _state_row(s, row)
            elif dataset == "solver_diagnostics":
                s.diagnostics.append(row)
            elif dataset == "mass_ledger":
                s.ledger.append(row)
            else:
                s.events.append(row)
        s.rows[dataset], s.invalid[dataset] = count, bad
    return s
