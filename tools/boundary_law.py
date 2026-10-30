"""Delivery boundary-law coefficient c per fitting profile (study 1 of decision D2 version 3.0).

Inputs: the plant model. Outputs: the ``parameters`` block of ``config/delivery_boundary.json``
(rewritten in place) and a printed line per profile.
Assumptions: for each profile, c is the value for which TK-102 at 7 m, pump A, 25 C and the
reference property class runs at 300 m3/h (42 m of head on the fixed-speed curve); a flow outside
the pump curve counts as 1000 m3/h so that the root find stays bracketed.
Source: ``docs/design_decisions.md`` D2 version 3.0, D15.
"""

from __future__ import annotations

import json
from pathlib import Path

from scipy.optimize import brentq

from verum.graph import Lineup
from verum.hydraulics import DeliveryBoundary, HydraulicModel, PumpOutsideCurve, SteadyInputs

SCENARIO = "EPA_GENERIC_RVP10_REFERENCE"
LINEUP = Lineup.of({"XV-S102", "XV-PAI", "XV-PAO"}, {"P-101A"})
PROFILES = ("pipe_only", "reference_fittings")


def solve(model: HydraulicModel, profile: str, c: float) -> tuple[float, float]:
    """Pump flow (m3/h) and head rise (m) at the coefficient c, or an out-of-curve marker."""
    inputs = SteadyInputs(
        LINEUP, {"TK-102": 7.0}, SCENARIO, 25.0, fitting_profile=profile,
        delivery=DeliveryBoundary(law_coefficient_m=c),
    )  # fmt: skip
    try:
        point = model.solve(inputs).pump
    except PumpOutsideCurve:
        return 1000.0, float("nan")
    assert point is not None
    return point.flow_m3h, point.head_rise_m


def main() -> None:
    model = HydraulicModel.load()
    out = {}
    for profile in PROFILES:
        c = brentq(lambda x, p=profile: solve(model, p, x)[0] - 300.0, 0.5, 20.0, xtol=1e-12)
        flow, head = solve(model, profile, c)
        print(profile, f"c = {c:.6f} m", f"Q = {flow:.4f} m3/h", f"H = {head:.4f} m")
        out[profile] = {
            "value": round(c, 6), "unit": "m", "status": "provisional", "evidence_tag": "CALC",
            "provenance_id": "VERUM-DD-D2-v3.0",
        }  # fmt: skip
    path = Path("config/delivery_boundary.json")
    doc = json.loads(path.read_text())
    doc["parameters"] = out
    path.write_text(json.dumps(doc, indent=2) + "\n")


if __name__ == "__main__":
    main()
