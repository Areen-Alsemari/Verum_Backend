"""Eligibility of a fault specification: asset, ranges, onset, ramp and the one-fault rule.

Inputs: a ``FaultSpec`` list, the topology of the plant, the duration of the episode and the
continuous sensor tags. Outputs: the list of violations (empty if the specification is eligible),
or an exception from ``check``.
Key assumptions:
    * Decision D65: onset in ``[600, T - 1800]`` s; hydraulic faults ramp over 30, 300 or 1200 s;
      only sensor faults may step.
    * Ranges: leak area 2e-6 to 1e-3 m2 and position 0.05 to 0.95 (D60), restriction ceiling 0.15
      to 0.9 (D61), head scale 0.70 to 0.98 (D62), sensor bias and drift 0.002 to 0.05 of span in
      magnitude (D63), a valve forced open to 1 and a valve stuck closed to 0.005 to 0.02 (D64).
    * One fault in the episode and one fault per asset (this phase); a misrouted or restricted valve
      is one of the motorized valves (inlet, outlet, pump branch); the valve of a leak edge is not
      required to be open: whether the edge carries a determined pressure at run time is a gate.
    * Conditions that depend on the run (leak pressure above 10 kPa, every engine gate) are not
      checked here; they reject the candidate while it runs (decision D66).

Source: ``docs/design_decisions.md`` D60 to D66; ``docs/fault_models.md``.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from verum.contracts.errors import ContractError
from verum.faults import spec as fs

LEAK_AREA_M2 = (2.0e-6, 1.0e-3)
LEAK_POSITION = (0.05, 0.95)
RESTRICTION_ALPHA = (0.15, 0.9)
PUMP_HEAD_SCALE = (0.70, 0.98)
SENSOR_FRACTION = (0.002, 0.05)
STUCK_CLOSED_ALPHA = (0.005, 0.02)
ONSET_BEFORE_END_S = 1800.0
ONSET_MIN_S = 600.0
ELIGIBLE_VALVES = (
    "XV-R101", "XV-R102", "XV-R103", "XV-S101", "XV-S102", "XV-S103",
    "XV-PAI", "XV-PAO", "XV-PBI", "XV-PBO",
)  # fmt: skip
PUMPS = ("P-101A", "P-101B")


def _within(x: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= x <= bounds[1]


def _magnitude(spec: fs.FaultSpec) -> list[str]:
    m, v = spec.magnitude, spec.variant
    if spec.fault_type == fs.LEAK and not _within(m, LEAK_AREA_M2):
        return [f"leak area {m:g} m2 outside {LEAK_AREA_M2}"]
    if spec.fault_type == fs.RESTRICTION and not _within(m, RESTRICTION_ALPHA):
        return [f"opening ceiling {m:g} outside {RESTRICTION_ALPHA}"]
    if spec.fault_type == fs.PUMP and not _within(m, PUMP_HEAD_SCALE):
        return [f"head scale {m:g} outside {PUMP_HEAD_SCALE}"]
    if spec.fault_type == fs.SENSOR and v in ("bias", "drift"):
        if not _within(abs(m), SENSOR_FRACTION):
            return [f"{v} {m:g} of span outside +-{SENSOR_FRACTION}"]
    if spec.fault_type == fs.SENSOR and v == "stuck" and m != 0.0:
        return ["a stuck-at has no magnitude"]
    if spec.fault_type == fs.MISROUTING:
        if v == "closed_but_open" and m != 1.0:
            return ["a valve forced open has magnitude 1"]
        if v == "open_but_stuck" and not _within(m, STUCK_CLOSED_ALPHA):
            return [f"stuck opening {m:g} outside {STUCK_CLOSED_ALPHA}"]
    return []


def _asset(
    spec: fs.FaultSpec, edges: Collection[str], continuous_tags: Collection[str]
) -> list[str]:
    ok = {
        fs.LEAK: spec.asset_id in edges,
        fs.RESTRICTION: spec.asset_id in ELIGIBLE_VALVES,
        fs.MISROUTING: spec.asset_id in ELIGIBLE_VALVES,
        fs.PUMP: spec.asset_id in PUMPS,
        fs.SENSOR: spec.asset_id in continuous_tags,
    }[spec.fault_type]
    return [] if ok else [f"{spec.asset_id} is not an eligible asset for {spec.fault_type}"]


def _timing(spec: fs.FaultSpec, duration_s: float) -> list[str]:
    problems = []
    if not ONSET_MIN_S <= spec.onset_s <= duration_s - ONSET_BEFORE_END_S:
        problems.append(f"onset {spec.onset_s:g} s outside [600, {duration_s - 1800:g}]")
    if spec.fault_type == fs.SENSOR:
        if spec.ramp_s is not None and spec.ramp_s not in fs.RAMPS_S:
            problems.append("a sensor fault steps or ramps over 30, 300 or 1200 s")
    elif spec.ramp_s not in fs.RAMPS_S:
        problems.append(f"a hydraulic fault ramps over {fs.RAMPS_S} s, not {spec.ramp_s}")
    return problems


def violations(
    specs: Sequence[fs.FaultSpec],
    edges: Collection[str],
    continuous_tags: Collection[str],
    duration_s: float,
) -> list[str]:
    problems: list[str] = []
    if len(specs) > 1:
        problems.append("one fault per episode in this phase")
    seen: set[str] = set()
    for spec in specs:
        if spec.variant not in fs.VARIANTS.get(spec.fault_type, ()):
            problems.append(f"{spec.variant} is not a variant of {spec.fault_type}")
            continue
        if spec.asset_id in seen:
            problems.append(f"two faults on {spec.asset_id}")
        seen.add(spec.asset_id)
        problems += _asset(spec, edges, continuous_tags) + _timing(spec, duration_s)
        problems += _magnitude(spec)
        if spec.fault_type == fs.LEAK:
            if spec.position is None or not _within(spec.position, LEAK_POSITION):
                problems.append(f"leak position {spec.position} outside {LEAK_POSITION}")
            if spec.discharge_coefficient is None:
                problems.append("a leak needs a discharge coefficient")
    return problems


def check(
    specs: Sequence[fs.FaultSpec],
    edges: Collection[str],
    continuous_tags: Collection[str],
    duration_s: float,
) -> None:
    problems = violations(specs, edges, continuous_tags, duration_s)
    if problems:
        raise ContractError("fault specification rejected: " + "; ".join(problems))
