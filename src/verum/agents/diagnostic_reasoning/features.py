"""Extraction of fixed-order numerical features from observation summaries.

Only the summary representation is read; transport metadata, identifiers and target masks never
enter the feature vector. Missing measurements and quality indicators are preserved as explicit
numeric channels so preprocessing can be fitted on training rows alone.
"""

from __future__ import annotations

from typing import Any, Final

import numpy as np

from verum.agents.common import TAG_ORDER, to_plain

FEATURE_PROFILE_ID: Final = "summary_v1_tabular_30tags_v1"
CONTINUOUS_FIELDS: Final[tuple[str, ...]] = (
    "latest_value",
    "previous_measured_value",
    "mean",
    "minimum",
    "maximum",
    "standard_deviation",
    "slope_per_s",
    "latest_received_age_s",
    "previous_measured_age_s",
    "rows_received",
    "measured_count",
    "missing_samples",
    "bad_quality_samples",
)


def _num(value: Any) -> tuple[float, float]:
    """Return a finite value and a present indicator (1.0 when present, 0.0 when missing)."""
    if value is None or isinstance(value, bool):
        return 0.0, 0.0
    val = float(value)
    if not np.isfinite(val):
        raise ValueError("non-finite observation feature")
    return val, 1.0


def _quality_code(quality: Any) -> float:
    if quality == "good":
        return 0.0
    if quality == "suspect":
        return 1.0
    if quality == "bad":
        return 2.0
    return -1.0


def feature_names() -> list[str]:
    """Return the ordered list of feature names matching the extracted vector."""
    names: list[str] = []
    for tag in TAG_ORDER:
        for field in CONTINUOUS_FIELDS:
            names.append(f"{tag}__{field}")
            names.append(f"{tag}__{field}_present")
        names.append(f"{tag}__latest_quality_code")
        names.append(f"{tag}__latest_is_measured")
        names.append(f"{tag}__age_lower_bound")
    names.extend(
        [
            "derived__flow_imbalance_m3h",
            "derived__level_slope_sum_ms",
            "derived__pump_a_dp_barg",
            "derived__pump_b_dp_barg",
            "derived__delivery_dp_barg",
        ]
    )
    return names


def extract_observation_vector(observations: dict[str, Any]) -> np.ndarray:
    """Convert one summary observation object into a 1-D float64 feature vector."""
    clean: dict[str, Any] = to_plain(observations)
    if "representation" in clean:
        if clean.get("representation") != "summary_v1":
            rep = clean.get("representation")
            raise ValueError(f"unsupported observation representation: {rep!r}")
        summary = clean.get("summary")
    else:
        summary = clean
    if not isinstance(summary, dict) or "signals" not in summary:
        raise ValueError("malformed summary observation payload")
    by_tag = {row["tag_id"]: row for row in summary["signals"]}
    if set(by_tag) != set(TAG_ORDER):
        raise ValueError("summary signals do not match the canonical tag order")
    values: list[float] = []
    for tag in TAG_ORDER:
        sig = by_tag[tag]
        for field in CONTINUOUS_FIELDS:
            val, present = _num(sig.get(field))
            values.append(val)
            values.append(present)
        values.append(_quality_code(sig.get("latest_quality")))
        values.append(1.0 if sig.get("latest_availability") == "measured" else 0.0)
        values.append(1.0 if sig.get("latest_received_age_is_lower_bound") is True else 0.0)
    ft001 = _num(by_tag["FT-001"].get("mean"))[0]
    ft201 = _num(by_tag["FT-201"].get("mean"))[0]
    lt_slopes = sum(_num(by_tag[t].get("slope_per_s"))[0] for t in ("LT-101", "LT-102", "LT-103"))
    pt201 = _num(by_tag["PT-201"].get("mean"))[0]
    pt202a = _num(by_tag["PT-202A"].get("mean"))[0]
    pt202b = _num(by_tag["PT-202B"].get("mean"))[0]
    pt203 = _num(by_tag["PT-203"].get("mean"))[0]
    values.extend(
        [
            ft001 - ft201,
            lt_slopes,
            pt202a - pt201,
            pt202b - pt201,
            max(pt202a, pt202b) - pt203,
        ]
    )
    return np.asarray(values, dtype=np.float64)
