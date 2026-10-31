"""Severity classes of a fault subtype and asset class, read from the class file.

The class file gives, for each subtype and asset class, the severity from which the marginal and the
clear class begin. This module turns those boundaries into intervals of the fault range and says
which classes exist. An unresolved boundary removes the classes above it, and a boundary at the
start of the range leaves no room for the class below it.

See D78, D84, D89 and D89c.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from verum.contracts.paths import config_dir
from verum.params import ParamValue

CLASS_FILE = "severity_classes.json"
# Severity range of each subtype, from the least severe end to the most severe, in the units of the
# audit grid: leak area (m2), closure fraction, head loss fraction, fraction of span (per hour for a
# drift), and the stuck opening, which grows in severity as it falls.
RANGES: dict[str, tuple[float, float]] = {
    "leak": (2.0e-6, 1.0e-3),
    "restriction_position_visible": (0.10, 0.85),
    "restriction_obstruction": (0.10, 0.85),
    "pump": (0.02, 0.30),
    "bias": (0.002, 0.05),
    "drift": (0.002, 0.05),
    "misroute_b": (0.02, 0.005),
}
NO_SEVERITY = ("stuck", "misroute_a")
NONE_CLASS = "none"


@dataclass(frozen=True)
class ClassInterval:
    name: str
    start: float
    end: float

    def draw(self, u: float) -> float:
        """Log-uniform severity inside the interval for a uniform number ``u`` in [0, 1)."""
        a, b = math.log(self.start), math.log(self.end)
        return math.exp(a + u * (b - a))


def asset_class(subtype: str, asset: str) -> str:
    """Asset class of the class file for an asset of a subtype."""
    if subtype == "leak":
        for prefix, name in (("E-S", "suction"), ("E-P", "pump_branch"), ("E-D", "discharge")):
            if asset.startswith(prefix):
                return name
        return "receipt"
    if subtype == "pump":
        return "pump"
    if subtype in ("bias", "drift", "stuck"):
        return {"FT": "flow", "PT": "pressure", "LT": "level"}[asset[:2]]
    if asset.startswith("XV-P"):
        return "pump_branch"
    return "tank_outlet" if asset.startswith("XV-S") else "tank_inlet"


def _grows(subtype: str, x: float) -> float:
    """Severity coordinate that rises with severity (the stuck opening falls)."""
    return -x if subtype == "misroute_b" else x


class ClassTable:
    def __init__(self, directory: Path | None = None) -> None:
        raw = json.loads(((directory or config_dir()) / CLASS_FILE).read_text(encoding="utf-8"))
        self.params = {k: ParamValue.from_mapping(v) for k, v in raw["parameters"].items()}
        self.marks: dict[str, dict[str, float | bool]] = raw["boundary_marks"]

    def _boundary(self, key: str) -> float | None:
        record = self.params[key]
        return None if record.status == "unresolved" else float(record.value)

    def intervals(self, subtype: str, aclass: str) -> list[ClassInterval]:
        """The classes that exist for a subtype and asset class, least severe first."""
        if subtype in NO_SEVERITY:
            return [ClassInterval(NONE_CLASS, 0.0, 0.0)]
        lo, hi = RANGES[subtype]
        marginal = self._boundary(f"{subtype}/{aclass}/marginal_from")
        clear = self._boundary(f"{subtype}/{aclass}/clear_from")
        if marginal is None:
            return [ClassInterval("invisible", lo, hi)]
        edges = [("invisible", lo, marginal), ("marginal", marginal, clear if clear else hi)]
        if clear is not None:
            edges.append(("clear", clear, hi))
        return [
            ClassInterval(name, a, b)
            for name, a, b in edges
            if _grows(subtype, b) - _grows(subtype, a) > 1e-12 * abs(a)
            or (name == "clear" and math.isclose(a, b) and math.isclose(b, hi))
        ]

    def gaps(self, subtype: str, aclass: str) -> list[str]:
        """The classes that the unresolved boundaries remove for a subtype and asset class."""
        if subtype in NO_SEVERITY:
            return []
        marginal = self._boundary(f"{subtype}/{aclass}/marginal_from")
        clear = self._boundary(f"{subtype}/{aclass}/clear_from")
        if marginal is None:
            return ["marginal", "clear"]
        return [] if clear is not None else ["clear"]
