"""The inspection truth of an episode: the true state that the inspection actions need.

Rows are taken from the written hydraulic-state rows at a 60 s grid and the last time, at every
event time and at every knot of a fault trajectory, with a pre-event and a post-event row at a
discontinuity. Each row adds the faults and the noise-free tag values from the fault
specifications and the sensor chain.
The file is evaluator data and is built after the truth files and the observations are written.
It changes no other output; the manifest of the directory is written again to list it.

See D156.
"""

from __future__ import annotations

import gzip
import json
import math
from pathlib import Path
from typing import Any

from verum.contracts import validate
from verum.faults import FaultSet, FaultSpec, instance_ids
from verum.faults.spec import LEAK
from verum.faults.truth import parameter_name, parameter_value
from verum.sensors import chain
from verum.sensors.adapter import SIDE_RANK, _contact_changes, _nodes, _series
from verum.sensors.specs import SensorConfig, TagSpec, load_sensor_config
from verum.sim import rows as rw
from verum.truth import MANIFEST, file_hashes, read_rows

DATASET = "inspection_truth"
FILE = "inspection_truth.jsonl.gz"
GRID_S = 60.0
PRE, POST = "pre_event", "post_event"
Key = tuple[float, str | None]
Payloads = dict[tuple[str, str, float, str | None], dict[str, Any]]
SI_VALUE = {"m3/h": (1 / 3600.0, 0.0), "barg": (1.0e5, 0.0), "C": (1.0, 273.15), "m": (1.0, 0.0)}


def _index(rows: list[dict[str, Any]]) -> Payloads:
    return {
        (r["record_type"], r["element_id"], r["t_sim_s"], r["side"]): r["payload"] for r in rows
    }


