"""Tables of how Agent 5 cites the Agent 2 report, and of which residuals physics expects.

Inputs: the output folder of a full-runner run over the sample (stored bundles), and the
validation split of the reference release for the residual part. Output: markdown tables on
stdout. Parts: citation by match with an injected fault, citation per residual event, the
expectation sets written from the topology and how often they hold, and a breakdown by what
Agent 2 sent. Assumptions: the per-event part and the consistency check describe a citation by
tag overlap, so they are meaningful only for bundles made with that rule. Labels are used for
grouping only. The test split is refused and every opened data file is recorded.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_runner_sample as sample_tools  # noqa: E402
from compare_agent2_runs import truth_pairs, wilson  # noqa: E402

from verum.agents.anomaly_detection.parameters import load_parameters  # noqa: E402
from verum.agents.anomaly_detection.residuals import (  # noqa: E402
    COMPUTED,
    compute_residuals,
    pump_state,
    read_window,
)
from verum.agents.diagnostic_reasoning.rules import ASSET_PRIMARY_TAGS  # noqa: E402

FAMILY = {
    "pump": "pump",
    "restriction_position_visible": "restriction",
    "restriction_obstruction": "restriction",
    "leak": "leak",
    "bias": "sensor fault",
    "drift": "sensor fault",
    "stuck": "sensor fault",
    "misroute_a": "misrouting",
}
FAMS = ["pump", "restriction", "leak", "sensor fault", "misrouting"]
KEYS = ["R1", "R2", "R3", "R4"]
SENSOR_RESIDUALS = {
    "FT-001": {"R1", "R4"},
    "FT-201": {"R1", "R2", "R3"},
    "PT-001": {"R4"},
    "PT-201": {"R2"},
    "PT-202A": {"R2", "R3"},
    "PT-202B": {"R2", "R3"},
    "PT-203": {"R3"},
}
MATCH_GROUPS = (
    "matches an injected fault",
    "does not match",
    "fault-free window (no injected fault)",
)
Row = dict[str, Any]
Counts = Counter[str]


def table(head: list[str], rows: list[list[Any]]) -> str:
    """A markdown table."""
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    return "\n".join(lines + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def share(k: int, n: int) -> str:
    """A count with its share of n."""
    return f"{k}" if n == 0 else f"{k} ({k / n:.2f})"


def load_bundles(folder: Path) -> list[Row]:
    """One row per window of the sample: its label and its stored bundle."""
    sample = json.loads((folder / "sample.json").read_text())
    rows = []
    for w in sample["validation"] + sample["train_sanity"]:
        path = folder / "bundles" / f"{w['window_id']}.json.gz"
        rows.append({"w": w, "b": json.loads(gzip.open(path, "rt").read())})
    return rows


def hyps(row: Row) -> list[Row]:
    """Agent 5 hypotheses of a window."""
    rep = row["b"]["reports"].get("diagnostic_reasoning")
    return list(rep["result"]["hypotheses"]) if rep and rep["result"] else []


def a2(row: Row) -> Row:
    """The Agent 2 report of a window."""
    report: Row = row["b"]["reports"]["anomaly_detection"]
    return report


def hyp_sets(h: Row) -> tuple[set[str], set[str]]:
    """Assets and tags of a hypothesis as Agent 5 compares them."""
    assets = {c["asset_id"] for c in h["components"] if c.get("asset_id")}
    tags = {c["tag_id"] for c in h["components"] if c.get("tag_id")}
    for asset in assets:
        tags.update(ASSET_PRIMARY_TAGS.get(asset, ()))
    return assets, tags


def matches(row: Row, h: Row) -> bool:
    """Whether the first component equals an injected mechanism and asset."""
    c = h["components"][0]
    return (c["mechanism"], c["asset_id"]) in truth_pairs(row["w"])


def match_group(row: Row, h: Row) -> str:
    """The row of the citation tables a hypothesis belongs to."""
    if not row["w"]["fault"]:
        return MATCH_GROUPS[2]
    return MATCH_GROUPS[0] if matches(row, h) else MATCH_GROUPS[1]


def cited(row: Row, h: Row) -> tuple[bool, bool]:
    """Whether the hypothesis cites the Agent 2 report as support and as conflict."""
    rid = a2(row)["report_id"]
    return rid in h["support_evidence_ids"], rid in h["conflict_evidence_ids"]


def relation_of(support: bool, conflict: bool) -> str:
    """Support, conflict, both or neither."""
    return (
        "both"
        if support and conflict
        else "support"
        if support
        else ("conflict" if conflict else "neither")
    )


def part_a(rows: list[Row]) -> str:
    """Citation of the Agent 2 report by match with an injected fault."""
    tally: Counter[tuple[str, str]] = Counter()
    for r in rows:
        for h in hyps(r):
            tally[(match_group(r, h), relation_of(*cited(r, h)))] += 1
    out = []
    for grp in MATCH_GROUPS:
        n = sum(v for (g, _), v in tally.items() if g == grp)
        kinds = ("support", "conflict", "both", "neither")
        out.append([grp, n] + [share(tally[(grp, k)], n) for k in kinds])
    return table(["hypotheses", "n", "support", "conflict", "both", "neither"], out)


def residual_events(row: Row) -> dict[str, Row]:
    """Residual events of a window by residual key."""
    out = {}
    for e in a2(row)["result"]["events"]:
        found = re.search(r"-residual-(R\d)$", e["event_id"])
        if found:
            out[found.group(1)] = e
    return out


def tag_overlap_relation(row: Row, h: Row) -> str:
    """The citation that the tag-overlap rule gives, recomputed from the events."""
    res = a2(row)["result"]
    events = res["events"]
    assets, tags = hyp_sets(h)
    if assets & {a for e in events for a in e["asset_ids"]}:
        return "support"
    if tags & {t for e in events for t in e["tag_ids"]}:
        return "support"
    return "conflict" if events and res["coverage"] == "assessed" else "neither"


def event_category(h: Row, event: Row, actual: str) -> str:
    """How one residual event relates to a hypothesis under the tag-overlap rule."""
    if hyp_sets(h)[1] & set(event["tag_ids"]):
        return "support from this event"
    return {"support": "support from another event", "conflict": "conflict"}.get(actual, "neither")


def per_event_stats(rows: list[Row]) -> tuple[dict[bool, dict[tuple[str, str], Counts]], int, int]:
    """Per residual and family counts for all hypotheses and for matching ones, and a check."""
    stats: dict[bool, dict[tuple[str, str], Counts]] = {False: defaultdict(Counter),
                                                         True: defaultdict(Counter)}  # fmt: skip
    checked = mismatches = 0
    for r in rows:
        events = residual_events(r)
        for h in hyps(r):
            actual = relation_of(*cited(r, h))
            checked += 1
            mismatches += tag_overlap_relation(r, h) != actual
            fam = FAMILY[h["components"][0]["mechanism"]]
            hit = bool(r["w"]["fault"] and matches(r, h))
            for key, event in events.items():
                for scope in [False, True] if hit else [False]:
                    cell = stats[scope][(key, fam)]
                    cell[event_category(h, event, actual)] += 1
                    cell["n"] += 1
    return stats, checked, mismatches


def event_table(stats: dict[tuple[str, str], Counts]) -> str:
    """One per-event table."""
    kinds = ("support from this event", "support from another event", "conflict", "neither")
    rows = []
    for key in KEYS:
        for fam in FAMS:
            c = stats.get((key, fam))
            if c:
                rows.append([key, fam, c["n"]] + [share(c[k], c["n"]) for k in kinds])
    head = ["residual event", "hypothesis family", "pairs", *kinds]
    return table(head, rows)


def events_per_residual(rows: list[Row]) -> str:
    """Residual events counted by residual and windows with at least one."""
    counts: Counts = Counter()
    for r in rows:
        counts.update(residual_events(r).keys())
    windows = sum(bool(residual_events(r)) for r in rows)
    return f"events {dict(counts)}; windows with at least one residual event {windows}"


def pump_letter(asset: str) -> str | None:
    """A or B when the asset sits on one pump branch."""
    for pattern in (r"P-101([AB])", r"XV-P([AB])[IO]", r"E-P([AB])\d", r"PT-202([AB])"):
        found = re.fullmatch(pattern, asset)
        if found:
            return found.group(1)
    return None


def restriction_expectation(asset: str) -> tuple[str, frozenset[str]]:
    """Expectation for a valve restriction, from where the valve sits on the line."""
    if asset.startswith("XV-R"):
        return "restriction, receipt-side valve", frozenset({"R4"})
    if asset.startswith("XV-S"):
        return "restriction, tank-outlet valve", frozenset()
    if re.fullmatch(r"XV-P[AB]I", asset):
        return "restriction, pump inlet valve", frozenset({"R2"})
    return "restriction, pump outlet valve", frozenset({"R3"})


def sensor_expectation(mech: str, tag: str) -> tuple[str, frozenset[str]]:
    """Expectation for a sensor fault: the residuals that read the tag."""
    kind = f"sensor {mech}"
    if tag in SENSOR_RESIDUALS:
        return f"{kind}, {tag}", frozenset(SENSOR_RESIDUALS[tag])
    if tag.startswith("LT-"):
        return f"{kind}, level transmitter", frozenset() if mech == "bias" else frozenset({"R1"})
    return f"{kind}, other", frozenset()


def expectation(mech: str, asset: str) -> tuple[str, frozenset[str]]:
    """Subgroup label and the residuals physics says should move, from the topology only."""
    if mech == "pump":
        return "pump head loss", frozenset({"R2"})
    if mech.startswith("restriction"):
        return restriction_expectation(asset)
    if mech == "leak":
        if asset in ("E001", "E-D2"):
            return "leak outside the mass balance", frozenset()
        return "leak between the two meters", frozenset({"R1"})
    if mech == "misroute_a":
        return "misrouting (valve forced open)", frozenset()
    return sensor_expectation(mech, asset)


def window_info(record: Any, params: Any) -> Row:
    """Computed and exceeded residuals and the pump state of one validation window."""
    signals = record.input["observations"]["signals"]
    results = compute_residuals(signals, params)
    exceeded = {
        r.key
        for r in results
        if r.state == COMPUTED and r.z is not None and r.z > params.residual_thresholds[r.key]
    }
    state, _ = pump_state(read_window(signals, params))
    return {"computed": {r.key for r in results if r.state == COMPUTED}, "fired": exceeded,
            "pump": state}  # fmt: skip


def validation_groups(release: Path) -> tuple[dict[tuple[str, str], list[Row]], list[Row]]:
    """Single-fault validation windows by family and subgroup, and the fault-free windows."""
    records, _ = sample_tools.load_split(release, "validation")
    params = load_parameters()
    groups: dict[tuple[str, str], list[Row]] = defaultdict(list)
    free: list[Row] = []
    for r in records:
        if not r.target["supervised_loss_mask"]:
            continue
        lab, info = sample_tools.labels_of(r), window_info(r, params)
        if not lab["fault"]:
            free.append(info)
        elif lab["n_components"] == 1:
            mech, asset = lab["mechanisms"][0], lab["assets"][0]
            sub, exp = expectation(mech, asset)
            letter = pump_letter(asset)
            active = True if not letter or mech == "misroute_a" else info["pump"] == letter
            groups[(FAMILY[mech], sub)].append({**info, "exp": exp, "applicable": active})
        else:
            groups[("multi-component (excluded)", "")].append(info)
    return groups, free


def baseline_table(free: list[Row]) -> str:
    """How often each residual exceeds in fault-free validation windows."""
    rows = []
    for k in KEYS:
        n = sum(k in w["computed"] for w in free)
        hit = sum(k in w["fired"] for w in free if k in w["computed"])
        rows.append([k, hit, n, wilson(hit, n)])
    anyhit = sum(bool(w["fired"]) for w in free)
    rows.append(["any residual", anyhit, len(free), wilson(anyhit, len(free))])
    head = ["fault-free validation windows", "exceed", "computable", "rate (95% interval)"]
    return table(head, rows)


def expectation_row(fam: str, sub: str, items: list[Row], free: list[Row]) -> list[Any]:
    """One row of the expectation table."""
    exp = items[0]["exp"]
    active = [w for w in items if w["applicable"]]
    comp = [w for w in active if exp <= w["computed"]]
    outside = sum(bool(w["fired"] - exp) for w in comp)
    free_comp = [w for w in free if exp <= w["computed"]]
    free_outside = sum(bool(w["fired"] - exp) for w in free_comp)
    any_text = all_text = "n/a"
    if exp:
        any_text = wilson(sum(bool(exp & w["fired"]) for w in comp), len(comp))
        every = sum(exp <= w["fired"] for w in comp)
        all_text = wilson(every, len(comp)) if len(exp) > 1 else "same"
    label = ", ".join(sorted(exp)) or "none"
    return [fam, sub, label, len(items), len(active), len(comp), any_text, all_text,
            wilson(outside, len(comp)), wilson(free_outside, len(free_comp))]  # fmt: skip


def rate_row(fam: str, sub: str, items: list[Row]) -> list[Any]:
    """One row of the per-residual rate table."""
    active = [w for w in items if w["applicable"]]
    cells = []
    for k in KEYS:
        c = [w for w in active if k in w["computed"]]
        cells.append(wilson(sum(k in w["fired"] for w in c), len(c)))
    label = ", ".join(sorted(items[0]["exp"])) or "none"
    return [fam, sub, label, len(active), *cells]


def validation_tables(release: Path) -> tuple[str, str, str]:
    """The fault-free baseline, the expectation table and the per-residual rate table."""
    groups, free = validation_groups(release)
    order = sorted(groups, key=lambda g: (FAMS.index(g[0]) if g[0] in FAMS else 9, g[1]))
    single = [g for g in order if not g[0].startswith("multi")]
    exp_head = [
        "family", "subgroup", "expected", "windows", "fault active", "expected computable",
        "at least one expected exceeds", "all expected exceed",
        "a residual outside the expected set exceeds", "same, fault-free windows",
    ]  # fmt: skip
    exp_rows = [expectation_row(f, s, groups[(f, s)], free) for f, s in single]
    rate_rows = [rate_row(f, s, groups[(f, s)]) for f, s in single]
    rate_head = ["family", "subgroup", "expected", "windows", *KEYS]
    multi = len(groups.get(("multi-component (excluded)", ""), []))
    notes = f"\n\nmulti-component windows excluded: {multi}\nfault-free n={len(free)}\n"
    notes += f"touched test split: {sample_tools.touched_test_split()}"
    return baseline_table(free), table(exp_head, exp_rows), table(rate_head, rate_rows) + notes


def events_content(events: list[Row]) -> str:
    """What Agent 2 sent in a window."""
    if any("-residual-" in e["event_id"] for e in events):
        return "residual events"
    return "quality events only" if events else "no events"


def breakdown_tables(rows: list[Row]) -> str:
    """Citation by what Agent 2 sent, and the matching hypotheses that do not cite support."""
    tally: Counter[tuple[str, str, str]] = Counter()
    listing = []
    for r in rows:
        result = a2(r)["result"]
        content = events_content(result["events"])
        for h in hyps(r):
            group = match_group(r, h).replace("matches an injected fault", "matches")
            group = group.replace(" (no injected fault)", "")
            rel = relation_of(*cited(r, h))
            tally[(group, content, rel)] += 1
            if group == "matches" and rel != "support":
                listing.append(unsupported_line(r, h, rel, content))
    out = ["\n## 4a extra: relation by what Agent 2 sent", breakdown_rows(tally)]
    out.append("\n## matching hypotheses that do not cite support")
    out += [str(item) for item in listing]
    status = Counter((a2(r)["status"], a2(r)["result"]["coverage"]) for r in rows)
    return "\n".join(out) + f"\n\nstatus/coverage: {dict(status)}"


def unsupported_line(row: Row, h: Row, rel: str, content: str) -> tuple[Any, ...]:
    """A matching hypothesis without support, with what Agent 2 sent."""
    first = h["components"][0]
    events = a2(row)["result"]["events"]
    keys = [e["event_id"].rsplit("-", 1)[-1] for e in events if "-residual-" in e["event_id"]]
    tags = sorted({t for e in events for t in e["tag_ids"]})
    return (rel, first["mechanism"], first["asset_id"], content, keys, tags,
            a2(row)["result"]["coverage"], row["w"]["set"])  # fmt: skip


def breakdown_rows(tally: Counter[tuple[str, str, str]]) -> str:
    """The table of citation by what Agent 2 sent."""
    rows = []
    for group in ("matches", "does not match", "fault-free window"):
        for content in ("residual events", "quality events only", "no events"):
            n = sum(v for (g, c, _), v in tally.items() if g == group and c == content)
            if n:
                counts = [tally[(group, content, k)] for k in ("support", "conflict", "neither")]
                rows.append([group, content, n, *counts])
    head = ["hypotheses", "Agent 2 events in the window", "n", "support", "conflict", "neither"]
    return table(head, rows)


def render(folder: Path, release: Path) -> str:
    """All tables as one markdown text."""
    sample_tools.install_audit()
    rows = load_bundles(folder)
    stats, checked, mismatches = per_event_stats(rows)
    faulty = sum(r["w"]["fault"] for r in rows)
    base, expected, rates = validation_tables(release)
    parts = [
        f"## windows {len(rows)} faulty {faulty}",
        "\n## 4a\n" + part_a(rows),
        f"\n## consistency: {checked} hypotheses, recomputed relation differs from citation "
        f"in {mismatches}",
        "\n## events: " + events_per_residual(rows),
        "\n## 4b all hypotheses\n" + event_table(stats[False]),
        "\n## 4b hypotheses matching an injected fault\n" + event_table(stats[True]),
        "\n## 4c baseline\n" + base,
        "\n## 4c expectation\n" + expected,
        "\n## 4c per residual rates\n" + rates,
        breakdown_tables(rows),
    ]
    return "\n".join(parts) + "\n"


def main() -> None:
    """Write the tables for a run folder."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, required=True, help="output folder of a runner run")
    parser.add_argument("--release", type=Path, default=sample_tools.DEFAULT_RELEASE)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    text = render(args.run, args.release)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
