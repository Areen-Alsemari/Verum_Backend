"""Pinned parameters of the topology residual detector, read only after a hash check.

The parameter file holds the fitted coefficients and scales, the thresholds, the persistence
rule, the units and the tag roles. Its sha256 is pinned in this module; a file that does not
match is refused before any of it is parsed. The agent imports no fitting code, only this reader.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

PARAMETERS_PATH = Path(__file__).resolve().parent / "artifacts" / "topology_residual_v1.json"
EXPECTED_PARAMETERS_SHA256 = "b3517147ffd0cfb9bf8214372952eb6eff70185b093b2eb0c0c8078ae9f89747"
METHOD_ID = "topology_residual_v1"
RESIDUAL_KEYS = ("R1", "R2", "R3", "R4")


@dataclass(frozen=True)
class QuadraticFit:
    """Fault-free quadratic of a pressure difference on a flow, with its residual scale."""

    coefficients: tuple[float, float, float]
    sigma: float


@dataclass(frozen=True)
class Parameters:
    """Everything the residuals need, as read from the pinned file."""

    sha256: str
    units: dict[str, str]
    fields: dict[str, str]
    mass_coefficients: tuple[float, float, float, float]
    mass_sigma: float
    slope_to_per_hour: float
    pump_fits: dict[tuple[str, str, str], QuadraticFit]
    receipt_line: QuadraticFit
    window_threshold: float
    residual_thresholds: dict[str, float]
    dead_zone_sigmas: float
    residual_reads: dict[str, tuple[str, ...]]
    persistence_k: int
    persistence_n: int
    persistence_threshold: float


def _quadratic(entry: dict[str, Any]) -> QuadraticFit:
    c = [float(v) for v in entry["coefficients"]]
    if len(c) != 3:
        raise ValueError("a quadratic fit holds three coefficients")
    return QuadraticFit((c[0], c[1], c[2]), float(entry["sigma"]))


def parse(doc: dict[str, Any], sha256: str) -> Parameters:
    """Build the parameters from a parsed document, checking its shape."""
    if doc["method_id"] != METHOD_ID:
        raise ValueError("the parameter file is for another method")
    mass = [float(v) for v in doc["mass_balance"]["coefficients"]]
    if len(mass) != 4:
        raise ValueError("the mass balance holds three tank areas and an intercept")
    pumps = {
        (f["residual"], f["pump"], f["state"]): _quadratic(f) for f in doc["pump_fits"]
    }  # fmt: skip
    thresholds, persistence = doc["thresholds"], doc["persistence"]
    k, n = int(persistence["k"]), int(persistence["n"])
    if not 1 <= k <= n:
        raise ValueError("the persistence rule needs 1 <= k <= n")
    return Parameters(
        sha256=sha256,
        units={t: str(v["unit"]) for t, v in doc["inputs"].items()},
        fields={t: str(v["field"]) for t, v in doc["inputs"].items()},
        mass_coefficients=(mass[0], mass[1], mass[2], mass[3]),
        mass_sigma=float(doc["mass_balance"]["sigma"]),
        slope_to_per_hour=float(doc["mass_balance"]["slope_to_per_hour"]),
        pump_fits=pumps,
        receipt_line=_quadratic(doc["receipt_line"]),
        window_threshold=float(thresholds["window_score"]),
        residual_thresholds={k: float(thresholds["residuals"][k]) for k in RESIDUAL_KEYS},
        dead_zone_sigmas=float(doc["dead_zone_sigmas"]),
        residual_reads={key: tuple(v["reads"]) for key, v in doc["residuals"].items()},
        persistence_k=k,
        persistence_n=n,
        persistence_threshold=float(persistence["threshold"]),
    )


def load_from(path: Path, expected_sha256: str) -> Parameters:
    """Read a parameter file, refuse it unless its bytes match the pinned hash, then parse it."""
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise ValueError("topology residual parameter file hash mismatch")
    doc = json.loads(raw.decode("utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("invalid topology residual parameter file")
    return parse(doc, actual)


@cache
def load_parameters() -> Parameters:
    """The pinned parameters of the shipped file, verified once per process."""
    return load_from(PARAMETERS_PATH, EXPECTED_PARAMETERS_SHA256)
