"""Inspection findings require recorded process coverage at the measurement time.

Archived extrapolation is an explicit research option, separate from the default workflow.
"""

from __future__ import annotations

from pathlib import Path

from _inspection_cases import grid, request, write
from verum.inspection.service import InspectionService


def test_default_service_refuses_unrecorded_future_measurements(tmp_path: Path) -> None:
    """A two-hour action cannot measure a process recorded for only one hour.

    Independent: yes, because the action duration alone exceeds the complete recorded horizon.
    """
    service = InspectionService(write(tmp_path, grid()))
    req = request(1, "ACT-INSP-01", "TK-101")
    service.submit(req, 100.)
    rec = service.record(req["request_id"])
    assert rec.timeline.t_performed_s > service.truth.coverage_end_s
    assert rec.timeline.reason == "INSUFFICIENT_SIMULATED_HORIZON"
    assert rec.outcome is None
    assert service.results(1e6)[0]["workflow_status"] == "cancelled"
    assert "findings" not in service.results(1e6)[0]
    assert service.history(1e6) == service.history(0.)


def test_an_overstated_scenario_duration_cannot_extend_recorded_coverage(tmp_path: Path) -> None:
    """A longer declared horizon cannot create missing process records.

    Independent: yes, because the last supplied state remains at 3600 s.
    """
    service = InspectionService(write(tmp_path, grid(), horizon=24000.))
    req = request(1, "ACT-INSP-01", "TK-101")
    service.submit(req, 100.)
    assert service.record(req["request_id"]).timeline.reason == "INSUFFICIENT_SIMULATED_HORIZON"


def test_recorded_future_process_allows_time_gated_results(tmp_path: Path) -> None:
    """An otherwise eligible action within recorded coverage can deliver its result later.

    Independent: yes, because the fixture supplies the full process through measurement time.
    """
    service = InspectionService(write(tmp_path, grid(horizon=24000.), horizon=24000.))
    approved = None
    for i in range(1, 10):
        req = request(i, "ACT-INSP-05", "TK-101")
        service.submit(req, 100.)
        rec = service.record(req["request_id"])
        if rec.timeline.approved:
            approved = rec
            break
    assert approved is not None and approved.outcome is not None
    tl = approved.timeline
    assert tl.t_performed_s <= service.truth.coverage_end_s
    result = next(r for r in service.results(tl.t_visible_s - .001)
                  if r["request_id"] == tl.request_id)
    assert "findings" not in result
    result = next(r for r in service.results(tl.t_visible_s) if r["request_id"] == tl.request_id)
    assert result["workflow_status"] == "performed" and "findings" in result
