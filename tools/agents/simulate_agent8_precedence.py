"""Describe what Agent 8 receives and simulate candidate decision precedence rules.

Inputs: the output folder of a full-runner run over the 181-window sample (stored bundles), and
optionally the folder of the chained variant, in which the windows of an episode share an
assessment log so that persistence is known. Output: markdown tables on stdout. Nothing is
implemented: each rule is a pure function of values read from the stored requests and reports,
and rule A is checked against the decision that Agent 8 actually returned. Labels are used to
group windows only, to show how many faulty and fault-free windows each rule would flag.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent5_agent2_evidence import table  # noqa: E402

from verum.agents.evidence_verification_decision import agent as decision  # noqa: E402

Row = dict[str, Any]
STATES = ("more_evidence_required", "review_required", "inconclusive", "assessment_available")


def load(folder: Path) -> list[Row]:
    """One row per window: its label and its stored bundle."""
    sample = json.loads((folder / "sample.json").read_text())
    rows = []
    for w in sample["validation"] + sample["train_sanity"]:
        path = folder / "bundles" / f"{w['window_id']}.json.gz"
        rows.append({"w": w, "b": json.loads(gzip.open(path, "rt").read())})
    return rows


def report(row: Row, role: str) -> Row | None:
    """The report of one role for a window."""
    found: Row | None = row["b"]["reports"].get(role)
    return found


def hypotheses(row: Row) -> list[Row]:
    """Agent 5 hypotheses of a window."""
    rep = report(row, "diagnostic_reasoning")
    return list(rep["result"]["hypotheses"]) if rep and rep["result"] else []


def physical_ids(row: Row) -> set[str]:
    """Report ids of the signal-based reports: the anomaly report and the forecast."""
    return {r["report_id"] for role in ("anomaly_detection", "predictive_health")
            if (r := report(row, role))}  # fmt: skip


def hypothesis_class(row: Row, h: Row) -> str:
    """Support from a signal report and conflict from any report, as a four-way label."""
    support = bool(set(h["support_evidence_ids"]) & physical_ids(row))
    conflict = bool(h["conflict_evidence_ids"])
    return (
        "both"
        if support and conflict
        else "support"
        if support
        else ("conflict" if conflict else "neither")
    )


def anomaly_check(row: Row) -> str:
    """Outcome of the anomaly check in the diagnosis report: pass, fail or unknown."""
    rep = report(row, "diagnostic_reasoning")
    checks = rep["result"]["upstream_checks"] if rep and rep["result"] else []
    return next((c["outcome"] for c in checks if c["check_id"] == "anomaly_report"), "unknown")


def features(row: Row) -> Row:
    """Everything a precedence rule may read, taken from the stored Agent 8 request."""
    request = row["b"]["requests"]["evidence_verification_decision"]
    inputs, registry = request["input"], {r["evidence_id"]: r for r in request["evidence"]}
    checks = decision._build_evidence_checks(inputs, registry, request["context"]["as_of_s"])
    conflicts = decision._report_conflicts(inputs, registry)
    conflicts += decision._overlap_conflicts(checks, registry)
    anomaly = report(row, "anomaly_detection")
    anomaly_id = anomaly["report_id"] if anomaly else None
    hyps = hypotheses(row)
    diagnosis = inputs["diagnosis_report"]
    plan = report(row, "inspection_planning")
    options = plan["result"]["options"] if plan and plan["result"] else []
    return {
        "missing": [
            k for k in decision.REPORT_KEYS if not inputs[k] or inputs[k]["result"] is None
        ],
        "checks": len(checks),
        "unusable": any(c["usable"] is not True for c in checks),
        "conflicts": conflicts,
        "reliable_conflict": anomaly_check(row) == "fail",
        "reliable_conflict_by_id": any(anomaly_id in h["conflict_evidence_ids"] for h in hyps),
        "hard_conflict": any(not c["check_id"].startswith("diagnosis:") for c in conflicts),
        "candidates": bool(
            diagnosis and diagnosis["result"] and hyps
            and diagnosis["result"]["assessment"] == "candidates_available"
        ),
        "supported": anomaly_check(row) == "pass",
        "supported_by_id": any(set(h["support_evidence_ids"]) & physical_ids(row) for h in hyps),
        "alarming": (inputs.get("persistence") or {}).get("alarming"),
        "obtainable": any(o["feasibility"] == "eligible_for_human_review" for o in options),
        "actual": report(row, "evidence_verification_decision")["result"]["decision_state"],  # type: ignore[index]
    }  # fmt: skip


def rule_a(f: Row) -> str:
    """The current precedence: missing evidence, conflicts, inconclusive, available."""
    if f["missing"] or not f["checks"] or f["unusable"]:
        return "more_evidence_required"
    if f["conflicts"]:
        return "review_required"
    return "assessment_available" if f["candidates"] else "inconclusive"


def rule_b(f: Row) -> str:
    """A conflict from a reliable family comes before missing evidence."""
    return "review_required" if f["reliable_conflict"] else rule_a(f)


def rule_c(f: Row) -> str:
    """A persistent alarm with a supported hypothesis comes before missing evidence."""
    return "review_required" if f["alarming"] is True and f["supported"] else rule_a(f)


def rule_d(f: Row) -> str:
    """Obtainable missing evidence stays; otherwise a supported hypothesis is reviewed."""
    state = rule_a(f)
    if state != "more_evidence_required" or f["obtainable"]:
        return state
    return "review_required" if f["supported"] else state


def rule_d_signal(f: Row) -> str:
    """Rule D, with support from any signal report (the anomaly report or the forecast)."""
    state = rule_a(f)
    if state != "more_evidence_required" or f["obtainable"]:
        return state
    return "review_required" if f["supported_by_id"] else state


def rule_e1(f: Row) -> str:
    """Rule A without the empty-proposal condition: no proposals is nothing to verify."""
    if f["missing"] or f["unusable"]:
        return "more_evidence_required"
    if f["conflicts"]:
        return "review_required"
    return "assessment_available" if f["candidates"] else "inconclusive"


def rule_e2(f: Row) -> str:
    """Review on a reliable conflict, a failed record check or a persistent supported alarm."""
    flagged = f["reliable_conflict"] or f["hard_conflict"]
    flagged = flagged or (f["alarming"] is True and f["supported"])
    return "review_required" if flagged else rule_a(f)


def rule_e3(f: Row) -> str:
    """Review on a conflict or a supported hypothesis, unless persistence is known to be false."""
    if f["reliable_conflict"] or f["hard_conflict"]:
        return "review_required"
    if f["supported"] and f["alarming"] is not False:
        return "review_required"
    return rule_a(f)


def rule_e4(f: Row) -> str:
    """Rule E3, and also review whenever the persistence rule alarms."""
    return "review_required" if f["alarming"] is True else rule_e3(f)


RULES: dict[str, tuple[str, Callable[[Row], str]]] = {
    "A": ("current", rule_a),
    "B": ("reliable-family conflict first", rule_b),
    "C": ("persistent supported alarm first", rule_c),
    "D": ("obtainable evidence stays, else review if supported", rule_d),
    "D*": ("D, support from the anomaly report or the forecast", rule_d_signal),
    "E1": ("A without the empty-proposal condition", rule_e1),
    "E2": ("B or C or failed record check first", rule_e2),
    "E3": ("conflict, or supported unless persistence is false", rule_e3),
    "E4": ("E3, and review whenever persistence alarms", rule_e4),
}


def inputs_tables(rows: list[Row]) -> list[str]:
    """What Agent 8 receives: hypotheses, Agent 6 options, Agent 7 state, persistence."""
    hyp: Counter[tuple[str, str]] = Counter()
    for r in rows:
        group = "faulty" if r["w"]["fault"] else "fault-free"
        for h in hypotheses(r):
            hyp[(group, hypothesis_class(r, h))] += 1
    kinds = ("support", "conflict", "both", "neither")
    out = ["\n### Hypotheses by what they cite", table(
        ["windows", "hypotheses", *kinds],
        [[g, sum(hyp[(g, k)] for k in kinds), *[hyp[(g, k)] for k in kinds]]
         for g in ("faulty", "fault-free")],
    )]  # fmt: skip
    return out + agent6_tables(rows) + agent7_table(rows)


def agent6_tables(rows: list[Row]) -> list[str]:
    """Agent 6 options: how many, with what feasibility, and whether one is recommended."""
    sizes: Counter[int] = Counter()
    feas: Counter[str] = Counter()
    status: Counter[str] = Counter()
    recommended = 0
    for r in rows:
        rep = report(r, "inspection_planning")
        status[rep["status"] if rep else "none"] += 1
        opts = rep["result"]["options"] if rep and rep["result"] else []
        sizes[min(len(opts), 5)] += 1
        feas.update(o["feasibility"] for o in opts)
        recommended += bool(rep and rep["result"] and rep["result"]["recommended_option_id"])
    cells: list[list[Any]] = [
        ["report status", dict(status)],
        ["options per window (5 means 5 or more)", dict(sorted(sizes.items()))],
        ["options by feasibility", dict(feas)],
        ["windows with a recommended option", recommended],
    ]
    return ["\n### Agent 6", table(["measure", "value"], cells)]


def agent7_table(rows: list[Row]) -> list[str]:
    """Agent 7 state: report status, record checks and observed quality."""
    status: Counter[str] = Counter()
    checks: Counter[int] = Counter()
    quality: Counter[int] = Counter()
    for r in rows:
        rep = report(r, "inspection_quality_documentation")
        status[rep["status"] if rep else "none"] += 1
        res = rep["result"] if rep else None
        checks[len(res["record_checks"]) if res else -1] += 1
        quality[len(res["observed_quality"]) if res else -1] += 1
    return ["\n### Agent 7", table(
        ["measure", "value"],
        [["report status", dict(status)], ["record checks per window (-1 no result)", dict(checks)],
         ["observed-quality entries per window (-1 no result)", dict(quality)]],
    )]  # fmt: skip


def agent8_table(rows: list[Row]) -> list[str]:
    """What Agent 8 itself sees and returns today."""
    feats = [features(r) for r in rows]
    actual = Counter(f["actual"] for f in feats)
    kinds: Counter[str] = Counter()
    for f in feats:
        kinds.update(c["check_id"].split(":")[0] + ":" + c["check_id"].split(":")[1]
                     if c["check_id"].startswith("diagnosis") else c["check_id"].split(":")[0]
                     for c in f["conflicts"])  # fmt: skip
    persist = Counter(str(f["alarming"]) for f in feats)
    same = sum(rule_a(f) == f["actual"] for f in feats)
    agree_conflict = sum(f["reliable_conflict"] == f["reliable_conflict_by_id"] for f in feats)
    agree_support = sum(f["supported"] == f["supported_by_id"] for f in feats)
    cells = [
        ["decision states returned", dict(actual)],
        ["windows with no evidence proposal", sum(f["checks"] == 0 for f in feats)],
        ["windows with a missing report", sum(bool(f["missing"]) for f in feats)],
        ["windows with a conflict entry", sum(bool(f["conflicts"]) for f in feats)],
        ["conflict entries by source", dict(kinds)],
        ["persistence alarming in the request", dict(persist)],
        ["rule A reproduces the returned decision", f"{same} of {len(feats)}"],
        [
            "anomaly check fail equals a hypothesis citing the anomaly report as conflict",
            f"{agree_conflict} of {len(feats)}",
        ],
        [
            "anomaly check pass equals a hypothesis citing a signal report as support",
            f"{agree_support} of {len(feats)}",
        ],
    ]
    return ["\n### Agent 8 today", table(["measure", "value"], cells)]


def simulation_table(rows: list[Row], only_known: bool = False) -> list[str]:
    """Decision counts per rule and the share flagged for review, faulty against fault-free."""
    feats = [(r["w"]["fault"], features(r)) for r in rows]
    if only_known:
        feats = [(w, f) for w, f in feats if f["alarming"] is not None]
    nf = sum(w for w, _ in feats)
    nn = len(feats) - nf
    out = []
    for key, (name, rule) in RULES.items():
        states = Counter(rule(f) for _, f in feats)
        flagged_f = sum(rule(f) == "review_required" for w, f in feats if w)
        flagged_n = sum(rule(f) == "review_required" for w, f in feats if not w)
        out.append(
            [
                key,
                name,
                *[states[s] for s in STATES],
                f"{flagged_f} of {nf}",
                f"{flagged_n} of {nn}",
            ]
        )
    head = ["rule", "description", *STATES, "faulty flagged review", "fault-free flagged review"]
    return [table(head, out)]


def states_by_group(rows: list[Row], only_known: bool = False) -> list[str]:
    """Every decision state per rule for faulty and for fault-free windows."""
    feats = [(r["w"]["fault"], features(r)) for r in rows]
    if only_known:
        feats = [(w, f) for w, f in feats if f["alarming"] is not None]
    out = []
    for key, (_, rule) in RULES.items():
        for fault in (True, False):
            counts = Counter(rule(f) for w, f in feats if w == fault)
            out.append([key, "faulty" if fault else "fault-free", *[counts[s] for s in STATES]])
    return [table(["rule", "windows", *STATES], out)]


def persistence_by_group(rows: list[Row]) -> list[str]:
    """Persistence answers and supported hypotheses by label of the window."""
    tally: Counter[tuple[str, str]] = Counter()
    for r in rows:
        f = features(r)
        group = "faulty" if r["w"]["fault"] else "fault-free"
        tally[(group, f"alarming {f['alarming']}, supported {f['supported']}")] += 1
    cells = [[g, k, v] for (g, k), v in sorted(tally.items())]
    return [table(["windows", "persistence and support", "count"], cells)]


def render(default: Path, chain: Path | None) -> str:
    """All tables as one markdown text."""
    rows = load(default)
    parts = [f"windows {len(rows)}, faulty {sum(r['w']['fault'] for r in rows)}"]
    parts += agent8_table(rows) + inputs_tables(rows)
    parts += ["\n### Simulated rules, windows run one by one (persistence unknown)"]
    parts += simulation_table(rows)
    parts += ["\n### All decision states by group, windows run one by one"] + states_by_group(rows)
    if chain is not None:
        crows = load(chain)
        parts += ["\n### Chained variant: Agent 8 today", *agent8_table(crows)[1:]]
        parts += ["\n### Simulated rules, chained windows (all)"] + simulation_table(crows)
        parts += ["\n### Simulated rules, chained windows with persistence known"]
        parts += simulation_table(crows, only_known=True)
        parts += ["\n### All decision states by group, chained windows (all)"]
        parts += states_by_group(crows)
        parts += ["\n### Persistence and support by group, chained windows"]
        parts += persistence_by_group(crows)
    return "\n".join(parts) + "\n"


def main() -> None:
    """Print the tables for one or two run folders."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, required=True, help="runner output, windows alone")
    parser.add_argument("--chain", type=Path, help="runner output of the chained variant")
    args = parser.parse_args()
    sys.stdout.write(render(args.run, args.chain))


if __name__ == "__main__":
    main()
