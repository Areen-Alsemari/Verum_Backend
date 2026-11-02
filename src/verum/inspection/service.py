"""The inspection service of one episode: requests in, time-gated requests and results out.

A request is validated, given a timeline by the approval emulator and, if it is approved, measured
in the true state at its performed time. The agent-visible views are built for a given time and
checked against the closed schemas: a result carries findings only once its time has passed, and a
request that has not been performed has no findings. The evaluator side keeps the true quantity of
each outcome for the realised-gain computation and the reports.

See D101, D102 and D107.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verum.inspection import history, models, preconditions, workflow
from verum.inspection.assets import Assets, load_assets
from verum.inspection.catalog import Catalog, load_catalog
from verum.inspection.checks import check
from verum.inspection.truth import Truth
from verum.inspection.validation import validate_request
from verum.rng import RandomStreams

SCHEMA_VERSION = "0.5.0"


@dataclass
class Record:
    request: dict[str, Any]
    index: int
    timeline: workflow.Timeline
    outcome: models.Outcome | None
    cancellation: tuple[float, str] | None = None


class InspectionService:
    def __init__(
        self,
        evaluator_directory: Path,
        catalog: Catalog | None = None,
        assets: Assets | None = None,
        *,
        allow_extrapolated_research: bool = False,
    ) -> None:
        self.truth = Truth(evaluator_directory)
        self._catalog = catalog or load_catalog()
        self._assets = assets or load_assets()
        self._allow_extrapolated_research = allow_extrapolated_research
        self._records: dict[str, Record] = {}
        self._prior = (history.prior_history(self.truth.seed, self._catalog, self._assets)
                       if allow_extrapolated_research else [])

    # --- static ----------
    def catalog(self) -> list[dict[str, Any]]:
        return self._catalog.agent_view(allow_legacy_simulation=self._allow_extrapolated_research)

    def assets(self) -> list[dict[str, str]]:
        return self._assets.listing()

    # --- submission ----------
    def submit(self, request: dict[str, Any], as_of_s: float) -> dict[str, Any]:
        """Accept a pending request at ``as_of_s``; raises ``RequestError`` if it is refused."""
        validate_request(request, self._catalog, self._assets, self._records, as_of_s)
        rid, action, target = request["request_id"], request["action_id"], request["target_asset"]
        t_requested = request["t_requested_sim_s"]
        timeline = workflow.plan(
            self._catalog, self._assets, self.truth, rid, action, target, t_requested,
            allow_extrapolated_research=self._allow_extrapolated_research,
        )
        outcome = None
        cancellation = None
        if timeline.approved:
            if not self._allow_extrapolated_research:
                cancellation = preconditions.work_cancellation(
                    self._catalog, self._assets, self.truth, action, target,
                    timeline.t_start_s, timeline.t_performed_s,
                )
        if timeline.approved and cancellation is None:
            rng = RandomStreams(self.truth.seed).stream(f"inspection/{rid}/measurement")
            state = self.truth.state(timeline.t_performed_s)
            outcome = models.perform(
                self._catalog, self._assets, state, action, target, rng,
                allow_legacy_simulation=self._allow_extrapolated_research,
            )
        self._records[rid] = Record(request, len(self._records), timeline, outcome, cancellation)
        return self._request_view(self._records[rid], as_of_s)

    def record(self, request_id: str) -> Record:
        """The evaluator-side record, with the true quantity of the outcome."""
        return self._records[request_id]

    # --- views ----------
    def requests(self, as_of_s: float) -> list[dict[str, Any]]:
        return [self._request_view(r, as_of_s) for r in self._records.values()]

    def results(self, as_of_s: float) -> list[dict[str, Any]]:
        return [self._result_view(r, as_of_s) for r in self._records.values()]

    def history(self, as_of_s: float) -> list[dict[str, Any]]:
        rows = [r for r in self._prior if r["t_recorded_s"] <= as_of_s]
        for rec in self._records.values():
            if rec.outcome is not None and rec.timeline.t_visible_s <= as_of_s:
                rows.append(history.result_record(
                    rec.index, rec.timeline.target, rec.timeline.action_id, rec.outcome.category,
                    rec.timeline.t_visible_s,
                ))  # fmt: skip
        for row in rows:
            check("inspection_history", row)
        return rows

    def _request_view(self, rec: Record, t: float) -> dict[str, Any]:
        tl = rec.timeline
        approval: dict[str, Any] = {"status": "PENDING"}
        if t >= tl.t_decision_s:
            if tl.approved:
                approval = {"status": "APPROVED", "approver_id": tl.approver_id,
                            "work_permit_number": tl.work_permit_number}  # fmt: skip
            else:
                approval = {"status": "REJECTED", "approver_id": tl.approver_id,
                            "rejection_reason": tl.reason}  # fmt: skip
        view = {**rec.request, "human_approval": approval}
        check("inspection_request", view)
        return view

    def _result_view(self, rec: Record, t: float) -> dict[str, Any]:
        tl = rec.timeline
        number = tl.request_id.split("-")[-1]
        view: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION, "dataset": "inspection_results",
            "result_id": f"RES-INSP-{number}", "request_id": tl.request_id,
            "action_id": tl.action_id, "workflow_status": "requested",
        }  # fmt: skip
        if t >= tl.t_decision_s:
            view["workflow_status"] = "approved" if tl.approved else "cancelled"
        if rec.cancellation is not None and t >= rec.cancellation[0]:
            view["workflow_status"] = "cancelled"
        if rec.outcome is not None and t >= tl.t_visible_s:
            o = rec.outcome
            view |= {
                "workflow_status": "performed", "evidence_status": o.evidence,
                "performed_at_t_sim_s": tl.t_performed_s, "technician_id": tl.technician_id,
                "tool_serial": tl.tool_serial,
                "calibration_valid_until": tl.calibration_valid_until,
                "findings": {
                    "outcome_category": o.category,
                    "primary_metric": {"name": o.name, "value": o.value, "unit": o.unit,
                                       "uncertainty_k2": o.uncertainty_k2},
                    "secondary_observations": list(o.notes),
                },
                "validation_status": "PASSED_QA",
            }  # fmt: skip
        check("inspection_result", view)
        return view
