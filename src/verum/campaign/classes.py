"""Severity classes of a fault subtype and asset class, read from the class file.

The class file gives, for each subtype and asset class, the severity from which the marginal and the
clear class begin. This module turns those boundaries into intervals of the fault range and says
which classes exist. An unresolved boundary removes the classes above it, and a boundary at the
start of the range leaves no room for the class below it. A stuck-at or a misrouting (a) has no
severity coordinate, so its class comes from the audit cell of its lineup and asset, or is
unaudited.

See D78, D84, D89, D89c and D154.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from verum.contracts.paths import config_dir
from verum.params import ParamValue

CLASS_FILE = "severity_classes.json"
AUDIT_FILE = "audit_cells.json"
UNAUDITED = "unaudited"
AUDIT_CELL = "audit"  # the cell class of a subtype whose class is read from the audit cells
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
ASSET_CLASSES: dict[str, tuple[str, ...]] = {
    "leak": ("suction", "pump_branch", "discharge", "receipt"),
    "restriction_position_visible": ("pump_branch", "tank_outlet", "tank_inlet"),
    "restriction_obstruction": ("pump_branch", "tank_outlet", "tank_inlet"),
    "pump": ("pump",),
    "bias": ("flow", "pressure", "level"),
    "drift": ("flow", "pressure", "level"),
    "misroute_b": ("tank_inlet",),
}


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

    def names(self, subtype: str) -> list[str]:
        """Class names that exist for some asset class of a subtype, least severe first."""
        if subtype in NO_SEVERITY:
            return [AUDIT_CELL]
        found = {iv.name for a in ASSET_CLASSES[subtype] for iv in self.intervals(subtype, a)}
        return sorted(found, key=("invisible", "marginal", "clear").index)

    def has_class(self, subtype: str, asset: str, name: str) -> bool:
        """Whether the asset class of an asset has a class interval of this name."""
        if subtype in NO_SEVERITY:
            return True
        return any(iv.name == name for iv in self.intervals(subtype, asset_class(subtype, asset)))


class AuditCells:
    """Audit class of each stuck-at and misrouting (a) cell, keyed by subtype, lineup and asset."""

    def __init__(self, directory: Path | None = None) -> None:
        raw = json.loads(((directory or config_dir()) / AUDIT_FILE).read_text(encoding="utf-8"))
        self.cells: dict[str, str] = {k: v["class"] for k, v in raw["cells"].items()}

    def class_of(self, subtype: str, mode: str, asset: str) -> str:
        """The class of the audit cell; unaudited if there is no cell or the audit rejected it."""
        return self.cells.get(f"{subtype}/{mode}/{asset}", UNAUDITED)
