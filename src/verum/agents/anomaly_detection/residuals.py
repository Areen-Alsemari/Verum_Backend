"""The four topology residuals, computed from one window summary and the pinned parameters.

R1 is the mismatch between the receipt flow, the delivery flow and the change of tank inventory
from the three level slopes. R2 and R3 compare the pressure rise across the running pump and the
pressure drop to the discharge header with their fault-free values at the delivery flow. R4
compares the receipt line pressure with its fault-free value at the receipt flow. A residual whose
input is missing or unusable is unknown, never zero; one that does not apply is not computed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from verum.agents.anomaly_detection.parameters import Parameters, QuadraticFit
from verum.agents.anomaly_detection.quality import is_number, tag_of

NAMES = {
    "R1": "mass_balance",
    "R2": "pump_head",
    "R3": "discharge_loss",
    "R4": "receipt_line",
}
TANK_LEVELS = ("LT-101", "LT-102", "LT-103")
PUMPS = {"A": "P-101A", "B": "P-101B"}
COMPUTED, UNKNOWN, NOT_APPLICABLE = "computed", "unknown", "not_applicable"
_STATES = {(True, False): "A", (False, True): "B", (True, True): "AB", (False, False): "none"}


@dataclass(frozen=True)
class Reading:
    """One input of the detector: its value, or the reason it cannot be used."""

    value: float | None
    reason: str | None = None


@dataclass(frozen=True)
class ResidualResult:
    """One residual for one window: computed, unknown (with reasons) or not applicable."""

    key: str
    state: str
    reads: tuple[str, ...]
    value: float | None
    z: float | None
    reasons: tuple[str, ...]


def _read_run_state(raw: Any) -> Reading:
    if isinstance(raw, bool):
        return Reading(1.0 if raw else 0.0)
    if is_number(raw) and raw in (0, 1):
        return Reading(float(raw))
    return Reading(None, "no usable run state")


def _read_one(signal: dict[str, Any] | None, tag: str, params: Parameters) -> Reading:
    if signal is None:
        return Reading(None, "tag not in the request")
    unit, expected, field = signal.get("unit"), params.units[tag], params.fields[tag]
    if unit != expected:
        return Reading(None, f"unit {unit!r} where {expected!r} is expected")
    raw = signal.get(field)
    if expected == "bool":
        return _read_run_state(raw)
    if not isinstance(raw, (int, float)) or not is_number(raw):
        return Reading(None, f"no usable {field}")
    return Reading(float(raw))


def read_window(signals: list[dict[str, Any]], params: Parameters) -> dict[str, Reading]:
    """The twelve inputs of the detector from the signal summaries of one window."""
    by_tag: dict[str, dict[str, Any]] = {}
    for signal in signals:
        by_tag.setdefault(tag_of(signal), signal)
    return {tag: _read_one(by_tag.get(tag), tag, params) for tag in sorted(params.fields)}


def _need(
    readings: dict[str, Reading], tags: tuple[str, ...]
) -> tuple[dict[str, float], list[str]]:
    values: dict[str, float] = {}
    reasons: list[str] = []
    for tag in tags:
        reading = readings[tag]
        if reading.value is None:
            reasons.append(f"{tag}: {reading.reason}")
        else:
            values[tag] = reading.value
    return values, reasons


def pump_state(readings: dict[str, Reading]) -> tuple[str | None, list[str]]:
    """'A', 'B', 'AB' or 'none' from the two run states; None with reasons if either is unknown."""
    values, reasons = _need(readings, tuple(PUMPS.values()))
    if reasons:
        return None, reasons
    return _STATES[(values["P-101A"] == 1.0, values["P-101B"] == 1.0)], []


def quadratic(fit: QuadraticFit, q: float) -> float:
    """Value of a fault-free quadratic at a flow."""
    c = fit.coefficients
    return c[0] + c[1] * q + c[2] * q * q


def beyond_dead_zone(residual: float, sigma: float, dead_zone_sigmas: float) -> float:
    """The residual beyond the dead zone, in scale units (zero inside it)."""
    return max(0.0, abs(residual) - dead_zone_sigmas * sigma) / sigma


def _result(
    key: str, reads: tuple[str, ...], value: float, sigma: float, p: Parameters
) -> ResidualResult:
    z = beyond_dead_zone(value, sigma, p.dead_zone_sigmas)
    return ResidualResult(key, COMPUTED, reads, value, z, ())


def _unknown(key: str, reads: tuple[str, ...], reasons: list[str]) -> ResidualResult:
    return ResidualResult(key, UNKNOWN, reads, None, None, tuple(reasons))


def mass_balance(readings: dict[str, Reading], params: Parameters) -> ResidualResult:
    """R1: receipt flow minus delivery flow minus the storage term, against its fault-free value."""
    reads = ("FT-001", "FT-201", *TANK_LEVELS)
    values, reasons = _need(readings, reads)
    if reasons:
        return _unknown("R1", reads, reasons)
    a1, a2, a3, intercept = params.mass_coefficients
    storage = sum(
        area * values[tag] * params.slope_to_per_hour
        for area, tag in zip((a1, a2, a3), TANK_LEVELS, strict=True)
    )
    residual = values["FT-001"] - values["FT-201"] - storage - intercept
    return _result("R1", reads, residual, params.mass_sigma, params)


def pump_residual(
    key: str, state: str | None, why: list[str], readings: dict[str, Reading], p: Parameters
) -> ResidualResult:
    """R2 (suction side) or R3 (discharge header side) for the running pump."""
    if state is None:
        return _unknown(key, tuple(PUMPS.values()), why)
    if state == "none":
        return ResidualResult(key, NOT_APPLICABLE, (), None, None, ("no pump is running",))
    if state == "AB":
        reason = "both pumps are running, which was not seen when the parameters were fitted"
        return _unknown(key, tuple(PUMPS.values()), [reason])
    other = "PT-201" if key == "R2" else "PT-203"
    reads = ("FT-201", f"PT-202{state}", other, PUMPS[state])
    values, reasons = _need(readings, reads[:3])
    if reasons:
        return _unknown(key, reads, reasons)
    fit = p.pump_fits.get((key, state, state)) or p.pump_fits[(key, state, "*")]
    residual = values[f"PT-202{state}"] - values[other] - quadratic(fit, values["FT-201"])
    return _result(key, reads, residual, fit.sigma, p)


def receipt_line(readings: dict[str, Reading], params: Parameters) -> ResidualResult:
    """R4: receipt line pressure against its fault-free value at the receipt flow."""
    reads = ("FT-001", "PT-001")
    values, reasons = _need(readings, reads)
    if reasons:
        return _unknown("R4", reads, reasons)
    fit = params.receipt_line
    residual = values["PT-001"] - quadratic(fit, values["FT-001"])
    return _result("R4", reads, residual, fit.sigma, params)


def compute_residuals(signals: list[dict[str, Any]], params: Parameters) -> list[ResidualResult]:
    """R1 to R4 for one window, in that order."""
    readings = read_window(signals, params)
    state, why = pump_state(readings)
    return [
        mass_balance(readings, params),
        pump_residual("R2", state, why, readings, params),
        pump_residual("R3", state, why, readings, params),
        receipt_line(readings, params),
    ]


def window_score(results: list[ResidualResult]) -> float | None:
    """The largest computed residual in scale units; None if none could be computed."""
    zs = [r.z for r in results if r.state == COMPUTED and r.z is not None]
    return max(zs) if zs else None
