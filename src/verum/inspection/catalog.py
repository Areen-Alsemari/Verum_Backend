"""The inspection catalog: actions, workflow constants, model parameters and thresholds.

The catalog is read from the configuration file as parameter records. A value that the source
document does not state is an unresolved parameter, and reading it raises. The agent-visible view
holds the name, target kind, preconditions, cost, duration and output fields with their expanded
uncertainty, and nothing of the models or the thresholds.

See D100 to D105.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from verum.contracts.paths import config_dir
from verum.params import ParamValue, UnresolvedParameter

FILE = "inspection_catalog.json"
ACTION_IDS = tuple(f"ACT-INSP-{i:02d}" for i in range(1, 8))
UNQUALIFIED_ACTIONS = frozenset({"ACT-INSP-01", "ACT-INSP-03", "ACT-INSP-04", "ACT-INSP-06"})
PRESSURE_TRANSMITTERS = ("PT-001", "PT-201", "PT-202A", "PT-202B", "PT-203")


@dataclass(frozen=True)
class Output:
    name: str
    unit: str
    modelled: bool
    kind: str
    uncertainty: ParamValue


@dataclass(frozen=True)
class Action:
    action_id: str
    name: str
    target_kind: str
    targets: str
    preconditions: tuple[str, ...]
    cost_usd: float
    duration_min: float
    outputs: tuple[Output, ...]

    @property
    def duration_s(self) -> float:
        return self.duration_min * 60.0

    def output(self, name: str) -> Output:
        return next(o for o in self.outputs if o.name == name)

    def u(self, name: str) -> float:
        """Expanded uncertainty (k = 2) of an output; raises if the document gives none."""
        return self.output(name).uncertainty.value


class Catalog:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.version: str = raw["schema_version"]
        self.actions: dict[str, Action] = {k: _action(k, v) for k, v in raw["actions"].items()}
        self._sections = {
            name: {k: ParamValue.from_mapping(v) for k, v in raw[name].items()}
            for name in ("workflow", "preconditions", "models", "thresholds", "history")
        }
        if tuple(self.actions) != ACTION_IDS:
            raise ValueError("the catalog must hold ACT-INSP-01 to ACT-INSP-07 in order")

    def param(self, section: str, name: str) -> float:
        """A number of the workflow, preconditions, models, thresholds or history sections."""
        return self._sections[section][name].value

    def action(self, action_id: str) -> Action:
        return self.actions[action_id]

    def agent_view(self, *, allow_legacy_simulation: bool = False) -> list[dict[str, Any]]:
        """What the gateway returns: no model, threshold or workflow constant."""
        view = [_view(a) for a in self.actions.values()]
        if not allow_legacy_simulation:
            for item in view:
                if item["action_id"] in UNQUALIFIED_ACTIONS:
                    for output in item["outputs"]:
                        output["modelled"] = False
                        output["uncertainty_k2"] = None
        return view


def _action(action_id: str, raw: dict[str, Any]) -> Action:
    outputs = tuple(
        Output(
            o["name"],
            o["unit"],
            o["modelled"],
            o["kind"],
            ParamValue.from_mapping(o["uncertainty"]),
        )
        for o in raw["outputs"]
    )
    return Action(
        action_id, raw["name"], raw["target_kind"], raw["targets"], tuple(raw["preconditions"]),
        ParamValue.from_mapping(raw["cost_usd"]).value,
        ParamValue.from_mapping(raw["duration_min"]).value, outputs,
    )  # fmt: skip


def _view(a: Action) -> dict[str, Any]:
    def u(o: Output) -> float | None:
        try:
            return o.uncertainty.value
        except UnresolvedParameter:
            return None

    return {
        "action_id": a.action_id, "name": a.name, "target_kind": a.target_kind,
        "targets": a.targets, "preconditions": list(a.preconditions),
        "cost_usd": a.cost_usd, "duration_min": a.duration_min,
        "outputs": [
            {"name": o.name, "unit": o.unit, "modelled": o.modelled, "uncertainty_k2": u(o)}
            for o in a.outputs
        ],
    }  # fmt: skip


@lru_cache(maxsize=4)
def _load(directory: Path) -> Catalog:
    import json

    return Catalog(json.loads((directory / FILE).read_text(encoding="utf-8")))


def load_catalog(directory: Path | None = None) -> Catalog:
    """The catalog of the configuration directory."""
    return _load(directory or config_dir())
