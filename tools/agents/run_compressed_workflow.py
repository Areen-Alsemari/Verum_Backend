"""Run the real chain on the meaningful validation windows with a simulated compressed follow-up.

For each meaningful window of the validation sample, a SIMULATED inspection is built by a fixed
rule from the first option Agent 6 lists, and the next real window of the episode is the
second pass. The rule reads no label and the inspection is treated as performed at the first
cutoff, so the result tests the plumbing and is not evidence of detection quality. Outputs go
to the output folder.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_runner_sample as sample  # noqa: E402
import simulate_followup_targets as followup  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
MARK_TEXT = "SIMULATED INSPECTION"
MARK_FLAG = "time_compressed: true"
MARKER = f"{MARK_TEXT}; {MARK_FLAG}"
CALIBRATION_VALID_UNTIL = "2026-12-31"
SCHEMA_VERSION = "0.5.0"
MEANINGFUL = "inspectable, Agent 5 names it first"
NO_SECOND_PASS = "no second pass available"
RULE = (
    "Rule R1. The target and action are the first option of the Agent 6 report that addresses a "
    "hypothesis. The request is approved and made at the first cutoff; the inspection is treated "
    "as performed at that same cutoff. The result is valid (research mode), passed quality "
    "assurance, reports the first catalogue output of the action with the value 0.0 and the "
    "catalogue uncertainty (0.0 where the catalogue states none, as for the unqualified actions), "
    "and the category TEST_INCONCLUSIVE, so it states no condition. "
    "Identifiers come from a counter over the meaningful windows in processing order."
)


def utc_of(start_utc: str, as_of_s: float) -> str:
    """The wall-clock cutoff: the synthetic episode start plus the cutoff in seconds.

    A window at 300 s gets the start plus five minutes. The second pass is the next real window of
    the episode, 300 s later, and a window without one reports "no second pass available".
    """
    start = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
    moment = (start + timedelta(seconds=as_of_s)).astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def episode_start_utc() -> str:
    """The fixed synthetic start of every episode, read from the sensor configuration file."""
    config = json.loads((REPO / "config" / "sensors.json").read_text(encoding="utf-8"))
    return str(config["episode_start_utc"])


def chosen_option(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """The first Agent 6 option that addresses a hypothesis, or None."""
    if plan is None or plan["result"] is None:
        return None
    for option in plan["result"]["options"]:
        if option["addresses_hypothesis_ids"]:
            return dict(option)
    return None


def competing(diagnosis: dict[str, Any] | None) -> list[str]:
    """Two hypothesis identifiers of Agent 5 for the request, padded with a marked note."""
    found = []
    if diagnosis is not None and diagnosis["result"] is not None:
        found = [h["hypothesis_id"] for h in diagnosis["result"]["hypotheses"][:2]]
    while len(found) < 2:
        found.append(f"{MARK_TEXT}: no further hypothesis was reported")
    return found


def make_request(
    serial: int, option: dict[str, Any], hypotheses: list[str], cutoff_s: float
) -> dict[str, Any]:
    """The approved inspection request, made at the first cutoff."""
    return {
        "schema_version": SCHEMA_VERSION, "dataset": "inspection_requests",
        "request_id": f"REQ-INSP-{serial:05d}", "t_requested_sim_s": cutoff_s,
        "action_id": option["action_id"], "target_asset": option["target_asset"],
        "justification": {
            "competing_hypotheses": hypotheses,
            "agent_reported_information_gain_bits": option["expected_information_gain_bits"] or 0.0,
            "estimated_cost_usd": option["cost_usd"],
        },
        "human_approval": {
            "status": "APPROVED", "approver_id": MARKER, "work_permit_number": MARKER,
        },
    }


def make_result(
    serial: int, request: dict[str, Any], catalog: list[dict[str, Any]], performed_s: float
) -> dict[str, Any]:
    """The simulated performed result of the request, by rule R1."""
    action = next(a for a in catalog if a["action_id"] == request["action_id"])
    output = action["outputs"][0]
    return {
        "schema_version": SCHEMA_VERSION, "dataset": "inspection_results",
        "result_id": f"RES-INSP-{serial:05d}", "request_id": request["request_id"],
        "action_id": request["action_id"], "workflow_status": "performed",
        "evidence_status": "valid", "performed_at_t_sim_s": performed_s,
        "technician_id": MARK_TEXT, "tool_serial": MARKER,
        "calibration_valid_until": CALIBRATION_VALID_UNTIL,
        "findings": {
            "outcome_category": "TEST_INCONCLUSIVE",
            "primary_metric": {
                "name": output["name"], "value": 0.0, "unit": output["unit"],
                "uncertainty_k2": output["uncertainty_k2"] or 0.0,
            },
            "secondary_observations": [MARK_TEXT, MARK_FLAG, RULE],
        },
        "validation_status": "PASSED_QA",
    }


def make_coverage(serial: int, request: dict[str, Any], second_cutoff_s: float) -> dict[str, Any]:
    """A coverage row from the start of the process to the second cutoff for the target."""
    from verum.agents.runner.prepare import FEATURES, SOURCE

    return {
        "coverage_id": f"COV-SIM-{serial:05d} {MARKER}", "target_asset": request["target_asset"],
        "start_s": 0.0, "end_s": second_cutoff_s, "evidence_ids": [SOURCE, FEATURES],
    }


def make_proposal(serial: int, result: dict[str, Any], second_cutoff_s: float) -> dict[str, Any]:
    """The evidence proposal that names the simulated result."""
    return {
        "proposal_id": f"PROP-SIM-{serial:05d} {MARKER}",
        "source_ref": f"inspection_result:{result['result_id']}",
        "claimed_available_at_s": second_cutoff_s,
        "claimed_evidence_ids": [f"inspection-result-{result['result_id']}"],
    }


def simulate(
    serial: int, reports: dict[str, Any], cutoff_s: float, second_cutoff_s: float,
    catalog: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """The simulated objects for one window, from first-pass reports only; None without option."""
    option = chosen_option(reports.get("inspection_planning"))
    if option is None:
        return None
    request = make_request(serial, option, competing(reports.get("diagnostic_reasoning")), cutoff_s)
    result = make_result(serial, request, catalog, cutoff_s)
    return {
        "option_id": option["option_id"], "request": request, "result": result,
        "coverage": make_coverage(serial, request, second_cutoff_s),
        "proposal": make_proposal(serial, result, second_cutoff_s),
    }


def status_of(report: dict[str, Any] | None) -> str | None:
    """Status of a report, or None when the role produced none."""
    return None if report is None else str(report["status"])


def decision_of(report: dict[str, Any] | None) -> str | None:
    """Decision state of an Agent 8 report."""
    if report is None or report["result"] is None:
        return None
    return str(report["result"]["decision_state"])


def failed_checks(report: dict[str, Any] | None) -> list[str]:
    """Names of the Agent 7 checks that did not pass, over all records."""
    if report is None or report["result"] is None:
        return []
    rows = report["result"]["record_checks"]
    return sorted({c["check_id"] for r in rows for c in r["checks"] if c["outcome"] != "pass"})


def usable_of(report: dict[str, Any] | None) -> bool | None:
    """Whether Agent 8 judged the proposal usable."""
    if report is None or report["result"] is None or not report["result"]["evidence_checks"]:
        return None
    return report["result"]["evidence_checks"][0]["usable"]


def issue_codes(report: dict[str, Any] | None) -> list[str]:
    """Issue codes of a report, empty when the role produced none."""
    return [] if report is None else [i["code"] for i in report["issues"]]


def pass_summary(bundle: Any) -> dict[str, Any]:
    """Statuses and decision of Agents 6 to 8 in one pass."""
    reports = bundle.reports
    seven = reports.get("inspection_quality_documentation")
    return {
        "agent6": status_of(reports.get("inspection_planning")),
        "agent6_issues": issue_codes(reports.get("inspection_planning")),
        "agent7": status_of(seven),
        "agent7_failed_checks": failed_checks(seven),
        "agent7_issues": issue_codes(seven),
        "agent8": status_of(reports.get("evidence_verification_decision")),
        "agent8_issues": issue_codes(reports.get("evidence_verification_decision")),
        "decision": decision_of(reports.get("evidence_verification_decision")),
        "proposal_usable": usable_of(reports.get("evidence_verification_decision")),
        "run_issues": [[i["role"], i["code"], i["message"][:200]] for i in bundle.issues],
    }


def left_degraded(second: dict[str, Any]) -> bool:
    """Whether Agent 7 and Agent 8 are both no longer degraded after the second pass."""
    return second["agent7"] != "degraded" and second["agent8"] != "degraded"


class Case:
    """The fixed inputs of the run: the reference, its hash, the start time and the next windows."""

    def __init__(self, reference: Any, sha: str, later: dict[tuple[str, int], Any]) -> None:
        self.reference, self.sha, self.later = reference, sha, later
        self.start = episode_start_utc()
        self.serial = 0

    def snapshot(self, case_id: str, w: dict[str, Any], summary: Any) -> Any:
        """The first-pass snapshot of a window, with its wall-clock cutoff."""
        from verum.agents.runner import Snapshot

        cutoff = float(w["cutoff_s"])
        return Snapshot(
            case_id=case_id, revision=0, as_of_s=cutoff, summary=summary,
            reference=self.reference, reference_snapshot_sha256=self.sha,
            as_of_utc=utc_of(self.start, cutoff),
        )


def second_pass(
    case: Case, snap: Any, bundle: Any, w: dict[str, Any], objects: dict[str, Any]
) -> Any:
    """Run the second revision with the simulated objects and the next real window."""
    from verum.agents.runner import next_revision, run_analysis, verify_bundle

    next_summary, next_cutoff = case.later[(w["episode_id"], w["position"] + 1)]
    second = next_revision(
        snap, as_of_s=next_cutoff, summary=copy.deepcopy(next_summary),
        inspection_results=(objects["result"],), inspection_requests=(objects["request"],),
        process_coverage=(objects["coverage"],), as_of_utc=utc_of(case.start, next_cutoff),
    )
    second = replace(second, evidence_proposals=(objects["proposal"],))
    return run_analysis(
        second, "runtime", allow_placeholders=False, previous=verify_bundle(bundle),
        recent=bundle.assessments,
    )


def follow_up(
    case: Case, snap: Any, bundle: Any, w: dict[str, Any], out: Path
) -> dict[str, Any]:
    """The compressed follow-up of one meaningful window, as a row."""
    key = (w["episode_id"], w["position"] + 1)
    if key not in case.later:
        return {"second_pass": NO_SECOND_PASS}
    next_cutoff = case.later[key][1]
    objects = simulate(
        case.serial + 1, bundle.reports, float(w["cutoff_s"]), next_cutoff,
        snap.reference["inspection_catalog"],
    )
    if objects is None:
        return {"second_pass": "no Agent 6 option addresses a hypothesis"}
    case.serial += 1
    sample.dump(out / "simulated" / f"{w['window_id']}.json", objects)
    second = pass_summary(second_pass(case, snap, bundle, w, objects))
    return {
        "second_pass": "run", "option": objects["option_id"],
        "action": objects["request"]["action_id"], "target": objects["request"]["target_asset"],
        "second": second, "left_degraded": left_degraded(second),
    }


def run_window(
    case: Case, case_id: str, w: dict[str, Any], summary: Any, log: Any, out: Path
) -> tuple[dict[str, Any], Any]:
    """First pass of one window, and the follow-up when the window is meaningful."""
    from verum.agents.runner import run_analysis

    snap = case.snapshot(case_id, w, summary)
    bundle = run_analysis(snap, "runtime", allow_placeholders=False, recent=log)
    row: dict[str, Any] = {
        "window_id": w["window_id"], "episode_id": w["episode_id"], "position": w["position"],
        "cutoff_s": w["cutoff_s"], "first": pass_summary(bundle), "meaningful": False,
    }
    assets = {a["asset_id"] for a in snap.reference["assets"]}
    probe = {"w": w, "b": {"reports": bundle.reports}}
    if w["fault"] and followup.classify(probe, assets) == MEANINGFUL:
        row["meaningful"] = True
        row.update(follow_up(case, snap, bundle, w, out))
    return row, bundle.assessments


def run_episodes(
    case: Case, windows: list[dict[str, Any]], summaries: dict[str, Any], out: Path
) -> list[dict[str, Any]]:
    """Run the windows of each episode in time order with a shared assessment log."""
    from verum.agents.runner import AssessmentLog

    episodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for w in windows:
        episodes[w["episode_id"]].append(w)
    rows: list[dict[str, Any]] = []
    for e, (_, members) in enumerate(sorted(episodes.items())):
        log, last = AssessmentLog(), None
        for w in sorted(members, key=lambda x: x["position"]):
            log = sample.pad_gap(log, f"E{e:04d}", last, w["position"])
            row, log = run_window(case, f"E{e:04d}", w, summaries[w["window_id"]], log, out)
            rows.append(row)
            last = w["position"]
            print(len(rows), w["window_id"], flush=True)
    return rows


def later_windows(records: list[Any], lineage: dict[str, Any], keep: set[str]) -> dict[Any, Any]:
    """Summary and cutoff of every validation window of the given episodes, by episode and place."""
    found: dict[tuple[str, int], Any] = {}
    for r in records:
        ref = lineage[r.example_id]
        if ref.episode_id in keep:
            found[(ref.episode_id, sample.position_of(r, lineage))] = (
                r.input["observations"], float(ref.source_cutoff_s),
            )
    return found


def main() -> int:
    """Draw the validation sample, run the chain and the compressed follow-ups, and summarise."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="folder for the run outputs")
    parser.add_argument("--release", type=Path, default=sample.DEFAULT_RELEASE)
    args = parser.parse_args()
    sample.install_audit()
    sample.install_guard()
    from verum.agents.common import file_sha256

    ref_path = args.release / "knowledge" / "public_reference.json"
    reference = json.loads(ref_path.read_text())
    records, lineage = sample.load_split(args.release, "validation")
    windows = sample.build_sample(records, lineage)
    ids = {w["window_id"] for w in windows}
    summaries = sample.summary_of(records, ids)
    later = later_windows(records, lineage, {w["episode_id"] for w in windows})
    case = Case(reference, file_sha256(ref_path), later)
    rows = run_episodes(case, windows, summaries, args.out)
    sample.dump(args.out / "rows.json", rows)
    meta = {
        "windows": len(rows), "rule": RULE, "marker": MARKER,
        "test_split_files_touched": sample.touched_test_split(), "guard": sample.guard_summary(),
    }
    sample.dump(args.out / "meta.json", meta)
    print("done", len(rows), "test split touched:", meta["test_split_files_touched"], flush=True)
    return 1 if meta["test_split_files_touched"] or meta["guard"]["rejected"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
