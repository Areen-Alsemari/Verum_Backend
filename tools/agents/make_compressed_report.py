"""Write the per-window table and the summary of a compressed workflow run as Markdown.

Input: the rows file of a run of the compressed workflow tool. Output: Markdown on stdout.
The rows hold statuses and decisions only, so no label is read.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

Row = dict[str, Any]
NAMES = {
    "insufficient_evidence": "insufficient", "more_evidence_required": "more evidence",
    "assessment_available": "assessment available", "review_required": "review required",
}
KIND = {"ACT-INSP-02": "valve-check", "ACT-INSP-03": "pump-vibration"}
HEAD = (
    "| Window | Position | Cutoff (s) | Action | Target | A3 first | A6 first | A7 first | "
    "A8 first | Decision first | Second pass | A3 second | A6 second | A7 second | A8 second | "
    "Decision second | Left degraded |\n" + "|" + "---|" * 17
)


def short(value: Any) -> str:
    """The short form of a status or decision."""
    return NAMES.get(value, str(value))


def line(row: Row) -> str:
    """One table row."""
    f = row["first"]
    first = " | ".join(short(f[k]) for k in ("agent3", "agent6", "agent7", "agent8", "decision"))
    head = f"| {row['window_id']} | {row['position']} | {row['cutoff_s']:.0f} |"
    if row["second_pass"] != "run":
        return f"{head} none | none | {first} | no second pass available | | | | | | |"
    s = row["second"]
    tail = " | ".join(short(s[k]) for k in ("agent3", "agent6", "agent7", "agent8", "decision"))
    left = "yes" if row["left_degraded"] else "no"
    return f"{head} {row['action']} | {row['target']} | {first} | run | {tail} | {left} |"


def stay_lines(stay: list[Row]) -> str:
    """One bullet per group of windows that stay degraded, from the issue codes only."""
    groups = Counter(
        (
            r["action"], r["second"]["agent6"], r["second"]["decision"],
            ", ".join(r["second"]["agent8_issues"]), ", ".join(r["second"]["agent6_issues"]),
        )
        for r in stay
    )
    return "\n".join(
        f"  - {n} {KIND[a]} window(s): Agent 6 is {a6} ({i6}) and Agent 8 returns "
        f"{short(d)} with the issue {i8}."
        for (a, a6, d, i8, i6), n in sorted(groups.items())
    )


def summary(mean: list[Row], run: list[Row]) -> str:
    """The summary bullets."""
    left = [r for r in run if r["left_degraded"]]
    stay = [r for r in run if not r["left_degraded"]]
    by = Counter((r["action"], r["left_degraded"]) for r in run)
    total = {a: by[(a, True)] + by[(a, False)] for a in KIND}
    first = ", ".join(
        f"{n} {short(k)}" for k, n in sorted(Counter(r["first"]["decision"] for r in mean).items())
    )
    n_mean, n_run = len(mean), len(run)
    valve, pump = by[("ACT-INSP-02", True)], by[("ACT-INSP-03", True)]
    lines = [
        "## Summary",
        "",
        f"- Agent 3 (anomaly detection) is complete in all {n_mean} first-pass windows and all "
        f"{n_run} second-pass windows.",
        f"- First pass, all {n_mean} windows: Agent 6 degraded (preconditions unknown), Agent 7 "
        f"degraded (no inspection results), Agent 8 degraded; its decision is {first}.",
        f"- Second pass, {n_run} windows: Agent 7 is complete in all {n_run}, with every check "
        f"passed and no issue, and Agent 8 judges the proposal usable in all {n_run}.",
        f"- **{len(left)} of {n_run} leave degraded** and reach assessment available: {valve} of "
        f"the {total['ACT-INSP-02']} valve-check windows and {pump} of the "
        f"{total['ACT-INSP-03']} pump-vibration windows.",
        f"- **{len(stay)} do not leave degraded**, and in each Agent 8 itself stays degraded "
        "although Agent 7 judges the record complete and Agent 8 judges the proposal usable:",
        stay_lines(stay),
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    """Read the rows file and print the table and the summary."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=Path, required=True, help="rows file of the run")
    rows = json.loads(parser.parse_args().rows.read_text(encoding="utf-8"))
    mean = sorted(
        (r for r in rows if r["meaningful"]), key=lambda r: (r["episode_id"], r["position"])
    )
    run = [r for r in mean if r["second_pass"] == "run"]
    print("\n".join([HEAD, *(line(r) for r in mean)]))
    print()
    print(summary(mean, run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
