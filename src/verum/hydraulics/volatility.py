"""Volatility classes: vapor-pressure constants for the property scenarios (decision D46).

Inputs: ``config/volatility_classes.json`` and ``config/volatility_gate.json``. Outputs: for each
derived class the pair of constants (A, B in degrees Rankine) of the true vapor pressure
``P_v (psia) = exp(A - B / T_R)``, or an unresolved pair.
Key assumptions:
    * The derived classes use the AP-42 gasoline correlation with distillation slope S = 3:
      ``A = 15.64 - 1.854 S^0.5 - (0.8742 - 0.3280 S^0.5) ln(RVP)`` and
      ``B = 8742 - 1042 S^0.5 - (1049 - 179.4 S^0.5) ln(RVP)``.
    * Verification gate: the formula must reproduce the tabulated A and B within 0.1 percent
      and the tabulated true vapor pressures (Table 7.1-2 at 60 F and the worked example) within
      2 percent. If any tabulated point disagrees, both derived classes are unresolved and raise
      ``UnresolvedParameter`` when read; the formula is never adjusted.
    * The resolved class is the audited RVP 10 constants of the fluid contract.

Source: ``docs/design_decisions.md`` D46 version 3; US EPA AP-42 chapter 7.1 (Table 7.1-2 and
the worked example of Section 7.1.4).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir
from verum.params import ParamValue

SLOPE_DEFAULT = 3.0
RANKINE_60F = 519.67


def ap42_constants(rvp_psi: float, slope: float = SLOPE_DEFAULT) -> tuple[float, float]:
    """(A, B) of the AP-42 correlation for a Reid vapor pressure in psi."""
    r, ln = math.sqrt(slope), math.log(rvp_psi)
    a = 15.64 - 1.854 * r - (0.8742 - 0.3280 * r) * ln
    b = 8742.0 - 1042.0 * r - (1049.0 - 179.4 * r) * ln
    return a, b


def true_vapor_pressure_psia(a: float, b: float, temperature_rankine: float) -> float:
    return math.exp(a - b / temperature_rankine)


@dataclass(frozen=True)
class GateResult:
    passed: bool
    worst_constant_error: float
    worst_pressure_error: float
    points: int
    detail: tuple[str, ...]


def _read(name: str, directory: Path | None) -> dict[str, Any]:
    path = (directory or config_dir()) / name
    try:
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    return loaded


def run_gate(directory: Path | None = None) -> GateResult:
    """Compare the formula with every tabulated point of the gate file."""
    gate = _read("volatility_gate.json", directory)
    slope = float(gate["distillation_slope_S"])
    tol_c, tol_p = gate["tolerance_constants_relative"], gate["tolerance_pressure_relative"]
    worst_c = worst_p = 0.0
    detail, points = [], 0
    for row in gate["table_7_1_2"]:
        a, b = ap42_constants(row["rvp_psi"], slope)
        ec = max(abs(a / row["A"] - 1.0), abs(b / row["B_degR"] - 1.0))
        pv = true_vapor_pressure_psia(a, b, RANKINE_60F)
        ep = abs(pv / row["true_vapor_pressure_60F_psia"] - 1.0)
        worst_c, worst_p, points = max(worst_c, ec), max(worst_p, ep), points + 1
        detail.append(f"RVP {row['rvp_psi']:g}: constants {ec:.2e}, P_v(60 F) {ep:.3%}")
    for row in gate["worked_example_528_37_degR"]:
        a, b = ap42_constants(row["rvp_psi"], slope)
        ec = max(abs(a / row["A"] - 1.0), abs(b / row["B_degR"] - 1.0))
        ep = abs(true_vapor_pressure_psia(a, b, 528.37) / row["vapor_pressure_psia"] - 1.0)
        worst_c, worst_p, points = max(worst_c, ec), max(worst_p, ep), points + 1
        detail.append(f"example RVP {row['rvp_psi']:g}: constants {ec:.2e}, P_v {ep:.3%}")
    return GateResult(
        worst_c <= tol_c and worst_p <= tol_p, worst_c, worst_p, points, tuple(detail)
    )


def derived_constants(directory: Path | None = None) -> dict[str, tuple[ParamValue, ParamValue]]:
    """Constants of the derived classes; unresolved pairs if the gate fails."""
    classes = _read("volatility_classes.json", directory)["classes"]
    passed = run_gate(directory).passed
    out: dict[str, tuple[ParamValue, ParamValue]] = {}
    for name, record in classes.items():
        if record["kind"] != "derived":
            continue
        if not passed:
            reason = "the AP-42 verification gate of decision D46 failed"
            out[name] = (ParamValue.unresolved("1", reason), ParamValue.unresolved("degR", reason))
            continue
        a, b = ap42_constants(float(record["rvp_psi"]["value"]), SLOPE_DEFAULT)
        prov = "VERUM-DD-D46-v3"
        out[name] = (
            ParamValue.selected(a, "1", "SIM", prov),
            ParamValue.selected(b, "degR", "SIM", prov),
        )
    return out
