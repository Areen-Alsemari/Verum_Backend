"""Which shipped scenarios the engine rejects when the fluid temperature is 40 C.

Inputs: the shipped scenarios (``config/scenarios``). Outputs:
``local/results/rejection_at_40c.json`` and a printed table of the outcome of each scenario as
shipped and at 40 C: completed, or the gate,
time and cause of the rejection.
Assumptions: only the temperature of the scenario changes; the volatility class, atmosphere stratum,
levels, schedule and seed are those of the file; no scenario file is edited.
Source: ``docs/design_decisions.md`` D7, D24, D35, D46; serves the tables of the Phase 5b report.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.scenario import load_scenario
from verum.truth import NullSink

SCENARIOS = (
    "S0-A", "S0-B", "S0-C", "S0u-D", "S0u-E", "S0-F", "S0-G", "S0-A-inland",
    "REJ-1", "REJ-2", "REJ-3",
)  # fmt: skip


def outcome(model: HydraulicModel, scenario_id: str, temperature_c: float | None) -> dict[str, Any]:
    scenario = load_scenario(scenario_id)
    if temperature_c is not None:
        scenario = dataclasses.replace(scenario, temperature_c=temperature_c)
    engine = Engine(
        model, load_lineup_table(model.topology), scenario, load_sim_config(), NullSink(), "EP"
    )
    result = engine.run()
    rejection = result.rejection
    return {
        "temperature_c": scenario.temperature_c,
        "atmosphere": scenario.atmosphere_stratum,
        "volatility_class": scenario.volatility_class,
        "completed": rejection is None,
        "rejection": rejection,
    }


def main() -> None:
    model = HydraulicModel.load()
    table = {
        sid: {"as_shipped": outcome(model, sid, None), "at_40c": outcome(model, sid, 40.0)}
        for sid in SCENARIOS
    }
    with open("local/results/rejection_at_40c.json", "w", encoding="utf-8") as fh:
        json.dump(table, fh, indent=1, default=str)
    for sid, res in table.items():
        for key, label in (("as_shipped", "as shipped"), ("at_40c", "40 C")):
            r = res[key]
            cause = "completed" if r["completed"] else str(r["rejection"])
            print(f"{sid:12s} {label:10s} {r['temperature_c']:5.1f} C {r['atmosphere']:8s} {cause}")


if __name__ == "__main__":
    main()
