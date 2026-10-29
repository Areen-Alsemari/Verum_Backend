"""The adapter between the hidden truth store and the sensor chain.

Inputs: an episode directory written by the engine. Outputs: ``observations.jsonl.gz`` and
``observation_audit.jsonl.gz`` in the same directory (the manifest is rewritten), and the
rows in memory.
Key assumptions:
    * This is the only module of ``verum.sensors`` that imports from ``verum.truth`` (a
      static test enforces it). It reads the hydraulic-state rows and the episode record and
      hands plain arrays to ``chain``.
    * Unit conversion happens first: m3/s to m3/h, absolute pressure to gauge with the
      atmosphere of the episode stratum (decision D27), K to C.
    * A pressure that the solve could not determine (a closed path) is held at the last
      determined value; a leading gap takes the first determined value.
    * Event tags (valve contacts, pump indicators, LSHH) are rows at t = 0 and at each
      change. A valve open contact follows decision D31 (assert at alpha 0.98, release below
      0.97, delay equal to the lag of the table). An LSHH row is the detector output of the
      engine (which already includes the detector delay of decision D33), seen after the
      comms delay.
    * A quantity that the hydraulic solve never determined in the episode (for example the
      pressure of an idle branch) gives rows with a null value, availability
      ``missing_sample`` and quality ``bad``: nothing is invented in its place.
    * The six withheld tags have no specification and therefore produce no row.
    * Every continuous tag has its own random streams (noise, dropout) named after the tag.

Source: ``docs/design_decisions.md`` D27 to D33.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from verum.rng import RandomStreams
from verum.sensors import chain
from verum.sensors.specs import SensorConfig, TagSpec, load_sensor_config
from verum.truth import MANIFEST, file_hashes, read_rows

SCHEMA_VERSION = "0.5.0"
OBSERVATIONS = "observations"
AUDIT = "observation_audit"
SIDE_RANK = {"pre_event": 0, None: 1, "post_event": 2}


@dataclass(frozen=True)
class ObservationResult:
    observations: list[dict[str, Any]]
    audit: list[dict[str, Any]]


def _utc(start: str, t: float) -> str:
    base = datetime.fromisoformat(start.replace("Z", "+00:00"))
    stamp = (base + timedelta(seconds=t)).astimezone(UTC)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}Z"


def _series(
    rows: list[dict[str, Any]], record_type: str, element: str
) -> list[tuple[float, str | None, dict[str, Any]]]:
    picked = [
        (r["t_sim_s"], r["side"], r["payload"])
        for r in rows
        if r["record_type"] == record_type and r["element_id"] == element
    ]
    picked.sort(key=lambda x: (x[0], SIDE_RANK[x[1]]))
    return picked


def _convert(field: str, value: Any, patm: float) -> float | None:
    if value is None:
        return None
    if field == "flow_m3s":
        return float(value) * 3600.0
    if field in ("pressure_pa_abs", "p_from_pa_abs", "p_to_pa_abs"):
        return (float(value) - patm) / 1.0e5
    if field in ("temperature_K", "fluid_temperature_K"):
        return float(value) - 273.15
    return float(value)


def _nodes(
    series: list[tuple[float, str | None, dict[str, Any]]], field: str, patm: float
) -> chain.Nodes:
    ts, xs, jumps = [], [], []
    last: float | None = None
    for t, side, payload in series:
        x = _convert(field, payload[field], patm)
        if x is None:
            x = last  # undetermined (closed path): hold the last determined value
        if x is None:
            continue
        last = x
        ts.append(t)
        xs.append(x)
        jumps.append(side == "post_event")
    first = next((x for x in xs), 0.0)
    for i, x in enumerate(xs):
        if x is None:
            xs[i] = first
    return chain.Nodes(np.array(ts), np.array(xs), np.array(jumps))


def _row(
    cfg: SensorConfig, episode: str, tag: str, t: float, avail: float, value: float | None,
    unit: str, quality: str, status: str,
) -> dict[str, Any]:  # fmt: skip
    return {
        "schema_version": SCHEMA_VERSION, "dataset": OBSERVATIONS, "episode_id": episode,
        "tag_id": tag, "t_sim_s": t, "t_available_s": avail,
        "timestamp_utc": _utc(cfg.episode_start_utc, t), "value": value, "unit": unit,
        "quality_flag": quality, "availability_status": status,
    }  # fmt: skip


def _audit(episode: str, tag: str, t: float, source: float, used: float) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "dataset": AUDIT, "episode_id": episode,
        "tag_id": tag, "t_sim_s": t, "t_source_s": source, "max_truth_time_used_s": used,
        "hidden": True,
    }  # fmt: skip


def _continuous(
    cfg: SensorConfig, spec: TagSpec, nodes: chain.Nodes, streams: RandomStreams,
    episode: str, duration: float,
) -> ObservationResult:  # fmt: skip
    assert spec.interval_s and spec.range_lo is not None and spec.range_hi is not None
    undetermined = len(nodes.t) == 0
    y = np.zeros(0) if undetermined else chain.lag_response(nodes, spec.lag_s)
    phase = chain.sample_phase(spec.tag, spec.interval_s)
    times = np.arange(0.0, duration - phase + 1e-9, spec.interval_s) + phase
    noise = streams.stream(f"sensor/{spec.tag}/noise").standard_normal(len(times))
    drop = streams.stream(f"sensor/{spec.tag}/dropout").random(len(times))
    sigma, p_drop = cfg.sigma(spec.noise_class), cfg["dropout_probability"]
    obs, aud = [], []
    for k, t in enumerate(times):
        t = float(t)
        avail = t + spec.comms_delay_s
        if undetermined or drop[k] < p_drop:
            obs.append(
                _row(cfg, episode, spec.tag, t, avail, None, spec.unit, "bad", "missing_sample")
            )
        else:
            if spec.mode == "window_mean":
                assert spec.window_s
                v = chain.trailing_mean(nodes, y, spec.lag_s, t, spec.window_s)
            else:
                v = chain.value_at(nodes, y, spec.lag_s, t)
            v += float(noise[k]) * sigma  # bias and drift hooks are zero here
            v, clipped = chain.quantise_clip(
                v, spec.range_lo, spec.range_hi, int(cfg["adc_steps"]), sigma
            )
            obs.append(
                _row(cfg, episode, spec.tag, t, avail, v, spec.unit,
                     "suspect" if clipped else "good", "measured")
            )  # fmt: skip
        aud.append(_audit(episode, spec.tag, t, t, t))
    return ObservationResult(obs, aud)


def _contact_changes(
    series: list[tuple[float, str | None, dict[str, Any]]], on: float, off: float
) -> list[tuple[float, int]]:
    """(time, state) of the open contact: initial state first, then every change."""
    out: list[tuple[float, int]] = []
    prev_t, prev_a, state = 0.0, None, 0
    for t, _side, payload in series:
        a = float(payload["position_frac"])
        if prev_a is None:
            state = int(a >= on)
            out.append((t, state))
        else:
            tc = t
            if state == 0 and a >= on:
                tc = (
                    prev_t + (on - prev_a) / (a - prev_a) * (t - prev_t)
                    if t > prev_t and a > prev_a
                    else t
                )
                state = 1
                out.append((tc, 1))
            elif state == 1 and a < off:
                tc = (
                    prev_t + (prev_a - off) / (prev_a - a) * (t - prev_t)
                    if t > prev_t and a < prev_a
                    else t
                )
                state = 0
                out.append((tc, 0))
        prev_t, prev_a = t, a
    return out


def _flip_changes(values: list[tuple[float, int]]) -> list[tuple[float, int]]:
    out = [values[0]]
    for t, v in values[1:]:
        if v != out[-1][1]:
            out.append((t, v))
    return out


def _event_rows(
    cfg: SensorConfig, spec: TagSpec, changes: list[tuple[float, int]], episode: str,
    duration: float, delay: float,
) -> ObservationResult:  # fmt: skip
    obs, aud = [], []
    for i, (tc, state) in enumerate(changes):
        t = 0.0 if i == 0 else tc + delay
        if t > duration:
            continue
        obs.append(
            _row(
                cfg,
                episode,
                spec.tag,
                t,
                t + spec.comms_delay_s,
                float(state),
                "bool",
                "good",
                "measured",
            )
        )
        aud.append(_audit(episode, spec.tag, t, tc, tc))
    return ObservationResult(obs, aud)


def observe_rows(directory: Path, config_dir: Path | None = None) -> ObservationResult:
    cfg = load_sensor_config(config_dir)
    meta = json.loads((directory / "episode.json").read_text(encoding="utf-8"))
    episode, duration, patm = (
        meta["episode_id"],
        float(meta["duration_s"]),
        meta["atmosphere_pa_abs"],
    )
    streams = RandomStreams(int(meta["seed"]))
    rows = read_rows(directory, "hydraulic_state")
    observations: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for tag, spec in cfg.tags.items():
        ref = spec.ref
        if spec.kind == "continuous":
            series = _series(rows, ref["record_type"], ref["element_id"])
            res = _continuous(
                cfg, spec, _nodes(series, ref["field"], patm), streams, episode, duration
            )
        elif tag.startswith("XV-"):
            series = _series(rows, "valve_state", ref["element_id"])
            changes = _contact_changes(
                series,
                cfg["contact_open_alpha"],
                cfg["contact_open_alpha"] - cfg["contact_hysteresis"],
            )
            res = _event_rows(cfg, spec, changes, episode, duration, spec.lag_s)
        elif tag.startswith("P-"):
            series = _series(rows, "pump_state", ref["element_id"])
            changes = _flip_changes([(t, int(p["run_state"] == "running")) for t, _s, p in series])
            res = _event_rows(cfg, spec, changes, episode, duration, spec.lag_s)
        else:  # LSHH: the detector output of the engine, already delayed (decision D33)
            series = _series(rows, "protection_state", "TK-" + tag[-3:])
            changes = _flip_changes([(t, int(bool(p["trip_latched"]))) for t, _s, p in series])
            res = _event_rows(cfg, spec, changes, episode, duration, 0.0)
        observations += res.observations
        audit += res.audit
    key = lambda r: (r["t_sim_s"], r["tag_id"])  # noqa: E731
    observations.sort(key=key)
    audit.sort(key=key)
    return ObservationResult(observations, audit)


def _write(directory: Path, name: str, rows: list[dict[str, Any]]) -> None:
    with (directory / f"{name}.jsonl.gz").open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as gz:
            for row in rows:
                line = json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n"
                gz.write(line.encode("utf-8"))


def observe_episode(directory: Path, config_dir: Path | None = None) -> ObservationResult:
    """Compute the observations of an episode directory and write them next to the truth."""
    result = observe_rows(directory, config_dir)
    _write(directory, OBSERVATIONS, result.observations)
    _write(directory, AUDIT, result.audit)
    hashes = file_hashes(directory)
    lines = [f"{digest}  {name}" for name, digest in hashes.items()]
    (directory / MANIFEST).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
