"""Causal observation summaries for coursework data handoffs.

Only records available at the cutoff enter an input; measurement values remain in source units.
Absolute episode time and identifiers stay in evaluator lineage rather than model features.
Missing samples and previous measurements remain distinct instead of being filled with zero.
"""

from __future__ import annotations

import bisect
import math
from collections import defaultdict
from typing import Any

import numpy as np


def check_observation(row: dict[str, Any], units: dict[str, str], duration_s: float) -> None:
    """Check numeric, unit and timing invariants in an already schema-verified source file."""
    tag = row["tag_id"]
    if tag not in units or row["unit"] != units[tag]:
        raise ValueError(f"unknown tag or inconsistent unit: {tag}")
    for key in ("t_sim_s", "t_available_s"):
        if isinstance(row[key], bool) or not math.isfinite(row[key]):
            raise ValueError("observation times must be finite numbers")
    if not 0 <= row["t_sim_s"] <= duration_s or row["t_available_s"] < row["t_sim_s"]:
        raise ValueError("observation violates measurement/availability ordering")
    value = row["value"]
    if value is not None and (isinstance(value, bool) or not math.isfinite(value)):
        raise ValueError("measurement must be finite or missing")


class ObservationWindows:
    def __init__(self, rows: list[dict[str, Any]], units: dict[str, str]) -> None:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[row["tag_id"]].append(row)
        self.units = units
        self.rows = {
            tag: sorted(grouped[tag], key=lambda r: (r["t_available_s"], r["t_sim_s"]))
            for tag in units
        }
        self.times = {tag: [r["t_available_s"] for r in items] for tag, items in self.rows.items()}

    def summary(self, cutoff_s: float, lookback_s: float) -> dict[str, Any]:
        """Summarise the closed-right availability window, with times relative to its cutoff."""
        if not math.isfinite(cutoff_s) or not math.isfinite(lookback_s) or lookback_s <= 0:
            raise ValueError("finite cutoff and positive lookback are required")
        signals = []
        for tag, unit in sorted(self.units.items()):
            rows, times = self.rows[tag], self.times[tag]
            lo = bisect.bisect_right(times, cutoff_s - lookback_s)
            hi = bisect.bisect_right(times, cutoff_s)
            window = rows[lo:hi]
            latest = rows[hi - 1] if hi else None
            measured = [r for r in window if r["value"] is not None]
            good = next((r for r in reversed(rows[:hi]) if r["value"] is not None), None)
            numeric = _statistics(measured) if unit != "bool" else _statistics([])
            numeric["measured_count"] = len(measured)
            signals.append(
                {
                    "tag_id": tag,
                    "unit": unit,
                    "rows_received": len(window),
                    "missing_samples": sum(r["value"] is None for r in window),
                    "bad_quality_samples": sum(r["quality_flag"] != "good" for r in window),
                    "latest_value": None if latest is None else latest["value"],
                    "latest_quality": None if latest is None else latest["quality_flag"],
                    "latest_availability": None
                    if latest is None
                    else latest["availability_status"],
                    "latest_received_age_s": None
                    if latest is None
                    else min(lookback_s, cutoff_s - latest["t_available_s"]),
                    "latest_received_age_is_lower_bound": None
                    if latest is None
                    else cutoff_s - latest["t_available_s"] >= lookback_s,
                    "previous_measured_value": None if good is None else good["value"],
                    "previous_measured_quality": None if good is None else good["quality_flag"],
                    "previous_measured_age_s": None
                    if good is None
                    else min(lookback_s, cutoff_s - good["t_available_s"]),
                    "previous_measured_age_is_lower_bound": None
                    if good is None
                    else cutoff_s - good["t_available_s"] >= lookback_s,
                    **numeric,
                }
            )
        return {
            "clock_basis": "relative_to_current_cutoff",
            "current_time_s": 0.0,
            "lookback_s": lookback_s,
            "signals": signals,
        }


def _statistics(rows: list[dict[str, Any]]) -> dict[str, float | int | None]:
    out: dict[str, float | int | None] = {
        "measured_count": len(rows),
        "mean": None,
        "minimum": None,
        "maximum": None,
        "standard_deviation": None,
        "slope_per_s": None,
    }
    if not rows:
        return out
    values = np.array([r["value"] for r in rows], dtype=float)
    times = np.array([r["t_available_s"] for r in rows], dtype=float)
    centred = times - times.mean()
    denominator = float(centred @ centred)
    out.update(
        mean=float(values.mean()),
        minimum=float(values.min()),
        maximum=float(values.max()),
        standard_deviation=float(values.std()),
        slope_per_s=None if denominator == 0 else float(centred @ values / denominator),
    )
    return out


def quality_target(summary: dict[str, Any]) -> dict[str, Any]:
    """Observed quality events, without equating missing evidence with healthy equipment."""
    return {
        "channels": [
            {
                "tag_id": s["tag_id"],
                "missing_samples": s["missing_samples"],
                "non_good_samples": s["bad_quality_samples"],
                "latest_reading_missing": s["latest_value"] is None,
            }
            for s in summary["signals"]
        ],
        "equipment_health_conclusion": None,
    }


def reference_supervision(
    record: dict[str, Any],
    cutoff_s: float,
    lookback_s: float,
    evidence_delay_s: float,
    windows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Keep existing injection truth separate from a conservative supervised-loss mask."""
    start = cutoff_s - lookback_s
    reasons = []
    if record["tier"] != "analytic_verification":
        reasons.append("restricted_source_model")
    if any(
        w.get("affects_emitted_tags", True) and w["t_start_s"] <= cutoff_s and w["t_end_s"] >= start
        for w in windows
    ):
        reasons.append("model_validity_window")
    active = [f for f in record["faults"] if f["onset_s"] <= cutoff_s]
    for fault in active:
        if fault["class"] != "clear":
            reasons.append("visibility_not_clear_in_source_audit")
        if record.get("latent") or fault.get("activity") not in (None, "active"):
            reasons.append("latent_or_unassessed_activity")
        if cutoff_s - fault["onset_s"] < max(
            lookback_s, (fault.get("ramp_s") or 0.0) + evidence_delay_s
        ):
            reasons.append("insufficient_post_onset_context")
    target = [
        {"fault_type": f["fault_type"], "mechanism": f["subtype"], "asset_id": f["asset_id"]}
        for f in active
    ]
    eligible = not reasons
    return {
        "supervised_loss_mask": eligible,
        "mask_reasons": sorted(set(reasons)),
        "injected_components": target if eligible else None,
        "injected_change_present": bool(active) if eligible else None,
        "label_scope": "parameters_injected_in_the_reduced_reference_simulator",
        "field_diagnosis_qualified": False,
    }
