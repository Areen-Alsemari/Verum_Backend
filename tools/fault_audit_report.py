"""Tables of the fault observability audit, from the audit runs.

Per run and tag the change is the difference of the 60 s means of the noise-free series between the
fault run and its healthy twin, judged against three sigma of the tag noise and of the healthy
variability. A fault has no observable consequence in a run if no continuous tag exceeds either
threshold and no event tag differs. Two run signatures are confusable if the cosine of the angle
between them exceeds 0.95 and both have a tag above three sigma.

See D66 to D68.
"""

from __future__ import annotations

import json
from collections import defaultdict
from itertools import combinations
from typing import Any

import numpy as np
from fault_audit import (
    CONT,
    EVENT,
    GRID,
    KINDS,
    ONSET_S,
    RESULTS,
    SIGMA,
    coordinates,
)

THRESHOLD_SIGMAS = 3.0
COSINE = 0.95
LAST_S = 300.0


def load(name: str) -> Any:
    with open(RESULTS / name, encoding="utf-8") as fh:
        return json.load(fh)


def load_runs() -> list[dict[str, Any]]:
    """The fault runs; a later partial file (``fault_audit_runs_<kinds>.json``) replaces a label."""
    runs = {r["label"]: r for r in load("fault_audit_runs.json")}
    for path in sorted(RESULTS.glob("fault_audit_runs_*.json")):
        runs.update({r["label"]: r for r in load(path.name)})
    return list(runs.values())


