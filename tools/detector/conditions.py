"""Operator-set operating conditions and fault onsets of train and validation episodes.

Read from the label file of each episode, which holds the campaign strata. Only episodes that
were loaded from train or validation are ever read, and the guard rejects any other id. The
conditions (atmosphere, temperature, flow set point, stress flag, commanded lineup) are inputs
a plant operator sets; they contain no fault effect.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
from windows import Windows


@dataclass(frozen=True)
class Condition:
    """Set conditions of one episode and its faults (subtype, asset, onset in seconds)."""

    atmosphere: str
    temperature_c: float
    setpoint_m3h: float
    stress: bool
    mode: str
    family: str
    faults: tuple[tuple[str, str, float], ...]

    @property
    def regime(self) -> tuple[str, float, float]:
        """The regime key: atmosphere, temperature and flow set point (stress implies 45 C)."""
        return (self.atmosphere, self.temperature_c, self.setpoint_m3h)

    @property
    def unit(self) -> tuple[str, str, float]:
        """The unit of the campaign split: family, atmosphere, temperature."""
        return (self.family, self.atmosphere, self.temperature_c)

    @property
    def onset_s(self) -> float | None:
        """Earliest fault onset, or None for a healthy episode."""
        return min((f[2] for f in self.faults), default=None)


def parse(doc: dict[str, Any]) -> Condition:
    """Condition from the content of a label file."""
    s = doc["strata"]
    faults = tuple((f["subtype"], f["asset_id"], float(f["onset_s"])) for f in doc["faults"])
    return Condition(
        s["atmosphere"], float(s["temperature_c"]), float(s["setpoint_m3h"]), bool(s["stress"]),
        s["mode"], s["family"], faults,
    )  # fmt: skip


def read_conditions(rel: Path, episodes: list[str]) -> dict[str, Condition]:
    """Conditions of the given episodes, one label file each."""
    out = {}
    for name in sorted(set(episodes)):
        path = rel / "evaluator" / "source_episodes" / name / "labels.json"
        out[name] = parse(json.loads(path.read_text(encoding="utf-8")))
    return out


def apply(w: Windows, conds: dict[str, Condition]) -> Windows:
    """The windows with the operator-set regime as key; the lineup key is kept for pump state."""
    c = [conds[e] for e in w.episodes]
    onset = np.asarray([x.onset_s if x.onset_s is not None else np.nan for x in c])
    return replace(w, regime=[x.regime for x in c], unit=[x.unit for x in c], onset_s=onset)
