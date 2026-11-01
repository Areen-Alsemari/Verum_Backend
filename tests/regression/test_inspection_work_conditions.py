"""Cancellation during inspection work without premature disclosure of future process changes.

Hand-built process records isolate workflow semantics from hydraulic-model qualification.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from _inspection_cases import grid, request, write
from verum.inspection.assets import load_assets
from verum.inspection.catalog import load_catalog
from verum.inspection.models import perform
from verum.inspection.service import InspectionService
from verum.params import UnresolvedParameter
from verum.rng import RandomStreams


def test_lost_and_recovered_work_condition_cancels_without_future_leakage(tmp_path: Path) -> None:
    """Brief receipt during a fitting check cancels work despite recovery before its end.

    Independent: yes, because a single literal record changes after approval but during the work.
    """
    rows = grid(horizon=24000.)
    assets = load_assets()
    receipt_edges = [edge.edge_id for edge in assets.receipt_edges("TK-101")]
    for row in rows:
        for edge in receipt_edges:
            row["edges"][edge]["flow_m3s"] = 0.
    safe = InspectionService(write(tmp_path / "safe", rows, horizon=24000.))
    req = None
    for i in range(1, 10):
        candidate = request(i, "ACT-INSP-06", "TK-101")
        safe.submit(candidate, 100.)
        if safe.record(candidate["request_id"]).timeline.approved:
            req = candidate
            break
    assert req is not None
    tl = safe.record(req["request_id"]).timeline
    changed_time = math.ceil((tl.t_start_s + tl.t_performed_s) / 120.) * 60.
    assert tl.t_start_s < changed_time < tl.t_performed_s
    for row in rows:
        if row["t_sim_s"] == changed_time:
            row["edges"][receipt_edges[0]]["flow_m3s"] = .1
    changed = InspectionService(write(tmp_path / "changed", rows, horizon=24000.))
    changed.submit(req, 100.)
    rec = changed.record(req["request_id"])
    assert rec.cancellation == (changed_time, "TANK_IN_RECEIPT_MODE")
    assert rec.outcome is None
    assert changed.requests(changed_time - .001)[0]["human_approval"]["status"] == "APPROVED"
    before = changed.results(changed_time - .001)[0]
    assert before["workflow_status"] == "approved" and "findings" not in before
    assert changed.results(changed_time)[0]["workflow_status"] == "cancelled"
    assert "findings" not in changed.results(tl.t_visible_s)[0]
    assert changed.history(tl.t_visible_s) == changed.history(0.)


@pytest.mark.parametrize("action", ["ACT-INSP-01", "ACT-INSP-03", "ACT-INSP-04", "ACT-INSP-06"])
def test_missing_measurement_cannot_assert_condition(tmp_path: Path, action: str) -> None:
    """Without a qualified equipment measurement, a liquid state cannot establish condition.

    Independent: yes, because the fixture supplies liquid level but no seal condition measurement.
    """
    rows = grid(horizon=24000.)
    for row in rows:
        for edge in load_assets().receipt_edges("TK-101"):
            row["edges"][edge.edge_id]["flow_m3s"] = 0.
    service = InspectionService(write(tmp_path, rows, horizon=24000.))
    target = {"ACT-INSP-03": "P-101A", "ACT-INSP-04": "E-D1"}.get(action, "TK-101")
    performed = None
    for i in range(1, 10):
        req = request(i, action, target, t=1800.)
        service.submit(req, 1800.)
        rec = service.record(req["request_id"])
        if rec.timeline.approved:
            performed = rec
            break
    assert performed is not None and performed.outcome is not None
    result = service.results(performed.timeline.t_visible_s)[-1]
    assert result["evidence_status"] == "missing"
    assert result["findings"]["outcome_category"] == "TEST_INCONCLUSIVE"
    assert result["findings"]["primary_metric"]["name"] == "measurement_available"
    assert result["findings"]["primary_metric"]["value"] == 0.


def test_valve_measurements_do_not_require_unsourced_severity_thresholds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pressure/travel measurements remain available when valve severity thresholds are unresolved.

    Independent: yes, because deliberately unreadable limits cannot establish a severity class.
    """
    catalog = load_catalog()
    original = catalog.param

    def parameter(group: str, key: str) -> float:
        if group == "thresholds" and key.startswith("valve_dp_"):
            raise UnresolvedParameter("equipment-specific severity threshold unavailable")
        return original(group, key)

    monkeypatch.setattr(catalog, "param", parameter)
    state = grid(horizon=60.)[0]
    result = perform(catalog, load_assets(), state, "ACT-INSP-02", "XV-S101",
                     RandomStreams(4242).stream("valve-metric-without-severity"))
    assert math.isfinite(result.value) and result.uncertainty_k2 > 0
    assert result.category == "TEST_INCONCLUSIVE" and result.evidence == "low_confidence"


@pytest.mark.parametrize("action,target", [("ACT-INSP-05", "TK-101"), ("ACT-INSP-07", "PT-201")])
def test_numeric_level_and_calibration_readings_do_not_assert_equipment_acceptance(
    action: str, target: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reading generation does not require an unqualified agreement threshold or comparator model.

    Independent: yes, because unavailable comparators cannot certify equipment condition.
    """
    catalog = load_catalog()
    original = catalog.param

    def parameter(group: str, key: str) -> float:
        if key in ("level_transmitter_uncertainty_mm",
                   "pressure_transmitter_uncertainty_percent_span"):
            raise UnresolvedParameter("acceptance comparator unqualified")
        return original(group, key)

    monkeypatch.setattr(catalog, "param", parameter)
    result = perform(catalog, load_assets(), grid(horizon=60.)[0], action, target,
                     RandomStreams(4242).stream("reading-without-acceptance"))
    assert math.isfinite(result.value) and result.uncertainty_k2 > 0
    assert result.category == "TEST_INCONCLUSIVE" and result.evidence == "low_confidence"


def test_default_history_does_not_invent_prior_maintenance(tmp_path: Path) -> None:
    """No past inspections or calibrations are asserted when no actual records were supplied.

    Independent: yes, because no historical events are supplied.
    """
    service = InspectionService(write(tmp_path, grid(horizon=60.), horizon=60.))
    assert service.history(0.) == []
