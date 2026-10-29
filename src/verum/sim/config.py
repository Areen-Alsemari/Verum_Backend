"""Engine configuration as parameter records.

Inputs: ``config/sim.json``. Outputs: ``SimConfig`` (scalar access to the records).
Key assumptions: every number is a ``ParamValue``; reading an unresolved one raises
``UnresolvedParameter``. Stroke times follow decision D4: 10 s for ``XV-R000`` and
30 s for the other motorized valves.

Source: ``docs/design_decisions.md`` D3, D4, D17, D18, D19.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir
from verum.params import ParamValue, ParamValueError

FILENAME = "sim.json"


@dataclass(frozen=True)
class SimConfig:
    parameters: dict[str, ParamValue]

    def __getitem__(self, name: str) -> float:
        try:
            return self.parameters[name].value
        except KeyError:
            raise ContractError(f"sim config: no parameter {name!r}") from None

    def stroke_time_s(self, valve: str) -> float:
        if valve == "XV-R000":
            return self["stroke_time_xv_r000_s"]
        return self["stroke_time_other_motorized_s"]


def load_sim_config(directory: Path | None = None) -> SimConfig:
    path = (directory or config_dir()) / FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))["parameters"]
        return SimConfig({k: ParamValue.from_mapping(v) for k, v in raw.items()})
    except (OSError, json.JSONDecodeError, KeyError, ParamValueError) as exc:
        raise ContractError(f"cannot read {path}: {exc!r}") from exc
