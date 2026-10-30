"""Engine configuration as parameter records.

Every number is a parameter record, and reading an unresolved one raises. Valve stroke times are 10
s for the common receipt valve and 30 s for the other motorized valves.

See D4.
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
