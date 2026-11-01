"""Synthetic history of the assets: prior inspections, calibrations and work orders.

The history is generated from the episode seed with one named stream per asset and does not depend
on the faults of the episode, which is a stated choice of version 1. A record states a kind, a time
before the start of the episode, the action or the work type and an outcome, and it holds no
measured value. An inspection that is performed in the episode adds a record when its result
becomes visible.

See D107.
"""

from __future__ import annotations

from typing import Any

from verum.inspection.assets import Assets
from verum.inspection.catalog import Catalog
from verum.rng import RandomStreams

SCHEMA_VERSION = "0.7.0"
DAY_S = 86400.0
ACTIONS_BY_KIND = {
    "tank": ("ACT-INSP-01", "ACT-INSP-05", "ACT-INSP-06"),
    "pump": ("ACT-INSP-03",),
    "isolation_valve": ("ACT-INSP-02",),
    "pipe": ("ACT-INSP-04",),
    "pressure_transmitter": ("ACT-INSP-07",),
}
WORK_TYPES = (
    "routine_maintenance", "gasket_replacement", "strainer_cleaning", "instrument_check",
    "lubrication", "coating_repair",
)  # fmt: skip
TEXT = {
    "NORMAL_INTACT": "Inspection completed; no finding.",
    "MINOR_DEGRADATION": "Inspection completed; minor wear noted for follow-up.",
}


def _record(asset: str, kind: str, t: float, description: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "dataset": "inspection_history", "asset_id": asset,
        "kind": kind, "t_recorded_s": t, "description": description, **extra,
    }  # fmt: skip


def prior_history(seed: int, catalog: Catalog, assets: Assets) -> list[dict[str, Any]]:
    """Prior records of every asset, in time order, with identifiers in that order."""
    streams = RandomStreams(seed)
    horizon = catalog.param("history", "horizon_days") * DAY_S
    p_normal = catalog.param("history", "prior_normal_probability")
    p_within = catalog.param("history", "calibration_within_tolerance_probability")
    records: list[dict[str, Any]] = []
    for item in assets.listing():
        asset, kind = item["asset_id"], item["kind"]
        rng = streams.stream(f"history/{asset}")
        for _ in range(int(rng.integers(0, 4))):
            t = -float(rng.uniform(1.0, horizon))
            action = ACTIONS_BY_KIND[kind][int(rng.integers(len(ACTIONS_BY_KIND[kind])))]
            outcome = "NORMAL_INTACT" if rng.random() < p_normal else "MINOR_DEGRADATION"
            records.append(_record(asset, "inspection", t, TEXT[outcome], action_id=action,
                                   outcome_category=outcome))  # fmt: skip
        if kind == "pressure_transmitter":
            for _ in range(int(rng.integers(1, 3))):
                t = -float(rng.uniform(1.0, horizon))
                ok = bool(rng.random() < p_within)
                text = (
                    "Calibration completed; as-found within tolerance."
                    if ok
                    else ("Calibration completed; as-found outside tolerance and adjusted.")
                )
                records.append(_record(asset, "calibration", t, text, within_tolerance=ok))
        for _ in range(int(rng.integers(0, 3))):
            t = -float(rng.uniform(1.0, horizon))
            work = WORK_TYPES[int(rng.integers(len(WORK_TYPES)))]
            records.append(_record(asset, "work_order", t, f"Work order closed: {work}.",
                                   work_type=work))  # fmt: skip
    records.sort(key=lambda r: (r["t_recorded_s"], r["asset_id"], r["kind"]))
    return [{**r, "record_id": f"HIST-{i:06d}"} for i, r in enumerate(records)]


def result_record(
    index: int, asset: str, action_id: str, category: str, t_visible_s: float
) -> dict[str, Any]:
    """The record that a performed inspection adds when its result becomes visible."""
    return {
        **_record(asset, "inspection", t_visible_s, "Inspection result recorded.",
                  action_id=action_id, outcome_category=category),
        "record_id": f"HIST-{900000 + index:06d}",
    }  # fmt: skip
