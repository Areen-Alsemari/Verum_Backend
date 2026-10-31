"""Which assets a lineup lets a fault act on.

A leak needs an edge that carries flow in the lineup, a restriction or a pump fault needs an open
valve or a running pump, and a sensor fault can use any continuous pressure, flow or level tag. An
asset that the lineup leaves idle is available only for a latent fault.

See D75, D76 and D84.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache, lru_cache

from verum.faults.validate import ELIGIBLE_VALVES, PUMPS
from verum.hydraulics import HydraulicModel, ReceiptBoundary, SteadyInputs
from verum.lineups import LineupTable, load_lineup_table

SENSOR_TAGS = (
    "FT-001", "PT-001", "LT-101", "LT-102", "LT-103",
    "PT-201", "PT-202A", "PT-202B", "FT-201", "PT-203",
)  # fmt: skip
BASE_LEVELS = {"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0}
PARALLEL_BRANCH_MODE = "RECEIVE_101_102"


@dataclass(frozen=True)
class LineupInfo:
    mode: str
    open_valves: frozenset[str]
    pumps: frozenset[str]
    edges: frozenset[str]

    @property
    def receipt_valves(self) -> list[str]:
        return sorted(v for v in self.open_valves if v in ELIGIBLE_VALVES and v.startswith("XV-R"))

    @property
    def delivery_valves(self) -> list[str]:
        return sorted(
            v for v in self.open_valves if v in ELIGIBLE_VALVES and not v.startswith("XV-R")
        )

    @property
    def receipt_edges(self) -> list[str]:
        return sorted(e for e in self.edges if e.startswith(("E00", "E-R")))

    @property
    def delivery_edges(self) -> list[str]:
        return sorted(e for e in self.edges if e.startswith("E-") and not e.startswith("E-R"))

    @property
    def idle_valves(self) -> list[str]:
        return sorted(v for v in ELIGIBLE_VALVES if v not in self.open_valves)

    @property
    def idle_pumps(self) -> list[str]:
        return sorted(p for p in PUMPS if p not in self.pumps)


@lru_cache(maxsize=1)
def model_and_table() -> tuple[HydraulicModel, LineupTable]:
    model = HydraulicModel.load()
    return model, load_lineup_table(model.topology)


@cache
def lineup_info(mode: str) -> LineupInfo:
    """Valves, pumps and the edges that carry flow, from a steady solve at the reference levels."""
    model, table = model_and_table()
    m = table.mode(mode)
    flow = 600.0 if m.receiving else 0.0
    inputs = SteadyInputs(
        m.lineup, BASE_LEVELS, "RVP_9_0", 25.0, fitting_profile="reference_fittings",
        receipt=ReceiptBoundary(flow_m3h=flow),
    )  # fmt: skip
    edges = frozenset(model.solve(inputs).active_edges)
    return LineupInfo(mode, frozenset(m.open_valves), frozenset(m.running_pumps), edges)


def leak_pool() -> list[str]:
    """Every edge that carries flow in some lineup of a campaign."""
    modes = (
        "DELIVER_101_A", "DELIVER_102_A", "DELIVER_103_A", "DELIVER_101_B", "DELIVER_102_B",
        "DELIVER_103_B", "RECEIVE_101", "RECEIVE_102", "RECEIVE_103", "RECEIVE_101_102",
    )  # fmt: skip
    return sorted({e for m in modes for e in lineup_info(m).edges})
