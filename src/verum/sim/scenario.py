"""Scenario files: initial state, schedule and episode options.

The initial valve and pump state is the named lineup mode with every open valve fully open and every
pump of the mode running. The schedule is passed unchanged to the operations controller, and this
module only checks its shape. The only random draws are the downstream demand process and, in
profile v2, the regime and receipt set-point streams. The variability profile is off, v1 or v2, the
volatility class is RVP_9_0, RVP_9_5 or RVP10, and the atmosphere stratum is coastal or inland.
Receipt set-points are chosen from 0, 300, 400, 500 and 600 m3/h.

See D6, D23, D24, D46 and D73.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir
from verum.sim.variability import resolve_profile

REQUIRED = (
    "scenario_id",
    "description",
    "seed",
    "duration_s",
    "temperature_c",
    "fitting_profile",
    "healthy_envelope",
    "atmosphere_stratum",
    "volatility_class",
    "demand_process",
    "initial",
    "schedule",
)
STRATA = ("coastal", "inland")
VOLATILITY_CLASSES = ("RVP_9_0", "RVP_9_5", "RVP10")
RECEIPT_SETPOINTS_M3H = (0.0, 300.0, 400.0, 500.0, 600.0)


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    description: str
    seed: int
    duration_s: float
    temperature_c: float
    fitting_profile: str
    healthy_envelope: bool
    atmosphere_stratum: str
    volatility_class: str
    demand_process: bool
    initial_mode: str
    tank_levels_m: dict[str, float]
    receipt_flow_m3h: float
    receipt_setpoint_m3h: float
    schedule: list[dict[str, Any]]
    variability_profile: str = "off"


def _check_setpoint(value: float) -> None:
    if value not in RECEIPT_SETPOINTS_M3H:
        raise ContractError(
            f"scenario: receipt set-point {value:g} m3/h is not one of {RECEIPT_SETPOINTS_M3H}"
        )


def parse_scenario(raw: dict[str, Any]) -> Scenario:
    missing = [k for k in REQUIRED if k not in raw]
    if missing:
        raise ContractError(f"scenario: missing fields {missing}")
    initial = raw["initial"]
    for key in ("mode", "tank_levels_m", "receipt_flow_m3h", "receipt_setpoint_m3h"):
        if key not in initial:
            raise ContractError(f"scenario {raw['scenario_id']}: initial.{key} is required")
    if raw["duration_s"] <= 0:
        raise ContractError("scenario: duration must be positive")
    if raw["volatility_class"] not in VOLATILITY_CLASSES:
        raise ContractError(f"scenario: volatility_class must be one of {VOLATILITY_CLASSES}")
    if raw["atmosphere_stratum"] not in STRATA:
        raise ContractError(f"scenario: atmosphere_stratum must be one of {STRATA}")
    for entry in raw["schedule"]:
        if ("t_s" in entry) == ("on" in entry):
            raise ContractError("scenario: a schedule entry has either t_s or on")
        if entry.get("command") == "receipt_setpoint":
            _check_setpoint(float(entry["value_m3h"]))
    _check_setpoint(float(initial["receipt_setpoint_m3h"]))
    return Scenario(
        scenario_id=raw["scenario_id"],
        description=raw["description"],
        seed=int(raw["seed"]),
        duration_s=float(raw["duration_s"]),
        temperature_c=float(raw["temperature_c"]),
        fitting_profile=raw["fitting_profile"],
        healthy_envelope=bool(raw["healthy_envelope"]),
        atmosphere_stratum=raw["atmosphere_stratum"],
        volatility_class=raw["volatility_class"],
        demand_process=bool(raw["demand_process"]),
        initial_mode=initial["mode"],
        tank_levels_m={k: float(v) for k, v in initial["tank_levels_m"].items()},
        receipt_flow_m3h=float(initial["receipt_flow_m3h"]),
        receipt_setpoint_m3h=float(initial["receipt_setpoint_m3h"]),
        schedule=list(raw["schedule"]),
        variability_profile=resolve_profile(
            raw.get("variability_profile"), bool(raw["demand_process"])
        ),
    )


def load_scenario(scenario_id: str, directory: Path | None = None) -> Scenario:
    path = (directory or config_dir()) / "scenarios" / f"{scenario_id}.json"
    try:
        return parse_scenario(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
