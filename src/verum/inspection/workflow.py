"""The approval emulator: the timeline of one request.

A request is decided after an approval delay, scheduled after a scheduling delay, performed after
the duration of its action, and visible a fixed time after it is performed. All draws come from one
named stream of the episode seed keyed by the request identifier, and the same number of draws is
made whatever the outcome, so a request has the same timeline whatever the other requests are.
Measurements beyond recorded process coverage require explicit historical research replay.

See D101 and D104.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from verum.inspection import preconditions
from verum.inspection.assets import Assets
from verum.inspection.catalog import Catalog
from verum.inspection.truth import Truth
from verum.rng import RandomStreams
from verum.sensors import load_sensor_config

NON_SAFETY_REASON = "NON_SAFETY_REASON"


@dataclass(frozen=True)
class Timeline:
    request_id: str
    action_id: str
    target: str
    t_requested_s: float
    t_decision_s: float
    reason: str | None  # None: approved
    approver_id: str
    work_permit_number: str
    t_start_s: float
    t_performed_s: float
    t_visible_s: float
    technician_id: str
    tool_serial: str
    calibration_valid_until: str

    @property
    def approved(self) -> bool:
        return self.reason is None


def plan(
    catalog: Catalog, assets: Assets, truth: Truth, request_id: str, action_id: str, target: str,
    t_requested_s: float, *, allow_extrapolated_research: bool = False,
) -> Timeline:  # fmt: skip
    """The timeline of a request; the precondition is checked against the truth at the decision."""
    u = RandomStreams(truth.seed).stream(f"inspection/{request_id}/workflow").random(8)
    p = catalog.param
    lo, hi = p("workflow", "approval_delay_min_s"), p("workflow", "approval_delay_max_s")
    t_decision = t_requested_s + lo + (hi - lo) * float(u[0])
    reason = NON_SAFETY_REASON if u[1] < p("workflow", "rejection_probability") else None
    s_lo, s_hi = p("workflow", "scheduling_delay_min_s"), p("workflow", "scheduling_delay_max_s")
    t_start = t_decision + s_lo + (s_hi - s_lo) * float(u[2])
    t_performed = t_start + catalog.action(action_id).duration_s
    # Planned duration is known when scheduling; this does not inspect future process outcomes.
    if not allow_extrapolated_research and t_performed > truth.coverage_end_s:
        reason = "INSUFFICIENT_SIMULATED_HORIZON"
    elif reason is None:
        reason = preconditions.check(catalog, assets, truth, action_id, target, t_decision)
    start = date.fromisoformat(load_sensor_config().episode_start_utc[:10])
    valid_until = start + timedelta(days=30 + int(u[7] * 335))
    return Timeline(
        request_id, action_id, target, t_requested_s, t_decision, reason,
        f"OPS-{10 + int(u[3] * 90):02d}", f"WP-{10000 + int(u[4] * 90000):05d}", t_start,
        t_performed, t_performed + p("workflow", "result_delay_s"),
        f"TECH-{100 + int(u[5] * 900):03d}", f"SN-{100000 + int(u[6] * 900000):06d}",
        valid_until.isoformat(),
    )  # fmt: skip
