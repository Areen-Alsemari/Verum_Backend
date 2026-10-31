"""Eligibility of a fault specification: asset, ranges, onset, ramp and the one-fault rule.

The check returns the list of violations, empty if the specification is eligible, and the strict
form raises. It covers onset and ramp times, the range of each physical parameter, one fault per
episode and per asset, the choice of asset, and the restriction mode. Conditions that depend on the
run, such as the leak pressure and the engine gates, are not checked here and reject the candidate
while it runs.

See D60 to D66, D74 and D75.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from verum.contracts.errors import ContractError
from verum.faults import spec as fs
from verum.faults.activity import LineupState, on_parallel_branch

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


def _mode(spec: fs.FaultSpec) -> list[str]:
    """Decision D74: a restriction names its mode; no other fault has one."""
    if spec.fault_type == fs.RESTRICTION:
        if spec.fault_mode in fs.RESTRICTION_MODES:
            return []
        return [
            f"a restriction needs a fault_mode in {fs.RESTRICTION_MODES}, not {spec.fault_mode}"
        ]
    return [] if spec.fault_mode is None else [f"{spec.fault_type} has no fault_mode"]


def _branch(spec: fs.FaultSpec, states: Sequence[LineupState] | None) -> list[str]:
    """Decision D75: a valve stuck nearly closed must be on a parallel branch at the onset."""
    if spec.variant != "open_but_stuck":
        return []
    if not states:
        return ["misrouting (b) needs the lineup in force at the onset to test the branch"]
    if on_parallel_branch(spec.asset_id, states[0]):
        return []
    return [f"{spec.asset_id} is not on a parallel branch: misrouting (b) is not eligible"]


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
    states: Sequence[LineupState] | None = None,
    max_faults: int = 1,
    min_separation_s: float = 0.0,
) -> list[str]:
    problems: list[str] = []
    if len(specs) > max_faults:
        problems.append(
            "one fault per episode in this phase"
            if max_faults == 1
            else f"at most {max_faults} faults per episode"
        )
    onsets = sorted(s.onset_s for s in specs)
    if any(b - a < min_separation_s for a, b in zip(onsets, onsets[1:], strict=False)):
        problems.append(f"onsets must be at least {min_separation_s:g} s apart")
    seen: set[str] = set()
    for spec in specs:
        if spec.variant not in fs.VARIANTS.get(spec.fault_type, ()):
            problems.append(f"{spec.variant} is not a variant of {spec.fault_type}")
            continue
        if spec.asset_id in seen:
            problems.append(f"two faults on {spec.asset_id}")
        seen.add(spec.asset_id)
        problems += _asset(spec, edges, continuous_tags) + _timing(spec, duration_s)
        problems += _magnitude(spec) + _mode(spec) + _branch(spec, states)
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
    states: Sequence[LineupState] | None = None,
    max_faults: int = 1,
    min_separation_s: float = 0.0,
) -> None:
    problems = violations(
        specs, edges, continuous_tags, duration_s, states, max_faults, min_separation_s
    )
    if problems:
        raise ContractError("fault specification rejected: " + "; ".join(problems))
