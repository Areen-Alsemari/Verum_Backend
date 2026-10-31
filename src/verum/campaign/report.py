"""The summary report of a campaign: counts, rejections, gaps, correlations and healthy statistics.

The report is built from the slot records, the stored scenarios and the healthy observation files
of a campaign folder, finished or not. It counts completed episodes by stratum, family, subtype,
class, pair type, split and tier, lists the attempts that failed by reason, lists the gaps, gives
the correlation between temperature and initial level for each delivering tank, and gives the mean
and spread of each continuous tag over the healthy episodes of each family.

See D83, D87 and D151.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from verum.campaign import runner
from verum.campaign.eligibility import lineup_info
from verum.campaign.plan import CampaignConfig

Records = list[dict[str, Any]]


def table(title: str, counts: Counter[Any], total: int | None = None) -> list[str]:
    """A markdown table of a counter, with the share of the total."""
    total = sum(counts.values()) if total is None else total
    out = [f"### {title}", "", "| value | count | share |", "| --- | --- | --- |"]
    for key, n in sorted(counts.items(), key=lambda kv: str(kv[0])):
        out.append(
            f"| {key} | {n} | {100 * n / total:.1f} percent |" if total else f"| {key} | {n} | |"
        )
    return [*out, ""]


def failure_reasons(records: Records) -> Counter[str]:
    """Reason of each failed attempt: the window kinds, the gate, or an error."""
    reasons: Counter[str] = Counter()
    for r in records:
        for a in r["attempts"]:
            if a["status"] == "excluded":
                reasons["excluded: " + "+".join(a["windows"])] += 1
            elif a["status"] == "rejected":
                reasons[f"rejected: {a['gate']}"] += 1
            elif a["status"] == "error":
                reasons["error"] += 1
    return reasons


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """The correlation coefficient of two samples, or None if either has no spread."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0.0 or syy == 0.0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / math.sqrt(sxx * syy)


def level_correlations(layout: runner.Layout, done: Records) -> list[str]:
    """Correlation between temperature and the initial level of each delivering tank."""
    samples: dict[str, tuple[list[float], list[float]]] = {}
    for r in done:
        scenario = json.loads(
            (layout.evaluator / "episodes" / r["episode_id"] / "scenario.json").read_text("utf-8")
        )
        info = lineup_info(scenario["initial"]["mode"])
        for valve in sorted(info.open_valves):
            if valve.startswith("XV-S"):
                tank = f"TK-{valve[-3:]}"
                xs, ys = samples.setdefault(tank, ([], []))
                xs.append(float(scenario["temperature_c"]))
                ys.append(float(scenario["initial"]["tank_levels_m"][tank]))
    out = ["### Temperature and initial level of the delivering tank", ""]
    out += ["| tank | episodes | correlation |", "| --- | --- | --- |"]
    for tank, (xs, ys) in sorted(samples.items()):
        r_xy = pearson(xs, ys)
        out.append(f"| {tank} | {len(xs)} | {'n/a' if r_xy is None else f'{r_xy:.3f}'} |")
    return [*out, ""]


def healthy_statistics(layout: runner.Layout, done: Records) -> list[str]:
    """Mean and standard deviation of each continuous tag over the healthy episodes of a family."""
    sums: dict[tuple[str, str], list[float]] = {}
    counts: Counter[str] = Counter()
    for r in done:
        if r["faults"]:
            continue
        family = r["strata"]["family"]
        counts[family] += 1
        path = layout.agent / "episodes" / r["episode_id"] / runner.OBSERVATIONS
        for row in runner.read_observations(path):
            if row["unit"] == "bool" or row["value"] is None:
                continue
            acc = sums.setdefault((family, row["tag_id"]), [0.0, 0.0, 0.0])
            acc[0] += 1.0
            acc[1] += row["value"]
            acc[2] += row["value"] ** 2
    out = ["### Healthy tag statistics by family", ""]
    out += ["| family | tag | healthy episodes | readings | mean | standard deviation |"]
    out += ["| --- | --- | --- | --- | --- | --- |"]
    for (family, tag), (n, s1, s2) in sorted(sums.items()):
        mean = s1 / n
        sd = math.sqrt(max(s2 / n - mean * mean, 0.0))
        out.append(f"| {family} | {tag} | {counts[family]} | {int(n)} | {mean:.5g} | {sd:.4g} |")
    return [*out, ""]


def sizes(layout: runner.Layout, records: Records) -> tuple[float, float]:
    """Bytes of the agent-visible and evaluator files of the completed episodes, in GB."""
    acc = runner.accounting(layout, [r["index"] for r in records])["bytes"]
    return acc["agent_visible"] / 1e9, acc["evaluator"] / 1e9


def build(config: CampaignConfig, root: Path) -> str:
    """The report of the campaign in ``root`` as markdown text, one paragraph per line."""
    layout = runner.Layout(root)
    records = runner.load_records(layout, list(range(config.n)))
    done = [r for r in records if r["status"] == "completed"]
    gaps = [r for r in records if r["status"] == "gap"]
    attempts = sum(len(r["attempts"]) for r in records)
    agent_gb, evaluator_gb = sizes(layout, records)
    wall = sum(r.get("wall_s", 0.0) for r in records)
    accounting = layout.evaluator / "accounting.json"
    elapsed = (
        json.loads(accounting.read_text("utf-8"))["elapsed_s"] if accounting.exists() else None
    )
    out = [f"# Campaign report, seed {config.seed}", ""]
    out += [
        f"Target {config.n} slots; {len(records)} finished, {len(done)} completed, "
        f"{len(gaps)} gaps, "
        f"{attempts} attempts ({attempts / max(len(records), 1):.2f} per slot).",
        f"Size: {agent_gb:.2f} GB agent-visible and {evaluator_gb:.2f} GB evaluator.",
        f"Compute time: {wall / 3600:.1f} hours of slot time"
        + (f", {elapsed / 3600:.1f} hours of wall-clock in the last run." if elapsed else "."),
        "",
        "## Completed episodes",
        "",
    ]
    out += table("Family", Counter(r["strata"]["family"] for r in done))
    out += table("Atmosphere", Counter(r["strata"]["atmosphere"] for r in done))
    out += table("Temperature (C)", Counter(r["strata"]["temperature_c"] for r in done))
    out += table("Kind", Counter(r["kind"] for r in done))
    out += table("Subtype (faults)", Counter(s for r in done for s in r["subtypes"]))
    out += table("Class (faults)", Counter(f["class"] for r in done for f in r["faults"]))
    out += table("Pair type", Counter(r["pair_type"] for r in done if r["kind"] == "pair"))
    out += table("Split", Counter(r["split"] for r in done))
    out += table("Tier", Counter(r["tier"] for r in done))
    out += ["## Attempts that failed", ""]
    out += table("Reason", failure_reasons(records), attempts)
    out += ["## Gaps", ""]
    out += [f"{len(gaps)} slots ended in a gap after five failed attempts.", ""]
    out += table("Cells of the gaps", Counter(r["cell"] for r in gaps))
    for gap in runner.class_gaps() + runner.switch_gaps():
        out += [f"- {json.dumps(gap, sort_keys=True)}"]
    out += ["", "## Per-cell attempts", "", "| cell | slots | completed | gaps | attempts |"]
    out += ["| --- | --- | --- | --- | --- |"]
    for cell, row in runner.cell_table(records).items():
        out.append(
            f"| {cell} | {row['slots']} | {row['completed']} | {row['gaps']} | {row['attempts']} |"
        )
    out += ["", *level_correlations(layout, done), *healthy_statistics(layout, done)]
    return "\n".join(out) + "\n"
