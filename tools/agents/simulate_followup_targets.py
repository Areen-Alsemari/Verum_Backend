"""Simulate narrower inspection targets for Agent 6 and count the windows a follow-up could serve.

Inputs: the output folder of a full-runner run over the 181-window sample (stored bundles). For
each window it reads the Agent 6 request and the Agent 5 hypotheses, replaces the target list by
the assets that the hypotheses name, and runs Agent 6 on the changed request. It also classifies
the faulty windows by whether the injected fault sits on an asset that the catalog can inspect and
whether Agent 5 names that asset, and counts how many windows leave room for an inspection inside
the recorded process. Nothing is changed in the agents; labels are used for grouping only.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent5_agent2_evidence import table  # noqa: E402

from verum.agents.inspection_planning.agent import InspectionPlanningAgent  # noqa: E402

Row = dict[str, Any]
HORIZON_S = 3600.0
APPROVAL_MIN_S, SCHEDULING_MIN_S, RESULT_DELAY_S = 300.0, 0.0, 120.0
DURATION_S = {
    "ACT-INSP-01": 5400.0, "ACT-INSP-02": 2700.0, "ACT-INSP-03": 3600.0, "ACT-INSP-04": 7200.0,
    "ACT-INSP-05": 2700.0, "ACT-INSP-06": 3600.0, "ACT-INSP-07": 2700.0,
}  # fmt: skip
ACTION_FOR = {
    "leak": "ACT-INSP-04", "restriction_position_visible": "ACT-INSP-02",
    "restriction_obstruction": "ACT-INSP-02", "misroute_a": "ACT-INSP-02",
    "pump": "ACT-INSP-03",
}  # fmt: skip
SENSOR_MECHANISMS = ("bias", "drift", "stuck")
MEASURED_IN_DEFAULT_MODE = ("ACT-INSP-02", "ACT-INSP-05", "ACT-INSP-07")
TANK_OF_LEVEL = {"LT-101": "TK-101", "LT-102": "TK-102", "LT-103": "TK-103"}


def load(folder: Path) -> list[Row]:
    """One row per window: its label and its stored bundle."""
    sample = json.loads((folder / "sample.json").read_text())
    rows = []
    for w in sample["validation"] + sample["train_sanity"]:
        path = folder / "bundles" / f"{w['window_id']}.json.gz"
        rows.append({"w": w, "b": json.loads(gzip.open(path, "rt").read())})
    return rows


def hypotheses(row: Row) -> list[Row]:
    """Agent 5 hypotheses of a window."""
    rep = row["b"]["reports"].get("diagnostic_reasoning")
    return list(rep["result"]["hypotheses"]) if rep and rep["result"] else []


def inspection_asset(mechanism: str, asset: str | None) -> tuple[str | None, str | None]:
    """The catalog asset and action that would inspect a component, or (None, None)."""
    if mechanism in SENSOR_MECHANISMS:
        if asset in TANK_OF_LEVEL:
            return TANK_OF_LEVEL[asset], "ACT-INSP-05"
        return (asset, "ACT-INSP-07") if asset and asset.startswith("PT-") else (None, None)
    return (asset, ACTION_FOR.get(mechanism)) if asset else (None, None)


def implicated(row: Row, assets: set[str]) -> list[str]:
    """Catalog assets named by the hypotheses of a window, in rank order, without repeats."""
    found: list[str] = []
    for h in hypotheses(row):
        c = h["components"][0]
        asset, _ = inspection_asset(c["mechanism"], c["asset_id"] or c.get("tag_id"))
        if asset in assets and asset not in found:
            found.append(str(asset))
    return found


def run_agent6(row: Row, targets: list[str]) -> Row:
    """Agent 6 on the stored request with a changed target list."""
    request = copy.deepcopy(row["b"]["requests"]["inspection_planning"])
    request["input"]["target_asset_ids"] = targets
    response = InspectionPlanningAgent().run(request)
    result = response["result"]
    options = result["options"] if result else []
    return {"status": response["status"], "options": options,
            "issues": [i["code"] for i in response["issues"]]}  # fmt: skip


def summarise(runs: list[Row]) -> list[list[Any]]:
    """Statuses, options per window and feasibility of a set of Agent 6 runs."""
    status = Counter(r["status"] for r in runs)
    sizes = Counter(min(len(r["options"]), 6) for r in runs)
    feas = Counter(o["feasibility"] for r in runs for o in r["options"])
    addressed = sum(bool(o["addresses_hypothesis_ids"]) for r in runs for o in r["options"])
    codes = Counter(c for r in runs for c in r["issues"])
    return [
        ["report status", dict(status)],
        ["options per window (6 is 6 or more)", dict(sorted(sizes.items()))],
        ["options by feasibility", dict(feas)],
        ["options that address a hypothesis", addressed],
        ["issue codes", dict(codes)],
    ]


def catalog_assets(rows: list[Row]) -> set[str]:
    """Assets of the reference, as the Agent 6 request lists them."""
    request = rows[0]["b"]["requests"]["inspection_planning"]
    return {a["asset_id"] for a in request["input"]["assets"]}


def stored_run(row: Row) -> Row:
    """The Agent 6 report of the stored run in the shape of run_agent6."""
    report = row["b"]["reports"]["inspection_planning"]
    options = report["result"]["options"]
    return {"status": report["status"], "options": options,
            "issues": [i["code"] for i in report["issues"]]}  # fmt: skip


def target_tables(rows: list[Row]) -> list[str]:
    """Agent 6 today against Agent 6 on the implicated assets."""
    targets = [implicated(r, catalog_assets(rows)) for r in rows]
    sizes = Counter(min(len(t), 3) for t in targets)
    many = [run_agent6(r, t) for r, t in zip(rows, targets, strict=True)]
    single = [run_agent6(r, t[:1]) for r, t in zip(rows, targets, strict=True)]
    size_rows = [[k, v] for k, v in sorted(sizes.items())]
    size_head = ["targets per window (3 is 3 or more)", "windows"]
    head = ["measure", "value"]
    return [
        "\n### Agent 6 today (all assets as targets)",
        table(head, summarise([stored_run(r) for r in rows])),
        "\n### Targets implicated by Agent 5",
        table(size_head, size_rows),
        "\n### Agent 6 on all implicated assets",
        table(head, summarise(many)),
        "\n### Agent 6 on the first implicated asset only",
        table(head, summarise(single)),
    ]


def classify(row: Row, assets: set[str]) -> str:
    """Whether the injected fault can be followed up, and whether Agent 5 names its asset."""
    w = row["w"]
    pairs = [inspection_asset(m, a) for m in w["mechanisms"] for a in w["assets"]]
    inspectable = {a for a, act in pairs if a in assets and act}
    if w["n_components"] > 1:
        return "several injected components"
    if not inspectable:
        return "fault asset has no catalog action"
    named = implicated(row, assets)
    if not named:
        return "inspectable, Agent 5 names no catalog asset"
    if named[0] in inspectable:
        return "inspectable, Agent 5 names it first"
    if inspectable & set(named):
        return "inspectable, Agent 5 names it later"
    return "inspectable, Agent 5 names other assets only"


def action_table(rows: list[Row]) -> list[str]:
    """Windows whose fault Agent 5 names first, by the action that would inspect it."""
    assets = catalog_assets(rows)
    tally: Counter[tuple[str, str]] = Counter()
    for r in rows:
        if not r["w"]["fault"] or classify(r, assets) != "inspectable, Agent 5 names it first":
            continue
        action = inspection_asset(r["w"]["mechanisms"][0], r["w"]["assets"][0])[1] or "none"
        mode = "measured, low confidence" if action in MEASURED_IN_DEFAULT_MODE else "unavailable"
        tally[(action, mode)] += 1
    cells = [[a, m, v] for (a, m), v in sorted(tally.items())]
    return [
        "\n### The windows whose fault Agent 5 names first, by action and default-mode outcome",
        table(["action", "outcome of the default inspection model", "windows"], cells),
    ]


def classification_table(rows: list[Row]) -> list[str]:
    """Faulty windows by whether a follow-up is meaningful."""
    assets = {
        a["asset_id"] for a in rows[0]["b"]["requests"]["inspection_planning"]["input"]["assets"]
    }
    faulty = [r for r in rows if r["w"]["fault"]]
    tally: Counter[tuple[str, str]] = Counter()
    for r in faulty:
        mech = r["w"]["mechanisms"][0] if r["w"]["n_components"] == 1 else "several"
        tally[(classify(r, assets), mech)] += 1
    by_class = Counter(k for (k, _), v in tally.items() for _ in range(v))
    detail = [[k, m, v] for (k, m), v in sorted(tally.items())]
    class_rows = [[k, v] for k, v in sorted(by_class.items())]
    return [
        "\n### Faulty windows by follow-up class",
        table(["class", "windows"], class_rows),
        "\n### The same by injected mechanism",
        table(["class", "mechanism", "windows"], detail),
    ]


def fits_in_process(row: Row, duration_s: float) -> bool:
    """Whether a result could be visible by the end of the process with the shortest delays."""
    chain = APPROVAL_MIN_S + SCHEDULING_MIN_S + duration_s + RESULT_DELAY_S
    return bool(row["w"]["cutoff_s"] + chain <= HORIZON_S)


def timing_table(rows: list[Row]) -> list[str]:
    """Windows with room for an inspection inside the recorded process, per action."""
    out = []
    for action, duration in sorted(DURATION_S.items()):
        fits = [r for r in rows if fits_in_process(r, duration)]
        out.append([action, duration / 60, len(fits), sum(r["w"]["fault"] for r in fits)])
    latest = max(r["w"]["cutoff_s"] for r in rows)
    positions = dict(sorted(Counter(int(r["w"]["position"]) for r in rows).items()))
    note = (
        f"Latest cutoff in the sample {latest:.0f} s; process horizon {HORIZON_S:.0f} s; "
        f"windows per position {positions}."
    )
    head = ["action", "duration (min)", "windows that fit", "of which faulty"]
    return ["\n### Room for an inspection inside the recorded process (best-case delays)", note,
            table(head, out)]  # fmt: skip


def main() -> None:
    """Print the tables for one run folder."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, required=True, help="runner output over the sample")
    rows = load(parser.parse_args().run)
    parts = [f"windows {len(rows)}, faulty {sum(r['w']['fault'] for r in rows)}"]
    parts += target_tables(rows) + classification_table(rows) + action_table(rows)
    parts += timing_table(rows)
    sys.stdout.write("\n".join(parts) + "\n")


if __name__ == "__main__":
    main()
