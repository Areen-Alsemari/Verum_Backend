"""Run inspection actions on stored episodes with known faults and print the outcomes.

For each chosen episode of a campaign folder the action that suits the fault is requested after
the fault is established, goes through the approval emulator, and is measured in the stored true
state. The table lists the action, the fault, the true quantity, the measured quantity with its
expanded uncertainty and the category. A sequence of three actions on one episode gives the cost
and the time of a plan. Episodes are not regenerated.

See D100 to D105.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from verum.campaign import runner
from verum.inspection.catalog import load_catalog
from verum.inspection.service import InspectionService

TRUE_UNIT = {
    "ACT-INSP-02": "bar", "ACT-INSP-03": "mm/s", "ACT-INSP-04": "m3/h", "ACT-INSP-05": "mm",
    "ACT-INSP-07": "percent of span",
}  # fmt: skip
ATTEMPTS = 3


def action_for(fault: dict[str, Any]) -> tuple[str, str] | None:
    """The action and target that suit a fault label, or None if no action fits."""
    sub, asset = fault["subtype"], fault["asset_id"]
    if sub == "leak":
        return "ACT-INSP-04", asset
    if sub.startswith("restriction") or sub == "misroute_a":
        return "ACT-INSP-02", asset
    if sub == "pump":
        return "ACT-INSP-03", asset
    if asset.startswith("LT-"):
        return "ACT-INSP-05", f"TK-{asset[-3:]}"
    if asset.startswith("PT-"):
        return "ACT-INSP-07", asset
    return None


def pick(records: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """One completed episode with an inspectable fault for each subtype, then others."""
    seen: set[str] = set()
    chosen: list[dict[str, Any]] = []
    for r in records:
        if r["status"] != "completed" or not r["faults"]:
            continue
        key = r["faults"][0]["subtype"]
        if key not in seen and action_for(r["faults"][0]) is not None:
            seen.add(key)
            chosen.append(r)
    for r in records:
        if len(chosen) >= count:
            break
        if r["status"] == "completed" and r["faults"] and r not in chosen:
            if action_for(r["faults"][0]) is not None:
                chosen.append(r)
    return chosen[:count]


def request(number: int, action: str, target: str, t: float) -> dict[str, Any]:
    return {
        "schema_version": "0.5.0", "dataset": "inspection_requests",
        "request_id": f"REQ-INSP-{number:05d}", "t_requested_sim_s": t, "action_id": action,
        "target_asset": target,
        "justification": {
            "competing_hypotheses": ["fault present", "no fault", "sensor error"],
            "agent_reported_information_gain_bits": 1.0,
            "estimated_cost_usd": load_catalog().action(action).cost_usd,
        },
        "human_approval": {"status": "PENDING"},
    }  # fmt: skip


def run_one(record: dict[str, Any], root: Path, number: int) -> list[str]:
    fault = record["faults"][0]
    action, target = action_for(fault) or ("", "")
    service = InspectionService(root / "evaluator" / "episodes" / record["episode_id"])
    t = min(3600.0, fault["onset_s"] + (fault["ramp_s"] or 0.0) + 60.0)
    label = f"{fault['subtype']} {fault['asset_id']} ({fault['class']}, {fault['activity']})"
    for attempt in range(ATTEMPTS):
        rid = f"REQ-INSP-{number + attempt:05d}"
        service.submit(request(number + attempt, action, target, t), t)
        rec = service.record(rid)
        if rec.outcome is not None:
            o = rec.outcome
            true = o.true.get("true_value")
            return [
                f"| {action} on {target} | {label} | {true:.4g} {TRUE_UNIT.get(action, '')} | "
                f"{o.value:.4g} {o.unit} | {o.uncertainty_k2:g} | {o.category} | {attempt + 1} |"
            ]
        last = rec.timeline.reason
    return [f"| {action} on {target} | {label} | - | rejected: {last} | - | - | {ATTEMPTS} |"]


def sequence(record: dict[str, Any], root: Path) -> list[str]:
    """Three actions on one episode, performed one after the other, with cost and time."""
    catalog = load_catalog()
    service = InspectionService(root / "evaluator" / "episodes" / record["episode_id"])
    plan = [("ACT-INSP-02", "XV-PAO"), ("ACT-INSP-03", "P-101A"), ("ACT-INSP-04", "E-D1")]
    t0 = 3000.0
    t, planned, incurred, lines = t0, 0.0, 0.0, []
    for k, (action, target) in enumerate(plan):
        number = 900 + k
        service.submit(request(number, action, target, t), t)
        tl = service.record(f"REQ-INSP-{number:05d}").timeline
        planned += catalog.action(action).cost_usd
        incurred += catalog.action(action).cost_usd if tl.approved else 0.0
        state = "approved" if tl.approved else f"rejected ({tl.reason})"
        lines.append(f"| {action} on {target} | {t:.0f} | {state} | {tl.t_visible_s:.0f} |")
        t = tl.t_visible_s
    elapsed = (t - t0) / 60.0
    cost = f"planned {planned:.0f} USD, incurred {incurred:.0f} USD"
    lines.append(f"| total | {t0:.0f} | {cost} | {t:.0f} (elapsed {elapsed:.0f} min) |")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/pilot3"))
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()
    config = runner.load_config(args.root)
    records = runner.load_records(runner.Layout(args.root), list(range(config.n)))
    chosen = pick(records, args.count)
    print("| action | fault | true quantity | measured | U (k=2) | category | requests |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for i, record in enumerate(chosen):
        for line in run_one(record, args.root, 100 * (i + 1)):
            print(line)
    delivery = next(
        r for r in records if r["status"] == "completed" and r["strata"]["family"] == "delivery"
    )
    print()
    print("| step | requested at (s) | decision | result visible at (s) |")
    print("| --- | --- | --- | --- |")
    for line in sequence(delivery, args.root):
        print(line)


if __name__ == "__main__":
    main()
