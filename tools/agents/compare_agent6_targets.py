"""Compare two runs of the sample for the change of the Agent 6 targets of the runner.

Inputs: two output folders of `run_runner_sample.py` over the same sample, one made before the
change and one after. Output: markdown tables on stdout: Agent 6 options per window and statuses,
windows with insufficient evidence, notes of the runner, verification counts, whether the
requests and responses of the other roles are identical, what Agent 8 returned, and what Agent 6
returns now for the windows whose fault Agent 5 names first. Labels are read from the sample for
grouping only; no agent sees them.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import simulate_followup_targets as followup  # noqa: E402
from agent5_agent2_evidence import table  # noqa: E402

Row = dict[str, Any]
NAMED_FIRST = "inspectable, Agent 5 names it first"


def pair(before: Path, after: Path) -> list[tuple[Row, Row]]:
    """Window by window, the row of the first run and of the second."""
    return list(zip(followup.load(before), followup.load(after), strict=True))


def options_of(row: Row) -> list[Row]:
    """The options of the Agent 6 report of a window."""
    rep = row["b"]["reports"]["inspection_planning"]
    return list(rep["result"]["options"]) if rep and rep["result"] else []


def agent6_rows(rows: list[Row]) -> list[list[Any]]:
    """Statuses, options per window and feasibility of the Agent 6 reports."""
    status = Counter(r["b"]["reports"]["inspection_planning"]["status"] for r in rows)
    sizes = Counter(min(len(options_of(r)), 6) for r in rows)
    feas = Counter(o["feasibility"] for r in rows for o in options_of(r))
    insufficient = sum(
        r["b"]["reports"]["inspection_planning"]["status"] == "insufficient_evidence" for r in rows
    )
    total = sum(len(options_of(r)) for r in rows)
    return [["report status", dict(status)], ["windows with insufficient_evidence", insufficient],
            ["options per window (6 is 6 or more)", dict(sorted(sizes.items()))],
            ["options in all windows", total], ["options by feasibility", dict(feas)]]  # fmt: skip


def note_rows(rows: list[Row]) -> list[list[Any]]:
    """Notes of the runner that concern Agent 6, counted over the windows."""
    codes = Counter(
        n["code"] for r in rows for n in r["b"]["notes"] if n["role"] == "inspection_planning"
    )
    return [[code, count] for code, count in sorted(codes.items())]


def strip_plan(request: Row, plan_id: str) -> Row:
    """A request without the Agent 6 report and its evidence row, for the comparison."""
    changed = copy.deepcopy(request)
    changed["evidence"] = [e for e in changed["evidence"] if e["evidence_id"] != plan_id]
    changed["input"].pop("inspection_plan_report", None)
    return changed


def identity_rows(pairs: list[tuple[Row, Row]]) -> list[list[Any]]:
    """Per role, the windows whose request and response are identical in the two runs."""
    out = []
    for role in pairs[0][0]["b"]["requests"]:
        same_req = same_rep = 0
        for old, new in pairs:
            ids = [r["b"]["reports"]["inspection_planning"]["report_id"] for r in (old, new)]
            a = strip_plan(old["b"]["requests"][role], ids[0])
            b = strip_plan(new["b"]["requests"][role], ids[1])
            same_req += a == b
            same_rep += old["b"]["reports"][role] == new["b"]["reports"][role]
        out.append([role, f"{same_req} of {len(pairs)}", f"{same_rep} of {len(pairs)}"])
    return out


def decision_rows(pairs: list[tuple[Row, Row]]) -> list[list[Any]]:
    """Agent 8 decision states, conflict entries and changed decisions."""
    key = "evidence_verification_decision"
    states = [Counter(p[i]["b"]["reports"][key]["result"]["decision_state"] for p in pairs)
              for i in (0, 1)]  # fmt: skip
    same = sum(
        p[0]["b"]["reports"][key]["result"]["decision_state"]
        == p[1]["b"]["reports"][key]["result"]["decision_state"]
        for p in pairs
    )
    conflicts = [sum(len(p[i]["b"]["reports"][key]["result"]["conflicts"]) for p in pairs)
                 for i in (0, 1)]  # fmt: skip
    return [["decision states before", dict(states[0])], ["decision states after", dict(states[1])],
            ["windows with the same decision", f"{same} of {len(pairs)}"],
            ["conflict entries before, after", f"{conflicts[0]}, {conflicts[1]}"]]  # fmt: skip


def meaningful_rows(pairs: list[tuple[Row, Row]]) -> tuple[int, str]:
    """What Agent 6 returned, before and after, for the windows whose fault Agent 5 names first."""
    assets = followup.catalog_assets([p[1] for p in pairs])
    out = []
    for old, new in pairs:
        if not new["w"]["fault"] or followup.classify(new, assets) != NAMED_FIRST:
            continue
        targets = new["b"]["requests"]["inspection_planning"]["input"]["target_asset_ids"]
        opts = options_of(new)
        feas = Counter(o["feasibility"] for o in opts)
        hit = sum(bool(o["addresses_hypothesis_ids"]) for o in opts)
        out.append(
            [
                new["w"]["mechanisms"][0],
                len(targets),
                len(options_of(old)),
                len(opts),
                dict(feas),
                hit,
            ]
        )
    summary = Counter((r[0], r[1], r[2], r[3], str(r[4]), r[5]) for r in out)
    cells = [[*k, v] for k, v in sorted(summary.items())]
    head = ["injected mechanism", "targets", "options before", "options now", "feasibility now",
            "options addressing a hypothesis", "windows"]  # fmt: skip
    return len(out), table(head, cells)


def render(before: Path, after: Path) -> str:
    """All tables as one markdown text."""
    pairs = pair(before, after)
    old, new = [p[0] for p in pairs], [p[1] for p in pairs]
    runs = {k: json.loads((d / "run_rows.json").read_text()) for k, d in
            (("before", before), ("after", after))}  # fmt: skip
    verify = {k: sum(r["verify"] == "ok" for r in v) for k, v in runs.items()}
    meaningful = meaningful_rows(pairs)
    parts = [
        f"windows {len(pairs)}; verify_bundle ok before {verify['before']}, after {verify['after']}"
    ]
    parts += ["\n### Agent 6 before", table(["measure", "value"], agent6_rows(old))]
    parts += ["\n### Agent 6 after", table(["measure", "value"], agent6_rows(new))]
    parts += ["\n### Runner notes about Agent 6, after", table(["code", "windows"], note_rows(new))]
    parts += ["\n### Requests and responses identical before and after (Agent 6 report set aside)",
              table(["role", "requests", "responses"], identity_rows(pairs))]  # fmt: skip
    parts += ["\n### Agent 8", table(["measure", "value"], decision_rows(pairs))]
    parts += [f"\n### Windows whose fault Agent 5 names first: {meaningful[0]}", meaningful[1]]
    return "\n".join(parts) + "\n"


def main() -> None:
    """Print the comparison of two run folders."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    args = parser.parse_args()
    sys.stdout.write(render(args.before, args.after))


if __name__ == "__main__":
    main()
