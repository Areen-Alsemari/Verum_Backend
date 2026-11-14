"""Small synthetic cases for the Anomaly Detection tests: parameters, windows and requests.

The parameters are round numbers chosen so that every residual of a healthy window is exactly
zero and every expected value can be worked out by hand. They are not the fitted parameters.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from verum.agents.anomaly_detection.parameters import Parameters, load_from
from verum.contracts.agent_interfaces import content_hash, contract_directory

TANK_AREA = 700.0
FLOW = 400.0
TAGS = {
    "FT-001": ("m3/h", "mean"), "FT-201": ("m3/h", "mean"),
    "LT-101": ("m", "slope_per_s"), "LT-102": ("m", "slope_per_s"),
    "LT-103": ("m", "slope_per_s"), "PT-001": ("barg", "mean"), "PT-201": ("barg", "mean"),
    "PT-202A": ("barg", "mean"), "PT-202B": ("barg", "mean"), "PT-203": ("barg", "mean"),
    "P-101A": ("bool", "latest_value"), "P-101B": ("bool", "latest_value"),
}  # fmt: skip


def parameter_document() -> dict[str, Any]:
    """A complete parameter document with round numbers."""

    def fit(residual: str, pump: str, state: str, c0: float, c1: float, sigma: float) -> Any:
        return {"residual": residual, "pump": pump, "state": state,
                "coefficients": [c0, c1, 0.0], "sigma": sigma}  # fmt: skip

    fits = []
    for pump in ("A", "B"):
        fits.append(fit("R2", pump, "*", 5.0, 0.01, 0.1))
        fits.append(fit("R3", pump, "*", 1.0, 0.002, 0.05))
    fits.append(fit("R2", "A", "A", 5.5, 0.01, 0.1))
    return {
        "method_id": "topology_residual_v1",
        "inputs": {t: {"unit": u, "field": f, "role": "test"} for t, (u, f) in TAGS.items()},
        "mass_balance": {"coefficients": [TANK_AREA] * 3 + [0.0], "sigma": 2.0,
                         "slope_to_per_hour": 3600.0},  # fmt: skip
        "pump_fits": fits,
        "receipt_line": {"coefficients": [1.0, 0.002, 0.0], "sigma": 0.02},
        "dead_zone_sigmas": 1.0,
        "persistence": {"k": 2, "n": 3, "threshold": 1.5},
        "thresholds": {
            "window_score": 3.0,
            "residuals": {"R1": 1.0, "R2": 1.0, "R3": 1.0, "R4": 1.0},
        },
        "residuals": {
            "R1": {"reads": ["FT-001", "FT-201", "LT-101", "LT-102", "LT-103"]},
            "R2": {"reads": ["FT-201", "PT-201", "PT-202A", "PT-202B"]},
            "R3": {"reads": ["FT-201", "PT-202A", "PT-202B", "PT-203"]},
            "R4": {"reads": ["FT-001", "PT-001"]},
        },
    }  # fmt: skip


def write_parameters(directory: Path, doc: dict[str, Any] | None = None) -> tuple[Path, str]:
    """Write a parameter document and return its path and sha256."""
    path = directory / "parameters.json"
    raw = json.dumps(doc or parameter_document(), indent=1, sort_keys=True).encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def parameters(directory: Path) -> Parameters:
    """The synthetic parameters, loaded through the same hash-checked reader as the real ones."""
    path, digest = write_parameters(directory)
    return load_from(path, digest)


def healthy(pump: str = "A") -> dict[str, float]:
    """Values of the twelve inputs for which every residual is exactly zero."""
    rise = 5.5 + 0.01 * FLOW if pump == "A" else 5.0 + 0.01 * FLOW
    discharge = 2.0 + rise
    values = {
        "FT-001": FLOW, "FT-201": FLOW, "LT-101": 0.0, "LT-102": 0.0, "LT-103": 0.0,
        "PT-001": 1.0 + 0.002 * FLOW, "PT-201": 2.0, "PT-202A": 2.0, "PT-202B": 2.0,
        "PT-203": discharge - (1.0 + 0.002 * FLOW), "P-101A": 0.0, "P-101B": 0.0,
    }  # fmt: skip
    values[f"PT-202{pump}"] = discharge
    values[f"P-101{pump}"] = 1.0
    return values


def signals_for(values: Mapping[str, float | None]) -> list[dict[str, Any]]:
    """Signal summaries holding only the fields the detector reads; None means no value."""
    out = []
    for tag, (unit, field) in TAGS.items():
        out.append({"tag_id": tag, "unit": unit, field: values.get(tag)})
    return out


def example_request() -> dict[str, Any]:
    """The official anomaly detection request example."""
    path = contract_directory() / "examples" / "anomaly_detection.request.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def clean_signal(signal: dict[str, Any]) -> None:
    """Make a summary look like a fully measured, good-quality window."""
    signal.update(
        missing_samples=0, bad_quality_samples=0, latest_quality="good",
        latest_availability="measured", rows_received=signal["measured_count"],
    )  # fmt: skip
    for name in ("latest_value", "mean", "minimum", "maximum"):
        if signal["unit"] != "bool" and not isinstance(signal.get(name), (int, float)):
            signal[name] = 1.0
    if signal["unit"] == "bool" and signal.get("latest_value") is None:
        signal["latest_value"] = 0.0


def set_missing(signal: dict[str, Any], count: int) -> None:
    """Declare count missing samples, keeping the summary counts consistent."""
    signal["missing_samples"] = count
    signal["rows_received"] = signal["measured_count"] + count


def request_with(values: Mapping[str, float | None]) -> dict[str, Any]:
    """The example request with the twelve inputs set and every signal clean and measured."""
    request = copy.deepcopy(example_request())
    summary = request["input"]["observations"]["summary"]
    for signal in summary["signals"]:
        clean_signal(signal)
        if signal["tag_id"] in TAGS:
            field = TAGS[signal["tag_id"]][1]
            signal[field] = values.get(signal["tag_id"])
    rehash(request)
    return request


def rehash(request: dict[str, Any]) -> None:
    """Re-hash the observation summary after a test changed it."""
    observations = request["input"]["observations"]
    digest = content_hash(observations["summary"])
    for evidence in request["evidence"]:
        if (
            evidence["kind"] == "observation_representation"
            and evidence["evidence_id"] in observations["evidence_ids"]
        ):
            evidence["content_sha256"] = digest
            return
    raise AssertionError("observation representation evidence not found")
