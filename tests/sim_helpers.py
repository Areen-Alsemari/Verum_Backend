"""Small readers shared by the protection-row tests.

They return the protection rows of a tank and its tank levels from a written episode, using gzip and
json only.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any


def protection_rows(
    directory: Path, tank: str
) -> tuple[list[tuple[float, dict[str, Any]]], dict[float, float]]:
    rows: list[tuple[float, dict[str, Any]]] = []
    levels: dict[float, float] = {}
    with gzip.open(directory / "hydraulic_state.jsonl.gz", "rt") as handle:
        for line in handle:
            r = json.loads(line)
            if r["side"] == "pre_event" or r["element_id"] != tank:
                continue
            if r["record_type"] == "protection_state":
                rows.append((r["t_sim_s"], r["payload"]))
            elif r["record_type"] == "tank_state":
                levels[r["t_sim_s"]] = r["payload"]["level_m"]
    return rows, levels


def esd_timeline() -> dict[str, float]:
    """Times of the emergency isolation scenario, computed from the scenario file by hand
    arithmetic; the derivation is in the "Isolation timeline" section of the verification notes.
    """
    import math

    from verum.rng import RandomStreams
    from verum.sensors import chain, load_sensor_config
    from verum.sim.config import load_sim_config
    from verum.sim.scenario import load_scenario

    scenario = load_scenario("S0u-E")
    sigma = load_sim_config()["detector_offset_sigma_m"]
    offset = float(RandomStreams(scenario.seed).stream("detector/TK-101").normal(0.0, sigma))
    rate = (600.0 / 3600.0) / 706.858347
    trip = (13.0 - offset - 12.3) / rate + 0.2
    candidates = [math.floor(trip) + 1.0]
    for tag, spec in load_sensor_config().tags.items():
        if tag.startswith("LT-"):
            assert spec.interval_s
            phase = chain.sample_phase(tag, spec.interval_s)
            k = math.floor((trip - phase) / spec.interval_s) + 1
            for j in (k - 1, k, k + 1):
                for t in (
                    phase + j * spec.interval_s,
                    phase + j * spec.interval_s + spec.comms_delay_s,
                ):
                    if t > trip:
                        candidates.append(t)
    request = min(candidates)
    return {"offset": offset, "trip": trip, "request": request, "closed": request + 9.99}
