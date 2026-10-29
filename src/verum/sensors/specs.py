"""Sensor specifications: the 30 emitted tags and the chain parameters.

Inputs: ``config/sensor_specs.json`` (units, ranges, rates, lag and comms delay from table
6.1.1 of the instrumentation document), ``config/sensors.json`` (noise, quantisation,
dropout, contact thresholds, detector) and ``config/canonical_sensor_contract.json``.
Outputs: ``SensorConfig`` with one ``TagSpec`` per emitted tag.
Key assumptions:
    * Every number is a ``ParamValue``; reading an unresolved one raises.
    * Only tags with status ``emit`` in the contract have a specification; the six withheld
      tags have none, so no row can be produced for them.
    * The table and the contract are cross-checked on load: the mapping reference of each
      tag must be the contract's.

Source: ``revised/04_instrumentation_inspection.md`` section 6.1.1;
``docs/design_decisions.md`` D27 to D33.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir
from verum.params import ParamValue, ParamValueError


@dataclass(frozen=True)
class TagSpec:
    tag: str
    kind: str  # "continuous" or "event"
    ref: dict[str, str]
    lag_s: float
    comms_delay_s: float
    unit: str
    range_lo: float | None = None
    range_hi: float | None = None
    interval_s: float | None = None
    mode: str | None = None
    window_s: float | None = None

    @property
    def noise_class(self) -> str:
        return {"m": "level", "m3/h": "flow", "barg": "pressure", "C": "temperature"}[self.unit]


@dataclass(frozen=True)
class SensorConfig:
    tags: dict[str, TagSpec]
    parameters: dict[str, ParamValue]
    episode_start_utc: str

    def __getitem__(self, name: str) -> float:
        return float(self.parameters[name].value)

    def sigma(self, noise_class: str) -> float:
        return {
            "level": self["noise_sigma_level_m"],
            "flow": self["noise_sigma_flow_m3h"],
            "pressure": self["noise_sigma_pressure_bar"],
            "temperature": self["noise_sigma_temperature_c"],
        }[noise_class]


def _read(name: str, directory: Path | None) -> dict[str, Any]:
    path = (directory or config_dir()) / name
    try:
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    return loaded


def _v(raw: dict[str, Any], key: str) -> float | None:
    if key not in raw:
        return None
    try:
        return float(ParamValue.from_mapping(raw[key]).value)
    except ParamValueError as exc:
        raise ContractError(f"sensor spec {key}: {exc}") from exc


def load_sensor_config(directory: Path | None = None) -> SensorConfig:
    contract = _read("canonical_sensor_contract.json", directory)["sensors"]
    raw_tags = _read("sensor_specs.json", directory)["tags"]
    emitted = {t for t, c in contract.items() if c["status"] == "emit"}
    if set(raw_tags) != emitted:
        raise ContractError("sensor specs and the contract disagree on the emitted tags")
    tags: dict[str, TagSpec] = {}
    for tag, raw in raw_tags.items():
        if raw["measured_variable_ref"] != contract[tag]["measured_variable_ref"]:
            raise ContractError(f"{tag}: mapping differs from the contract")
        lag, comms = _v(raw, "lag_s"), _v(raw, "comms_delay_s")
        assert lag is not None and comms is not None
        tags[tag] = TagSpec(
            tag, raw["kind"], raw["measured_variable_ref"], lag, comms,
            raw.get("unit", "bool"), _v(raw, "range_lo"), _v(raw, "range_hi"),
            _v(raw, "interval_s"), raw.get("mode"), _v(raw, "window_s"),
        )  # fmt: skip
    params = _read("sensors.json", directory)
    try:
        records = {k: ParamValue.from_mapping(v) for k, v in params["parameters"].items()}
    except ParamValueError as exc:
        raise ContractError(f"sensors.json: {exc}") from exc
    return SensorConfig(tags, records, params["episode_start_utc"])