def _times(rows: list[dict[str, Any]], duration: float, specs: tuple[FaultSpec, ...]) -> list[Key]:
    """Row keys: the 60 s grid, the event times and the fault knots, in time order."""
    events = {r["t_sim_s"] for r in rows if r["side"] == PRE}
    steps = {s.onset_s for s in specs if s.ramp_s is None}
    keys: set[Key] = set()
    grid = [k * GRID_S for k in range(int(duration // GRID_S) + 1)] + [duration]
    knots = {t for s in specs for t in s.knot_times_s() if t <= duration}
    for t in sorted({*grid, *events, *knots}):
        if t in events or t in steps:
            keys |= {(t, PRE), (t, POST)}
        else:
            keys.add((t, None))
    return sorted(keys, key=lambda k: (k[0], SIDE_RANK[k[1]]))


class Reader:
    """The hydraulic-state rows of an episode and the sensor chain on them."""

    def __init__(self, directory: Path, faults: FaultSet | None, cfg: SensorConfig) -> None:
        meta = json.loads((directory / "episode.json").read_text(encoding="utf-8"))
        self.episode, self.duration = meta["episode_id"], float(meta["duration_s"])
        self.patm = float(meta["atmosphere_pa_abs"])
        self.cfg, self.specs = cfg, faults.specs if faults is not None else ()
        self.faults = faults
        self.rows = read_rows(directory, "hydraulic_state")
        self.roof_faults = []
        if (directory / "roof_constraints.json").exists():
            self.roof_faults = [row for row in read_rows(directory, "fault_truth")
                                if row["mechanism"] == "held_roof_withdrawal_v1"]
        self.payloads = _index(self.rows)
        self.tags = {t: s for t, s in cfg.tags.items() if s.kind == "continuous"}
        self.nodes, self.lagged = {}, {}
        for tag, spec in self.tags.items():
            ref = spec.ref
            self.nodes[tag] = _nodes(
                _series(self.rows, ref["record_type"], ref["element_id"]), ref["field"], self.patm
            )
            self.lagged[tag] = chain.lag_response(self.nodes[tag], spec.lag_s)
        spans = {t: s.range_hi - s.range_lo for t, s in self.tags.items()}  # type: ignore[operator]
        self.hook = faults.sensor_hook(spans) if faults is not None and faults.specs else None
        self._prime_frozen_readings()
        on = cfg["contact_open_alpha"]
        off = on - cfg["contact_hysteresis"]
        self.contacts = {
            v: _contact_changes(_series(self.rows, "valve_state", v), on, off) for v in rw.VALVES
        }

    def sample(self, tag: str, t: float) -> float:
        """The chain output for a tag at time ``t``, before the fault, noise and quantisation."""
        spec = self.tags[tag]
        if spec.mode == "window_mean":
            assert spec.window_s
            return chain.trailing_mean(
                self.nodes[tag], self.lagged[tag], spec.lag_s, t, spec.window_s
            )
        return chain.value_at(self.nodes[tag], self.lagged[tag], spec.lag_s, t)

    def _prime_frozen_readings(self) -> None:
        """A stuck sensor freezes at its first scheduled sample after the onset, as it does in the
        observations, so the hook is called once at that sample before any row is read."""
        if self.hook is None:
            return
        for spec in self.specs:
            if spec.variant != "stuck" or spec.asset_id not in self.tags:
                continue
            tag: TagSpec = self.tags[spec.asset_id]
            assert tag.interval_s
            phase = chain.sample_phase(tag.tag, tag.interval_s)
            k = max(0, math.ceil((spec.onset_s - phase) / tag.interval_s - 1e-12))
            t = phase + k * tag.interval_s
            self.hook(tag.tag, t, self.sample(tag.tag, t))

    def payload(self, rtype: str, element: str, key: Key) -> dict[str, Any]:
        t, side = key
        found = self.payloads.get((rtype, element, t, side))
        if found is None:
            found = self.payloads[(rtype, element, t, None)]
        return found

    def contact(self, valve: str, key: Key) -> int:
        t, side = key
        state = 0
        for tc, s in self.contacts[valve]:
            if tc < t or (tc == t and side != PRE):
                state = s
        return state


def _gauge(pressure_abs: float | None, patm: float) -> float:
    if pressure_abs is None:
        raise ValueError("a pressure of the inspection truth is undetermined")
    return pressure_abs - patm


def _tank_rows(rd: Reader, key: Key) -> dict[str, Any]:
    out = {}
    for tank in ("TK-101", "TK-102", "TK-103"):
        p = rd.payload("tank_state", tank, key)
        out[tank] = {
            "level_m": p["level_m"],
            "temperature_K": p["temperature_K"],
            "volume_m3": p["volume_m3"],
        }
    return out


def _edge_rows(rd: Reader, key: Key, edges: list[str]) -> dict[str, Any]:
    out = {}
    for edge in edges:
        p = rd.payload("edge_state", edge, key)
        out[edge] = {
            "flow_m3s": p["flow_m3s"],
            "p_from_pa_gauge": _gauge(p["p_from_pa_abs"], rd.patm),
            "p_to_pa_gauge": _gauge(p["p_to_pa_abs"], rd.patm),
        }  # fmt: skip
    return out


def _valve_rows(rd: Reader, key: Key) -> dict[str, Any]:
    out = {}
    for valve in rw.VALVES:
        p = rd.payload("valve_state", valve, key)
        out[valve] = {
            "commanded_open": p["commanded_open"], "position_frac": p["position_frac"],
            "contact_open": rd.contact(valve, key),
        }  # fmt: skip
    return out


def _pump_rows(rd: Reader, key: Key, t_fault: float) -> dict[str, Any]:
    out = {}
    for pump in rw.PUMPS:
        p = rd.payload("pump_state", pump, key)
        scale = rd.faults.pump_scale(t_fault, pump) if rd.faults is not None else 1.0
        out[pump] = {
            "run_state": p["run_state"], "speed_ratio": p["speed_ratio"], "head_scale": scale
        }  # fmt: skip
    return out


def _fault_rows(rd: Reader, key: Key, t_fault: float) -> tuple[list[Any], list[Any]]:
    leaks, faults = [], []
    for ident, spec in zip(instance_ids(rd.episode, rd.specs), rd.specs, strict=True):
        name, unit = parameter_name(spec)
        faults.append({
            "fault_instance_id": ident, "fault_type": spec.fault_type, "asset_id": spec.asset_id,
            "severity": spec.severity(t_fault), "parameter": name, "unit": unit,
            "parameter_value": parameter_value(spec, t_fault),
        })  # fmt: skip
        if spec.fault_type == LEAK:
            flow = rd.payload("edge_state", spec.asset_id, key).get("leak_flow_m3s", 0.0)
            leaks.append({
                "fault_instance_id": ident, "edge_id": spec.asset_id,
                "fraction": spec.position, "flow_m3s": flow,
            })  # fmt: skip
    for row in rd.roof_faults:
        modified = row["physical_parameter_modified"]
        faults.append({
            "fault_instance_id": row["fault_instance_id"], "fault_type": row["fault_type"],
            "asset_id": row["asset_id"], "severity": 1., "parameter": modified["name"],
            "unit": modified["unit"],
            "parameter_value": modified["fault_value_at_severity_one"]["value"],
        })
    return leaks, faults


def _tag_rows(rd: Reader, t_eval: float, t_fault: float) -> dict[str, Any]:
    out = {}
    for tag, spec in rd.tags.items():
        v = rd.sample(tag, t_eval)
        offset = 0.0 if rd.hook is None else rd.hook(tag, t_fault, v) - v
        scale, shift = SI_VALUE[spec.unit]
        out[tag] = {"value": v * scale + shift, "fault_offset": offset * scale}
    return out


def build_rows(
    directory: Path, faults: FaultSet | None, config_dir: Path | None = None
) -> list[Any]:
    """The inspection-truth rows of an episode directory, in time order."""
    rd = Reader(directory, faults, load_sensor_config(config_dir))
    order = _edge_order(rd)
    rows = []
    keys = set(_times(rd.rows, rd.duration, rd.specs))
    if rd.roof_faults:
        # Preserve the nonlinear displacement corners in evaluator interpolation too.
        tanks = {row["asset_id"] for row in rd.roof_faults}
        previous: dict[str, str] = {}
        for row in rd.rows:
            if row["record_type"] == "tank_state" and row["element_id"] in tanks:
                tank, regime = row["element_id"], row["payload"]["roof_state"]
                if tank in previous and previous[tank] != regime:
                    keys.add((row["t_sim_s"], row["side"]))
                previous[tank] = regime
    for key in sorted(keys, key=lambda k: (k[0], SIDE_RANK[k[1]])):
        t, side = key
        t_eval = math.nextafter(t, -math.inf) if side == PRE else t
        leaks, fault_rows = _fault_rows(rd, key, t_eval)
        rows.append({
            "schema_version": rw.SCHEMA_VERSION, "dataset": DATASET, "episode_id": rd.episode,
            "t_sim_s": t, "side": side, "tanks": _tank_rows(rd, key),
            "edges": _edge_rows(rd, key, order), "valves": _valve_rows(rd, key),
            "pumps": _pump_rows(rd, key, t_eval), "leaks": leaks, "faults": fault_rows,
            "tags": _tag_rows(rd, t_eval, t_eval), "hidden": True,
        })  # fmt: skip
    return rows


def _edge_order(rd: Reader) -> list[str]:
    seen: dict[str, None] = {}
    for r in rd.rows:
        if r["record_type"] == "edge_state":
            seen.setdefault(r["element_id"], None)
    return list(seen)


def write_inspection_truth(
    directory: Path, faults: FaultSet | None, config_dir: Path | None = None
) -> list[Any]:
    """Build, check against the closed schema and write ``inspection_truth.jsonl.gz``."""
    rows = build_rows(directory, faults, config_dir)
    with (directory / FILE).open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as gz:
            for row in rows:
                validate(DATASET, row)
                gz.write((json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n").encode())
    lines = [f"{digest}  {name}" for name, digest in file_hashes(directory).items()]
    (directory / MANIFEST).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows
