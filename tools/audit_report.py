"""Tables of the agent-side audit and the severity class boundaries.

It evaluates every cell of the fault grid and every held-out healthy run against the calibrated
thresholds, then writes the comparison with the earlier methods, the class fractions, the
confusable pairs, the smallest detectable severity and the time to detect for each window length,
and, with the class option, the severity class boundaries as parameter records.

See D77 to D81.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from itertools import combinations
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import numpy as np
from audit_cells import Cell, activity_of, evaluate, parse
from audit_collect import HELD_OUT_RUNS, PROFILES
from audit_features import LAYOUT, WINDOWS_S, design
from fault_audit import ASSETS, SENSOR_KINDS, coordinates
from fault_audit_v2 import FAMILIES, fault_jobs

from verum.evaluation.agent_audit import crossing, klass

RESULTS = Path("local/results")
INVISIBLE, CLEAR = 1.0, 3.0
COSINE = 0.95
CLASS_FILE = Path("config/severity_classes.json")


def labels() -> list[str]:
    out = [j["label"] for p in PROFILES for j in fault_jobs(p)]
    for profile in PROFILES:
        for fam in ("A", "B", "C"):
            for kind in SENSOR_KINDS:
                for asset in ASSETS[kind][FAMILIES[fam][0]]:
                    out += [
                        f"case|{kind}|{fam}|{asset}|{i}|{profile}"
                        for i in range(len(coordinates(kind)))
                    ]
    return out


def evaluate_one(args: tuple[str, dict[str, Any], float]) -> dict[str, Any]:
    return evaluate(*args)


def evaluate_all(th: dict[str, Any]) -> list[dict[str, Any]]:
    """Fault cells and held-out healthy runs, each with its margins."""
    jobs: list[tuple[str, dict[str, Any], float]] = []
    for label in labels():
        cell = parse(label)
        assert cell is not None
        entry = th[f"{cell.profile}|{cell.family}"]
        jobs.append((label, entry["thresholds"], entry["false_alarm"]["scale"]))
    for profile in PROFILES:
        for fam in LAYOUT:
            entry = th[f"{profile}|{fam}"]
            scale = entry["false_alarm"]["scale"]
            held = [f"held|{fam}|{profile}|{k}" for k in range(HELD_OUT_RUNS)]
            jobs += [(label, entry["thresholds"], scale) for label in held]
    with Pool(9) as pool:
        return pool.map(evaluate_one, jobs, chunksize=4)


def coordinate_of(kind: str, index: int) -> float | None:
    return None if kind in ("misroute_a", "stuck") else coordinates(kind)[index]


def asset_class(kind: str, asset: str) -> str:
    if kind == "leak":
        for prefix, name in (("E-S", "suction"), ("E-P", "pump_branch"), ("E-D", "discharge")):
            if asset.startswith(prefix):
                return name
        return "receipt"
    if kind in ("restriction", "misroute_a", "misroute_b"):
        return (
            "pump_branch"
            if asset.startswith("XV-P")
            else "tank_outlet"
            if asset.startswith("XV-S")
            else "tank_inlet"
        )
    if kind == "pump":
        return "pump"
    return {"FT": "flow", "PT": "pressure", "LT": "level"}[asset[:2]]


def annotate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    modes = design()[1]
    rows = []
    for r in results:
        cell = parse(r["label"])
        if cell is None:
            p = r["label"].split("|")
            rows.append({**r, "healthy": True, "profile": p[2], "family": p[1], "fault": "healthy"})
            continue
        rows.append(
            {
                **r,
                "healthy": False,
                "profile": cell.profile,
                "family": cell.family,
                "fault": cell.fault,
                "kind": cell.kind,
                "asset": cell.asset,
                "index": cell.index,
                "coordinate": coordinate_of(cell.kind, cell.index),
                "activity": activity_of(cell, modes),
                "aclass": asset_class(cell.kind, cell.asset),
            }
        )
    return rows


def active(rows: list[dict[str, Any]], profile: str) -> list[dict[str, Any]]:
    return [
        r
        for r in rows
        if not r["healthy"] and r["profile"] == profile and r["activity"] == "active"
    ]


def share(rows: list[dict[str, Any]], fault: str, key: str, level: float) -> str:
    cells = [r for r in rows if r["fault"] == fault and not r["rejected"]]
    return f"{sum(1 for r in cells if r[key] >= level)}/{len(cells)}"


def comparison(rows: list[dict[str, Any]]) -> list[str]:
    """The twin method, the held margin, the unscaled calibrated margin and the scaled one."""
    previous = json.loads((RESULTS / "fault_audit_v2.json").read_text(encoding="utf-8"))["rows"]
    unscaled = json.loads((RESULTS / "phase6c" / "audit_rows.json").read_text(encoding="utf-8"))
    twin = json.loads((RESULTS / "fault_audit.json").read_text(encoding="utf-8"))["runs"]
    head = "| fault | twin | v1: held margin | unscaled | scaled m>=1 | scaled m>=3 "
    lines = [
        head + "| v2: held margin | unscaled | scaled m>=1 | scaled m>=3 |",
        "| --- |" + " --- |" * 9,
    ]
    for f in sorted({r["fault"] for r in rows if not r["healthy"]}):
        base = "restriction" if f.startswith("restriction") else f
        t = [r for r in twin if r["kind"] == base and not r.get("rejected")]
        if f == "restriction_obstruction":
            tw = "-"
        else:
            keep = [r for r in t if activity_ok(r, f)]
            tw = f"{sum(bool(r['consequence']) for r in keep)}/{len(keep)}"
        cells = [tw]
        for profile in PROFILES:
            old = [r for r in previous if selected(r, profile, f)]
            mid = [r for r in unscaled if selected(r, profile, f)]
            new = active(rows, profile)
            cells += [
                f"{sum(r['held_margin'] >= 1 for r in old)}/{len(old)}",
                f"{sum(r['margin'] >= 1 for r in mid)}/{len(mid)}",
                share(new, f, "margin", 1.0),
                share(new, f, "margin", CLEAR),
            ]
        lines.append(f"| {f} | " + " | ".join(cells) + " |")
    return lines


def selected(row: dict[str, Any], profile: str, fault: str) -> bool:
    """An active, completed fault cell of a profile in an earlier result file."""
    return (
        not row.get("healthy")
        and row["profile"] == profile
        and row["fault"] == fault
        and row["activity"] == "active"
        and not row["rejected"]
    )


def activity_ok(twin_row: dict[str, Any], fault: str) -> bool:
    cell = Cell(twin_row["kind"], fault, twin_row["scenario"][-1], twin_row["asset"], 0, "v1", "")
    return activity_of(cell, design()[1]) == "active"


def healthy_floor(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| group | profile | runs | scaled m>=1 | scaled m>=3 | held>=1 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for profile in PROFILES:
        for name, sel in (
            (
                "held-out healthy",
                [r for r in rows if r["healthy"] and r["profile"] == profile and not r["rejected"]],
            ),
            (
                "latent cells",
                [
                    r
                    for r in rows
                    if not r["healthy"]
                    and r["profile"] == profile
                    and r["activity"] == "latent"
                    and not r["rejected"]
                ],
            ),
        ):
            m = np.array([r["margin"] for r in sel])
            h = np.array([r["held"] for r in sel])
            lines.append(
                f"| {name} | {profile} | {len(sel)} | {(m >= 1).sum()} | {(m >= 3).sum()} | "
                f"{(h >= 1).sum()} |"
            )
    return lines


def class_fractions(rows: list[dict[str, Any]], profile: str, key: str = "margin") -> list[str]:
    lines = [
        "| fault | active | latent | rejected | invisible | marginal | clear | balanced share |",
        "| --- |" + " --- |" * 7,
    ]
    for f in sorted({r["fault"] for r in rows if not r["healthy"]}):
        cells = [
            r for r in rows if not r["healthy"] and r["profile"] == profile and r["fault"] == f
        ]
        act = [r for r in cells if r["activity"] == "active" and not r["rejected"]]
        n = len(act)
        frac = {
            c: sum(klass(r[key]) == c for r in act) / n for c in ("invisible", "marginal", "clear")
        }
        populated = sum(1 for v in frac.values() if v > 0)
        lines.append(
            f"| {f} | {n} | {sum(r['activity'] == 'latent' for r in cells)} | "
            f"{sum(bool(r['rejected']) for r in cells)} | {frac['invisible']:.2f} | "
            f"{frac['marginal']:.2f} | "
            f"{frac['clear']:.2f} | {1 / populated:.2f} each of {populated} |"
        )
    return lines


def confusables(rows: list[dict[str, Any]], profile: str, minimum: float) -> list[str]:
    live = [r for r in active(rows, profile) if not r["rejected"] and r["margin"] >= minimum]
    tally: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for a, b in combinations(live, 2):
        if a["fault"] == b["fault"] or a["family"] != b["family"]:
            continue
        names = sorted(set(a["signature"]) & set(b["signature"]))
        va, vb = (
            np.array([a["signature"][n] for n in names]),
            np.array([b["signature"][n] for n in names]),
        )
        na, nb = np.linalg.norm(va), np.linalg.norm(vb)
        if na == 0 or nb == 0 or float(va @ vb) / (na * nb) <= COSINE:
            continue
        key = tuple(sorted((a["fault"], b["fault"])))
        tally[key][0] += 1  # type: ignore[index]
        tally[key][1] += int(a["changed_tags"] != b["changed_tags"])  # type: ignore[index]
    lines = [
        "| pair | confusable cell pairs | separated by a contact or run status |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {x} / {y} | {n} | {s} |" for (x, y), (n, s) in sorted(tally.items())]
    return lines


def metric(row: dict[str, Any], key: str) -> float:
    """The scaled margin of a cell: the best over window lengths, or that of one length."""
    return float(row["margin"] if key == "margin" else row["by_length"][key])


def curves(
    rows: list[dict[str, Any]], key: str
) -> dict[tuple[str, str], dict[str, list[tuple[float, float]]]]:
    """(fault, asset class) -> asset -> (severity coordinate, margin), most severe last."""
    out: dict[tuple[str, str], dict[str, list[tuple[float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in rows:
        if r["healthy"] or r["profile"] != "v2" or r["activity"] != "active" or r["rejected"]:
            continue
        if r["coordinate"] is None:
            continue
        sign = -1.0 if r["kind"] == "misroute_b" else 1.0
        value = metric(r, key)
        out[(r["fault"], r["aclass"])][f"{r['family']}|{r['asset']}"].append(
            (sign * r["coordinate"], value)
        )
    return {k: {a: sorted(v) for a, v in d.items()} for k, d in out.items()}


def smallest_detectable(rows: list[dict[str, Any]]) -> list[str]:
    """Smallest severity with a scaled margin of 1, per window length and over the best length."""
    keys = [*(str(w) for w in WINDOWS_S), "margin"]
    lines = [
        "| fault | asset class | assets | 60 s | 300 s | 900 s | best length |",
        "| --- |" + " --- |" * 6,
    ]
    per = {k: curves(rows, k) for k in keys}
    for (fault, aclass), assets in sorted(per["margin"].items()):
        cells = []
        for k in keys:
            found = [crossing(per[k][(fault, aclass)][a], 1.0) for a in assets]
            ok = [abs(x) for x in found if x is not None]
            cells.append(
                f"{np.median(ok):.3g} ({len(ok)}/{len(found)})" if ok else f"none (0/{len(found)})"
            )
        lines.append(f"| {fault} | {aclass} | {len(assets)} | " + " | ".join(cells) + " |")
    return lines


def detect_times(rows: list[dict[str, Any]], profile: str) -> list[str]:
    lines = [
        "| fault | detected cells | median s: 60 | 300 | 900 | most severe cells: 60 | 300 | 900 |",
        "| --- |" + " --- |" * 7,
    ]
    for f in sorted({r["fault"] for r in rows if not r["healthy"]}):
        cells = [
            r
            for r in active(rows, profile)
            if r["fault"] == f and not r["rejected"] and r["margin"] >= 1.0
        ]
        if not cells:
            continue
        top = [r for r in cells if r["index"] == max(c["index"] for c in cells)]

        def med(sel: list[dict[str, Any]], length: int) -> str:
            v = [r["detect"][str(length)] for r in sel if r["detect"][str(length)] is not None]
            return f"{np.median(v):.0f} ({len(v)})" if v else "-"

        lines.append(
            f"| {f} | {len(cells)} | "
            + " | ".join(med(cells, w) for w in WINDOWS_S)
            + " | "
            + " | ".join(med(top, w) for w in WINDOWS_S)
            + " |"
        )
    return lines


# --- severity classes ----------
def diagnose(points: list[tuple[float, float]], level: float) -> str:
    peak = max(m for _, m in points)
    drops = sum(1 for (_, a), (_, b) in zip(points, points[1:], strict=False) if b < 0.75 * a)
    if drops:
        return (
            f"the margin is not monotone ({drops} falls of more than a quarter); largest {peak:.2f}"
        )
    if peak < 0.9 * level:
        return f"the range ends below the level: largest margin {peak:.2f} of {level:g}"
    return f"borderline: largest margin {peak:.2f} of {level:g}"


def class_file(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Boundary records, the marks of boundaries at the range start (D89c), and notes."""
    params: dict[str, Any] = {}
    marks: dict[str, Any] = {}
    notes: list[str] = []
    for (fault, aclass), assets in sorted(curves(rows, "margin").items()):
        for name, level in (("marginal", INVISIBLE), ("clear", CLEAR)):
            found = {a: crossing(p, level) for a, p in assets.items()}
            values = [abs(x) for x in found.values() if x is not None]
            key = f"{fault}/{aclass}/{name}_from"
            if len(values) == len(found):
                value = float(np.median(values))
                params[key] = {
                    "value": value, "unit": "1", "status": "provisional",
                    "evidence_tag": "SIM", "provenance_id": "VERUM-DD-D89-v1.0",
                }  # fmt: skip
                start = min(abs(p[0][0]) for p in assets.values())
                if math.isclose(value, start, rel_tol=1e-9):
                    at_start = min(p[0][1] for p in assets.values())
                    marks[key] = {"floor": at_start < level, "smallest_margin_at_start": at_start}
                continue
            missing = [a for a, x in found.items() if x is None]
            reasons = "; ".join(diagnose(assets[a], level) for a in missing[:1])
            reason = (
                f"{len(missing)} of {len(found)} assets do not reach {level:g} inside the range: "
                f"{reasons}"
            )
            params[key] = {
                "value": None, "unit": "1", "status": "unresolved", "evidence_tag": "OPEN",
                "unresolved_reason": reason,
            }  # fmt: skip
            notes.append(f"- `{key}`: {reason}")
    doc = {
        "schema_version": "1.1.0",
        "description": "Severity class boundaries of the agent-side audit under profile v2 (D78, "
        "D89): the severity coordinate from which the scaled margin, best over the window lengths "
        "and worst over the design draws, reaches 1 (marginal) and 3 (clear); the median over the "
        "assets of the class. A boundary that any asset of the class does not reach inside the "
        "range is unresolved. A boundary equal to the lower end of the range appears in "
        "boundary_marks (D89c): floor true means that the class begins at or below the range "
        "start and the value is not a detection threshold; floor false means that the scaled "
        "margin reaches the level at the start for every asset, with the smallest margin there.",
        "source": "tools/audit_report.py",
        "parameters": params,
        "boundary_marks": marks,
    }
    return doc, notes


def main(write_classes: bool) -> None:
    th = json.loads((RESULTS / "audit_calibration.json").read_text(encoding="utf-8"))
    cache = RESULTS / "audit_cells.json"
    if cache.exists():
        results = json.loads(cache.read_text(encoding="utf-8"))
    else:
        results = evaluate_all(th)
        cache.write_text(json.dumps(results), encoding="utf-8")
    rows = annotate(results)
    out = ["# Agent-side audit, scaled margins", "", "## Comparison (active cells)", ""]
    out += comparison(rows) + ["", "## Healthy floor", ""] + healthy_floor(rows)
    for profile in PROFILES:
        out += ["", f"## Class fractions, profile {profile}", ""] + class_fractions(rows, profile)
    for profile in PROFILES:
        for minimum in (3.0, 1.0):
            title = f"## Confusable pairs, profile {profile}, scaled margin at least {minimum:g}"
            out += ["", title, ""] + confusables(rows, profile, minimum)
        out += ["", f"## Time to detect (s), profile {profile}", ""] + detect_times(rows, profile)
    title = "## Smallest detectable severity, profile v2 (median over assets; assets reaching 1)"
    out += ["", title, ""] + smallest_detectable(rows)
    doc, notes = class_file(rows)
    out += ["", "## Unresolved boundaries", ""] + notes
    out += ["", "## Boundaries at the range start", ""]
    out += [f"- `{k}`: {v}" for k, v in doc["boundary_marks"].items()]
    (RESULTS / "audit_tables.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    (RESULTS / "audit_rows.json").write_text(json.dumps(rows), encoding="utf-8")
    print("\n".join(out))
    if write_classes:
        CLASS_FILE.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main("--write-classes" in sys.argv)