def healthy_sigma(baseline: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Cross-seed standard deviation of the 60 s mean, averaged over the observed window."""
    out: dict[str, dict[str, float]] = {}
    for sid in ("S0-A", "S0-B", "S0-C"):
        runs = [
            r
            for r in baseline
            if r["label"].startswith(f"{sid}:") and not r["label"].endswith("twin")
        ]
        out[sid] = {}
        for tag in CONT:
            stack = np.array([r["series"][tag] for r in runs if r["rejected"] is None])
            out[sid][tag] = float(np.nanmean(np.nanstd(stack, axis=0, ddof=1)))
    return out


def tag_metrics(
    tag: str,
    fault: np.ndarray,
    twin: np.ndarray,
    truth_f: np.ndarray,
    truth_t: np.ndarray,
    sh: float,
) -> dict[str, Any]:
    d = fault - twin
    on = GRID >= ONSET_S
    big = int(np.nanargmax(np.abs(np.where(on, d, 0.0))))
    # A healthy variability below a thousandth of the noise is numerical zero (a quantity the
    # demand process does not touch): only the noise limits the detection there.
    sh_eff = sh if sh >= 1e-3 * SIGMA[tag] else 0.0
    thr_n = THRESHOLD_SIGMAS * SIGMA[tag]
    thr_h = max(thr_n, THRESHOLD_SIGMAS * sh_eff)  # above both thresholds

    def first(thr: float) -> float | None:
        hit = np.nonzero(on & (np.abs(d) > thr))[0]
        return float(GRID[hit[0]] - ONSET_S) if hit.size else None

    last = GRID >= GRID[-1] - LAST_S
    return {
        "truth_max": float(np.max(np.abs(truth_f - truth_t)[on])),
        "sampled_max": float(abs(d[big])),
        "sigma_noise_units": float(abs(d[big]) / SIGMA[tag]),
        "sigma_health_units": float(abs(d[big]) / sh_eff) if sh_eff > 0 else None,
        "t_noise_s": first(thr_n),
        "t_health_s": first(thr_h),
        "sign": int(np.sign(d[big])) if abs(d[big]) > 0 else 0,
        "end_change": float(np.nanmean(d[last])),
        "over_noise": bool(abs(d[big]) > thr_n),
        "over_health": bool(abs(d[big]) > thr_h),
    }


def analyse(runs: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sh = healthy_sigma(baseline)
    twins = {r["label"].split(":")[0]: r for r in baseline + runs if r["label"].endswith("twin")}
    out = []
    cases: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []
    for r in runs:
        if r["label"].endswith("twin"):
            cases += [
                (k, {"series": v, "truth": r["truth"], "rejected": None}, None)
                for k, v in r.get("sensor_cases", {}).items()
            ]
        else:
            cases.append((r["label"], r, None))
    for label, run, _ in cases:
        kind, sid, asset, i = label.split("|")
        entry: dict[str, Any] = {
            "kind": kind, "scenario": sid, "asset": asset, "index": int(i),
            "coordinate": coordinates(kind)[int(i)],
        }  # fmt: skip
        if run.get("rejected"):
            entry["rejected"] = {k: run["rejected"][k] for k in ("gate", "t_sim_s", "detail")}
            out.append(entry)
            continue
        twin = twins[sid]
        tags = {}
        for tag in CONT:
            tags[tag] = tag_metrics(
                tag, np.array(run["series"][tag]), np.array(twin["series"][tag]),
                np.array(run["truth"][tag]), np.array(twin["truth"][tag]), sh[sid][tag],
            )  # fmt: skip
        events = (
            [t for t in EVENT if list(run.get("series", {}).get(t, [])) != list(twin["series"][t])]
            if kind not in ("bias", "drift", "stuck")
            else []
        )
        entry.update(tags=tags, events_changed=events, windows=run.get("windows", []))
        entry["detect_noise"] = [t for t, m in tags.items() if m["over_noise"]]
        entry["detect_health"] = [t for t, m in tags.items() if m["over_health"]]
        entry["consequence"] = bool(entry["detect_noise"] or entry["detect_health"] or events)
        entry["signature"] = [tags[t]["end_change"] / SIGMA[t] for t in CONT]
        out.append(entry)
    return out


def cell(entry: dict[str, Any] | None) -> str:
    if entry is None:
        return "?"
    if "rejected" in entry:
        return "R"
    if entry["detect_health"]:
        return "H"
    if entry["detect_noise"]:
        return "n"
    return "e" if entry["events_changed"] else "-"


def cosine(a: list[float], b: list[float]) -> float:
    x, y = np.array(a), np.array(b)
    return float(x @ y / (np.linalg.norm(x) * np.linalg.norm(y)))


def has_signal(e: dict[str, Any]) -> bool:
    return max(abs(v) for v in e["signature"]) > THRESHOLD_SIGMAS


def best_index(entries: list[dict[str, Any]], which: str) -> dict[str, Any] | None:
    realised = [e for e in sorted(entries, key=lambda e: e["index"]) if "rejected" not in e]
    if not realised:
        return None
    return realised[-1] if which == "largest" else realised[len(realised) // 2]


def confusable(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for e in entries:
        groups[(e["scenario"], e["kind"], e["asset"])].append(e)
    pairs: list[dict[str, Any]] = []
    for which in ("largest", "middle"):
        chosen = {k: best_index(v, which) for k, v in groups.items()}
        for (ka, a), (kb, b) in combinations(sorted((k, v) for k, v in chosen.items() if v), 2):
            if ka[0] != kb[0] or not (has_signal(a) and has_signal(b)):
                continue
            c = cosine(a["signature"], b["signature"])
            if c > COSINE:
                pairs.append(
                    {
                        "scenario": ka[0],
                        "a": ka[1:],
                        "b": kb[1:],
                        "cosine": round(c, 3),
                        "at": which,
                    }
                )
    return pairs


def best_cosine(
    entries: list[dict[str, Any]],
    kinds_a: set[str],
    kinds_b: set[str],
    tags: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Largest cosine between any realised run of one group and any of another, per scenario."""
    out = []
    for sid in ("S0-A", "S0-B", "S0-C"):
        a = [
            e
            for e in entries
            if e["scenario"] == sid
            and e["kind"] in kinds_a
            and "rejected" not in e
            and has_signal(e)
        ]
        b = [
            e for e in entries
            if e["scenario"] == sid
            and e["kind"] in kinds_b
            and "rejected" not in e
            and has_signal(e)
            and (tags is None or e["asset"] in tags)
        ]  # fmt: skip
        best = max(
            ((cosine(x["signature"], y["signature"]), x, y) for x in a for y in b if x is not y),
            default=None,
            key=lambda z: z[0],
        )
        if best:
            out.append(
                {
                    "scenario": sid,
                    "cosine": round(best[0], 3),
                    "a": [best[1]["kind"], best[1]["asset"], best[1]["index"]],
                    "b": [best[2]["kind"], best[2]["asset"], best[2]["index"]],
                }
            )
    return out


def table(entries: list[dict[str, Any]]) -> list[str]:
    groups: dict[tuple[str, str, str], dict[int, dict[str, Any]]] = defaultdict(dict)
    for e in entries:
        groups[(e["kind"], e["scenario"], e["asset"])][e["index"]] = e
    lines = [
        "| fault | scenario | asset | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | smallest > noise "
        "| smallest > healthy | first detection at the largest realised (s, noise / healthy) "
        "| tags carrying the signal (largest realised) |",
        "| " + " | ".join(["---"] * 15) + " |",
    ]
    for kind in KINDS:
        for key in sorted(k for k in groups if k[0] == kind):
            g = groups[key]
            marks = [cell(g.get(i)) if i < len(coordinates(kind)) else "" for i in range(8)]
            coords = coordinates(kind)
            first_n = next(
                (coords[i] for i in range(len(coords)) if i in g and g[i].get("detect_noise")), None
            )
            first_h = next(
                (coords[i] for i in range(len(coords)) if i in g and g[i].get("detect_health")),
                None,
            )
            top = best_index(list(g.values()), "largest")
            carry = ""
            if top is not None:
                ranked = sorted(top["tags"].items(), key=lambda kv: -kv[1]["sigma_noise_units"])
                carry = ", ".join(
                    f"{t} ({m['sigma_noise_units']:.0f})"
                    for t, m in ranked[:4]
                    if m["sigma_noise_units"] > THRESHOLD_SIGMAS
                )
                if top["events_changed"]:
                    carry += (", " if carry else "") + "events: " + " ".join(top["events_changed"])
            f = lambda v: "-" if v is None else f"{v:.3g}"  # noqa: E731
            lines.append(
                f"| {kind} | {key[1]} | {key[2]} | "
                + " | ".join(marks + [""] * (8 - len(marks)))
                + f" | {f(first_n)} | {f(first_h)} | {first_times(top)} | {carry or '-'} |"
            )
    return lines


UNITS = {
    "leak": "area m2", "restriction": "closure fraction", "pump": "head loss fraction",
    "bias": "fraction of span", "drift": "fraction of span per hour",
    "stuck": "-", "misroute_a": "-", "misroute_b": "stuck opening",
}  # fmt: skip


def smallest(flag: str, group: list[dict[str, Any]]) -> float | None:
    """Smallest severity coordinate whose run exceeds the threshold; 0 for a fault without one."""
    hits = [e["coordinate"] or 0.0 for e in group if "rejected" not in e and e[flag]]
    return min(hits) if hits else None


def span(flag: str, per: dict[tuple[str, str], list[dict[str, Any]]], plain: bool) -> str:
    found = [x for g in per.values() if (x := smallest(flag, g)) is not None]
    if not found:
        return "none"
    if plain:  # a fault without a severity range: say how many assets show it
        return f"{len(found)} of {len(per)} assets"
    return f"{min(found):.3g} to {max(found):.3g} ({len(found)} of {len(per)} assets)"


def fastest(per: dict[tuple[str, str], list[dict[str, Any]]]) -> str:
    times = []
    for g in per.values():
        top = best_index(g, "largest")
        hit = (
            [m["t_noise_s"] for m in top["tags"].values() if m["t_noise_s"] is not None]
            if top
            else []
        )
        if hit:
            times.append(min(hit))
    return f"{min(times):.0f} to {max(times):.0f}" if times else "-"


def summary(entries: list[dict[str, Any]]) -> list[str]:
    """One row per fault type: the range over the assets of the smallest detectable severity."""
    rows = [
        "| fault | severity coordinate | smallest above 3 sigma of the noise | smallest above the "
        "healthy variability as well | first detection at the largest severity (s) "
        "| rejected by a gate | no consequence |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for kind in KINDS:
        mine = [e for e in entries if e["kind"] == kind]
        per: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for e in mine:
            per[(e["scenario"], e["asset"])].append(e)
        plain = coordinates(kind) == [None]
        rejected = sum(1 for e in mine if "rejected" in e)
        none = sum(1 for g in per.values() if not any(e.get("consequence") for e in g))
        rows.append(
            f"| {kind} | {UNITS[kind]} | {span('detect_noise', per, plain)} "
            f"| {span('detect_health', per, plain)} | {fastest(per)} "
            f"| {rejected} of {len(mine)} runs | {none} of {len(per)} assets |"
        )
    return rows


def first_times(top: dict[str, Any] | None) -> str:
    """Earliest time after the onset at which any tag exceeds each threshold."""
    if top is None:
        return "-"
    tn = [m["t_noise_s"] for m in top["tags"].values() if m["t_noise_s"] is not None]
    th = [m["t_health_s"] for m in top["tags"].values() if m["t_health_s"] is not None]
    return f"{min(tn):.0f} / {min(th):.0f}" if tn and th else (f"{min(tn):.0f} / -" if tn else "-")


def named(entries: list[dict[str, Any]]) -> list[str]:
    rows = ["| comparison | scenario | cosine | runs |", "| --- | --- | --- | --- |"]
    pairs = (
        (
            "leak against flow-meter bias or drift",
            {"leak"},
            {"bias", "drift"},
            {"FT-001", "FT-201"},
        ),
        ("valve restriction against pump head degradation", {"restriction"}, {"pump"}, None),
        ("leak against valve restriction", {"leak"}, {"restriction"}, None),
    )
    for label, a, b, tags in pairs:
        for r in best_cosine(entries, a, b, tags):
            rows.append(f"| {label} | {r['scenario']} | {r['cosine']} | {r['a']} and {r['b']} |")
    return rows


def main() -> None:
    entries = analyse(load_runs(), load("fault_audit_baseline.json"))
    baseline = load("fault_audit_baseline.json")
    sh = healthy_sigma(baseline)
    lines = ["# Fault observability audit", ""]
    lines += [
        "R: rejected by a gate (D66); -: no tag above either threshold and no event change; "
        "e: only an event tag changes; n: above 3 sigma of the noise; H: above 3 sigma of the "
        "noise and of the healthy variability.",
        "",
    ]
    lines += [
        "## Healthy variability (cross-seed std of the 60 s mean, demand process on)",
        "",
    ]
    lines += ["| tag | noise sigma | S0-A | S0-C | S0-B |", "| --- | --- | --- | --- | --- |"]
    for t in CONT:
        lines.append(
            f"| {t} | {SIGMA[t]:.4g} | {sh['S0-A'][t]:.3g} | {sh['S0-C'][t]:.3g} "
            f"| {sh['S0-B'][t]:.3g} |"
        )
    lines += [
        "",
        "## Per fault, scenario and asset (severities 1 to 8 as in the grid of the decisions)",
        "",
    ] + table(entries)
    no_effect = sorted(
        {(e["kind"], e["scenario"], e["asset"]) for e in entries}
        - {(e["kind"], e["scenario"], e["asset"]) for e in entries if e.get("consequence")}
    )
    lines += ["", "## Faults without an observable consequence at any realised severity", ""]
    lines += [f"- {k} on {a} in {s}" for k, s, a in no_effect] or ["- none"]
    rej = defaultdict(list)
    for e in entries:
        if "rejected" in e:
            rej[(e["kind"], e["scenario"], e["asset"])].append(
                f"{e['index'] + 1}:{e['rejected']['gate']}"
            )
    lines += ["", "## Rejected candidates (severity index: gate)", ""] + [
        f"- {k[0]} {k[2]} in {k[1]}: {' '.join(v)}" for k, v in sorted(rej.items())
    ]
    pairs = confusable(entries)
    lines += ["", "## Confusable pairs (cosine of the signatures above 0.95)", ""]
    lines += [
        f"- {p['scenario']}: {p['a']} and {p['b']}, cosine {p['cosine']} ({p['at']} severity)"
        for p in pairs
    ] or ["- none"]
    lines += ["", "## Summary by fault type", ""] + summary(entries)
    lines += ["", "## Named comparisons (best cosine over all realised runs)", ""] + named(entries)
    leaks = [e for e in entries if e["kind"] == "leak" and e.get("detect_noise")]
    lines += [
        "",
        "## Leak: smallest area above 3 sigma of the noise, and at other Cd (area x 0.62 / Cd)",
        "",
    ]
    lines += [
        "| scenario | asset | A at Cd 0.62 (m2) | at Cd 0.5 | at Cd 0.8 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for sid in ("S0-A", "S0-C", "S0-B"):
        for asset in sorted({e["asset"] for e in leaks if e["scenario"] == sid}):
            a = min(e["coordinate"] for e in leaks if e["scenario"] == sid and e["asset"] == asset)
            lines.append(
                f"| {sid} | {asset} | {a:.3g} | {a * 0.62 / 0.5:.3g} | {a * 0.62 / 0.8:.3g} |"
            )
    (RESULTS / "fault_audit_summary.md").write_text(
        "\n".join(summary(entries)) + "\n", encoding="utf-8"
    )
    (RESULTS / "fault_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    slim = [{k: v for k, v in e.items() if k != "signature"} for e in entries]
    (RESULTS / "fault_audit.json").write_text(
        json.dumps({"runs": slim, "confusable": pairs}), encoding="utf-8"
    )
    print("\n".join(lines[:60]))


if __name__ == "__main__":
    main()
