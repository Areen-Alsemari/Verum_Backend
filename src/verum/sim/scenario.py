"""Scenario files: initial state, schedule and episode options.

Inputs: ``config/scenarios/<id>.json``. Outputs: a validated ``Scenario``.
Key assumptions:
    * The initial valve and pump state is the named lineup mode with every open valve
      fully open and every pump of the mode running (decision D6: an episode starts
      with a pump running).
    * ``healthy_envelope`` turns on gate SG3 (levels 1.8 to 12 m, protection NORMAL).
    * The schedule is passed unchanged to the operations controller; this module
      only checks its shape.
    * The seed is recorded in the episode; no random draw is made in healthy episodes.

Source: ``revised/01_facility_tanks_topology.md`` section 6.2;
``docs/design_decisions.md`` D6, D11, D21.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir

REQUIRED = (
    "scenario_id",
    "description",
    "seed",
    "duration_s",
    "temperature_c",
    "fitting_profile",
    "healthy_envelope",
    "initial",
    "schedule",
)


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    description: str
    seed: int
    duration_s: float
    temperature_c: float
    fitting_profile: str
    healthy_envelope: bool
    initial_mode: str
    tank_levels_m: dict[str, float]
    receipt_flow_m3h: float
    receipt_setpoint_m3h: float
    schedule: list[dict[str, Any]]


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
    for entry in raw["schedule"]:
        if ("t_s" in entry) == ("on" in entry):
            raise ContractError("scenario: a schedule entry has either t_s or on")
    return Scenario(
        scenario_id=raw["scenario_id"],
        description=raw["description"],
        seed=int(raw["seed"]),
        duration_s=float(raw["duration_s"]),
        temperature_c=float(raw["temperature_c"]),
        fitting_profile=raw["fitting_profile"],
        healthy_envelope=bool(raw["healthy_envelope"]),
        initial_mode=initial["mode"],
        tank_levels_m={k: float(v) for k, v in initial["tank_levels_m"].items()},
        receipt_flow_m3h=float(initial["receipt_flow_m3h"]),
        receipt_setpoint_m3h=float(initial["receipt_setpoint_m3h"]),
        schedule=list(raw["schedule"]),
    )


def load_scenario(scenario_id: str, directory: Path | None = None) -> Scenario:
    path = (directory or config_dir()) / "scenarios" / f"{scenario_id}.json"
    try:
        return parse_scenario(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
