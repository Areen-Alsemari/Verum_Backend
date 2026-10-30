"""Agent-side audit, analysis stage: residual features, thresholds, margins, classes and tables.

Inputs: ``local/results/audit_v2_runs.jsonl`` from ``tools/fault_audit_v2.py`` and the Phase 6a
results ``fault_audit.json``. Outputs: ``local/results/fault_audit_v2.json`` and
``fault_audit_v2.md`` (all tables), ``local/results/fault_audit_v2_summary.md`` (the tables the
fault-model document quotes) and, with ``--write-classes``, ``config/severity_classes.json``. Run as
``python tools/fault_audit_v2_report.py [--write-classes]``.
Features (decision D77), from the 60 s window means of the observed tags and design data only:
(1) mass balance FT-001 - FT-201 - sum over tanks of area x level slope; (2) pump consistency
PT-202A - PT-201 - rho g H(FT-201); (3) delivery law PT-203 - (2 barg + rho g c (FT-201/300)^2);
(4) FT-201 against the design delivery flow for the observed level; (5) PT-001 against the design
receipt pressure for FT-001 and the observed level; (6) each continuous tag minus its previous
window mean (a one-step persistence forecast); and the discrete features, a change after the onset
of a valve contact or of a pump run status.
Nuisance: five draws of the design model (pump head scale uniform in 0.97 to 1.03, fitting K
multiplier log-uniform in 0.5 to 2, boundary coefficient multiplier log-uniform in 0.8 to 1.25),
from the named stream ``audit_nuisance``. The threshold of a feature is three times its standard
deviation over the healthy runs (20 seeds x 5 draws x windows 4 to 45) of the profile and lineup,
about the mean of the same sample; the margin of a feature in a run is the largest absolute
deviation from that mean over the windows after the onset, in units of the threshold. The margin of
a run under a draw is the largest over features; the margin of the run is the smallest over the five
draws (an agent whose design is wrong in the worst way), and a discrete change is a margin of 3 or
more at once. Classes (decision D78): invisible below 1, marginal from 1 to below 3, clear from 3.
Source: ``docs/design_decisions.md`` D68, D74 to D78; serves the Phase 6b report.
"""

from __future__ import annotations

import dataclasses
import json
import math
import sys
from collections import defaultdict
from functools import lru_cache
from itertools import combinations
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import numpy as np
from fault_audit import CONT, N_SEV, ONSET_S, coordinates
from fault_audit_v2 import N_WINDOWS, OUT, WINDOW_S

from verum.faults import FaultSpec, LineupState, activity
from verum.hydraulics import (
    DeliveryBoundary,
    HydraulicModel,
    ReceiptBoundary,
    SteadyInputs,
    load_boundary_law_coefficient,
)
from verum.lineups import load_lineup_table
from verum.rng import RandomStreams
from verum.tanks import load_tank_geometry

RESULTS = Path("local/results")
FIRST_WINDOW = 4  # windows 1 to 3 hold the start-up of the receipt controller
K_ON = int(math.ceil((ONSET_S + 1e-9) / WINDOW_S)) + 1  # first window ending after the onset
INVISIBLE, CLEAR = 1.0, 3.0
THRESHOLD_SIGMAS = 3.0
COSINE = 0.95
MARGIN_KEY = "held_margin"  # the margin of the class boundaries (decision D78, see the report)
LAST_WINDOWS = 5
SUSTAIN_WINDOWS = 3
LT = ("LT-101", "LT-102", "LT-103")
LAYOUT = {  # family -> (lineup mode, delivering tank, receiving tanks)
    "A": ("DELIVER_101_A", "TK-101", ()),
    "B": ("RECEIVE_101", None, ("TK-101",)),
    "C": ("RECEIVE_101_DELIVER_102_A", "TK-102", ("TK-101",)),
    "B2": ("RECEIVE_101_102", None, ("TK-101", "TK-102")),
}
NOMINAL = (1.0, 1.0, 1.0)


def draws() -> list[tuple[float, float, float]]:
    """The nominal design and the five perturbed ones (head scale, K and c multipliers)."""
    rng = RandomStreams(20261106).stream("audit_nuisance")
    out = [NOMINAL]
    for _ in range(5):
        head = float(rng.uniform(0.97, 1.03))
        k = math.exp(float(rng.uniform(math.log(0.5), math.log(2.0))))
        c = math.exp(float(rng.uniform(math.log(0.8), math.log(1.25))))
        out.append((head, k, c))
    return out


DRAWS = draws()


@lru_cache(maxsize=1)
def design() -> tuple[HydraulicModel, Any]:
    model = HydraulicModel.load().for_stratum("coastal")
    return model, load_lineup_table(model.topology)


def solve(fam: str, draw: tuple[float, float, float], levels: dict[str, float], q_in: float) -> Any:
    model, table = design()
    head, k, c = draw
    pump = model.default_pump()
    pump = dataclasses.replace(pump, h0_m=pump.h0_m * head, k_m=pump.k_m * head)
    law = load_boundary_law_coefficient("reference_fittings").value * c
    inputs = SteadyInputs(
        table.mode(LAYOUT[fam][0]).lineup, levels, "RVP_9_0", 25.0,
        fitting_profile="reference_fittings", k_multiplier=k,
        receipt=ReceiptBoundary(flow_m3h=q_in), delivery=DeliveryBoundary(law_coefficient_m=law),
        pump=pump,
    )  # fmt: skip
    return model.solve(inputs)


def design_values(fam: str, draw: tuple[float, float, float], wm: dict[str, np.ndarray]) -> tuple:
    """Design delivery flow and design PT-001 (barg) per window, NaN where not defined."""
    q_design, p_design = np.full(N_WINDOWS, np.nan), np.full(N_WINDOWS, np.nan)
    _mode, deliver, receive = LAYOUT[fam]
    for w in range(FIRST_WINDOW - 1, N_WINDOWS):
        lv = {f"TK-{t[3:]}": wm[t][w] for t in LT}
        flow = wm["FT-001"][w]
        if any(np.isnan(v) for v in lv.values()) or np.isnan(flow):
            continue
        try:
            r = solve(fam, draw, lv, max(flow, 0.0) if receive else 0.0)
        except Exception:  # noqa: BLE001  (outside the design curve: no value, not an error)
            continue
        if deliver and r.pump is not None:
            q_design[w] = r.pump.flow_m3h
        if receive and flow > 50.0:
            p_design[w] = r.tap_pressures_pa_gauge["PIPELINE_RECEIPT_BOUNDARY"] / 1e5
    return q_design, p_design


def features(
    fam: str, draw: tuple[float, float, float], wm: dict[str, list[float]]
) -> dict[str, list]:
    """Feature series (45 windows) of one record under one design."""
    model, _ = design()
    a = {t: np.array(v) for t, v in wm.items()}
    rho_g = model.rho * model.g
    head, _k, c_mult = draw
    area = load_tank_geometry().area_m2
    _mode, deliver, receive = LAYOUT[fam]
    out: dict[str, np.ndarray] = {}
    dvol = sum(area * np.diff(a[t], prepend=np.nan) / WINDOW_S * 3600.0 for t in LT)
    out["mass_balance"] = a["FT-001"] - a["FT-201"] - dvol
    if deliver:
        pump = model.default_pump()
        h = np.array([pump.head_rise_m(q) if not np.isnan(q) else np.nan for q in a["FT-201"]])
        out["pump_consistency"] = (a["PT-202A"] - a["PT-201"]) * 1e5 - rho_g * head * h
        law = load_boundary_law_coefficient("reference_fittings").value * c_mult
        out["delivery_law"] = (a["PT-203"] - 2.0) * 1e5 - rho_g * law * (a["FT-201"] / 300.0) ** 2
    q_design, p_design = design_values(fam, draw, a)
    if deliver:
        out["delivery_flow"] = a["FT-201"] - q_design
    if receive:
        out["receipt_law"] = (a["PT-001"] - p_design) * 1e5
    for tag in CONT:
        out[f"persist:{tag}"] = np.diff(a[tag], prepend=np.nan)
    return {k: v.tolist() for k, v in out.items()}


def contact_changes(ev: dict[str, list[list[float]]]) -> list[tuple[float, str]]:
    """(time, tag) of every change of a contact or run status after the onset."""
    out = []
    for tag, rows in ev.items():
        before = [v for t, v in rows if t <= ONSET_S]
        state = before[-1] if before else None
        for t, v in rows:
            if t > ONSET_S and v != state:
                out.append((t, tag))
                state = v
    return sorted(out)


def process(rec: dict[str, Any]) -> dict[str, Any]:
    fam = rec["label"].split("|")[1]
    if rec.get("rejected"):
        return {"label": rec["label"], "rejected": rec["rejected"]}
    return {
        "label": rec["label"], "rejected": None,
        "features": [features(fam, d, rec["wm"]) for d in DRAWS],
        "changes": contact_changes(rec["ev"]),
    }  # fmt: skip


def expand(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each healthy or fault run, and each sensor case of a first-seed healthy run, as a record."""
    out = []
    for r in records:
        out.append(r)
        for key, case in r.get("sensor_cases", {}).items():
            profile = r["label"].split("|")[2]
            out.append({"label": f"{key}||{profile}", "rejected": None, **case})
    return out


def load_processed() -> list[dict[str, Any]]:
    cache = RESULTS / "audit_v2_features.json"
    if cache.exists():
        loaded: list[dict[str, Any]] = json.loads(cache.read_text(encoding="utf-8"))
        return loaded
    records = expand([json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines()])
    with Pool(9) as pool:
        done = pool.map(process, records, chunksize=4)
    cache.write_text(json.dumps(done), encoding="utf-8")
    return done


# --- thresholds and margins ----------
def healthy_stats(
    done: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, tuple[float, float]]]:
    """(profile, family) -> feature -> (mean, threshold) over seeds, draws 1 to 5 and windows."""
    pool: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in done:
        parts = r["label"].split("|")
        if parts[0] != "healthy" or r["rejected"]:
            continue
        for fd in r["features"][1:]:
            for name, series in fd.items():
                pool[(parts[2], parts[1])][name] += series[FIRST_WINDOW - 1 :]
    stats: dict[tuple[str, str], dict[str, tuple[float, float]]] = {}
    for key, feats in pool.items():
        stats[key] = {}
        for name, values in feats.items():
            x = np.array(values)
            x = x[~np.isnan(x)]
            if len(x) > 10:
                stats[key][name] = (float(x.mean()), THRESHOLD_SIGMAS * float(x.std(ddof=1)))
    return stats


def held_series(z: np.ndarray) -> np.ndarray:
    """Margin held over three consecutive windows, at the last window of the three."""
    if len(z) < SUSTAIN_WINDOWS:
        return np.zeros(0)
    n = len(z) - SUSTAIN_WINDOWS + 1
    return np.minimum.reduce([z[i : n + i] for i in range(SUSTAIN_WINDOWS)])


def margins(fd: dict[str, list[float]], st: dict[str, tuple[float, float]]) -> dict[str, tuple]:
    """Feature -> (largest single-window margin after the onset, first window at which a margin
    above 1 has been held for three windows or None, largest margin held over three windows)."""
    out = {}
    for name, (mu, theta) in st.items():
        if name not in fd or theta <= 0.0:
            continue
        z = np.abs(np.array(fd[name]) - mu) / theta
        z = z[K_ON - 1 :]
        z = np.where(np.isnan(z), 0.0, z)
        held = held_series(z)
        above = np.nonzero(held > 1.0)[0]
        first = None if len(above) == 0 else int(above[0]) + SUSTAIN_WINDOWS - 1 + K_ON
        out[name] = (float(z.max()), first, float(held.max()) if len(held) else 0.0)
    return out


def evaluate(r: dict[str, Any], st: dict[str, tuple[float, float]]) -> dict[str, Any]:
    per_draw = []
    by_feature: dict[str, list[float]] = defaultdict(list)
    for fd in r["features"][1:]:
        m = margins(fd, st)
        for name, v in m.items():
            by_feature[name].append(v[2])
        top = max(m.items(), key=lambda kv: kv[1][0])
        firsts = [w for _, w, _ in m.values() if w is not None]
        held = max(v[2] for v in m.values())
        per_draw.append((top[1][0], top[0], min(firsts) if firsts else None, held))
    worst = min(per_draw, key=lambda x: x[0])
    held_margin = min(x[3] for x in per_draw)
    nominal = margins(r["features"][0], st)
    margin, dominant, first, _ = worst
    change = r["changes"][0][0] if r["changes"] else None
    discrete = change is not None
    t_first = None if first is None else WINDOW_S * first - ONSET_S
    if discrete and (t_first is None or change - ONSET_S < t_first):
        t_first = change - ONSET_S
    if discrete:
        margin = max(margin, CLEAR)
    return {
        "margin": margin, "held_margin": max(held_margin, CLEAR) if discrete else held_margin,
        "dominant": "contact" if discrete and margin == CLEAR else dominant,
        "t_first_s": t_first, "discrete": discrete,
        "nominal_margin": max((v[0] for v in nominal.values()), default=0.0),
        "nominal_held": max((v[2] for v in nominal.values()), default=0.0),
        "signature": signature(r["features"][0], st),
        "changed_tags": sorted({tag for _, tag in r["changes"]}),
        "held_by_feature": {k: round(min(v), 3) for k, v in by_feature.items()
                            if not k.startswith("persist") or min(v) >= 1.0},  # fmt: skip
    }  # fmt: skip


def signature(fd: dict[str, list[float]], st: dict[str, tuple[float, float]]) -> dict[str, float]:
    """Signed mean over the last windows of (feature - healthy mean) / threshold, nominal design."""
    out = {}
    for name, (mu, theta) in st.items():
        if name in fd and theta > 0.0:
            x = np.array(fd[name][-LAST_WINDOWS:])
            x = x[~np.isnan(x)]
            out[name] = float((x.mean() - mu) / theta) if len(x) else 0.0
    return out


def klass(margin: float) -> str:
    return "invisible" if margin < INVISIBLE else "marginal" if margin < CLEAR else "clear"


# --- the fault cells ----------
def cell(label: str) -> dict[str, Any]:
    p = label.split("|")
    if label.startswith("healthy"):
        return {}
    kind, fam, asset, idx = p[0], p[1], p[2], int(p[3])
    mode = p[4] if kind == "restriction" and len(p) > 5 else ""
    profile = p[-1]
    fault = f"restriction_{mode}" if kind == "restriction" and mode else kind
    return {"kind": kind, "fault": fault, "family": fam, "asset": asset, "index": idx,
            "profile": profile}  # fmt: skip


def coordinate_of(kind: str, index: int) -> float | None:
    if kind in ("misroute_a", "stuck"):
        return None
    if kind in ("bias", "drift"):
        return coordinates(kind)[index]
    return coordinates(kind)[index]


SPECS = {  # kind -> fault type and variant (the values do not matter for the label)
    "leak": ("PIPE_LEAK", "orifice"), "restriction": ("VALVE_RESTRICTION", "restriction"),
    "pump": ("PUMP_HEAD_DEGRADATION", "head_scale"), "bias": ("SENSOR_DRIFT", "bias"),
    "drift": ("SENSOR_DRIFT", "drift"), "stuck": ("SENSOR_DRIFT", "stuck"),
    "misroute_a": ("VALVE_MISROUTING", "closed_but_open"),
    "misroute_b": ("VALVE_MISROUTING", "open_but_stuck"),
}  # fmt: skip


def activity_of(kind: str, family: str, asset: str, fault: str) -> str:
    """Decision D76 label of a cell from the lineup of its family (set-point 600 when receiving)."""
    mode, _deliver, receive = LAYOUT[family]
    m = design()[1].mode(mode)
    state = LineupState(
        frozenset(m.open_valves), frozenset(m.running_pumps), 600.0 if receive else 0.0
    )
    ftype, variant = SPECS[kind]
    restriction_mode = fault.split("_", 1)[1] if kind == "restriction" else None
    spec = FaultSpec(ftype, variant, asset, 900.0, 300.0, 0.5, fault_mode=restriction_mode)
    return activity(spec, [state])


def evaluate_all(done: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stats = healthy_stats(done)
    rows = []
    for r in done:
        c = cell(r["label"])
        parts = r["label"].split("|")
        if not c and parts[0] == "healthy" and not r["rejected"]:
            st = stats[(parts[2], parts[1])]
            rows.append({"healthy": True, "profile": parts[2], "family": parts[1],
                         "seed": int(parts[3]), "fault": "healthy", **evaluate(r, st)})  # fmt: skip
            continue
        if not c:
            continue
        base = {**c, "label": r["label"], "coordinate": coordinate_of(c["kind"], c["index"]),
                "activity": activity_of(c["kind"], c["family"], c["asset"], c["fault"]),
                }  # fmt: skip
        if r["rejected"]:
            rows.append({**base, "rejected": r["rejected"].get("gate")})
            continue
        st = stats[(c["profile"], c["family"])]
        rows.append({**base, "rejected": None, **evaluate(r, st)})
    return rows


# --- tables ----------
def faults_only(rows: list[dict[str, Any]], active: bool = True) -> list[dict[str, Any]]:
    out = [r for r in rows if not r.get("healthy")]
    return [r for r in out if (r["activity"] == "active") == active] if active is not None else out


def counts(rows: list[dict[str, Any]], profile: str, key: str) -> dict[str, dict[str, int]]:
    """Active cells of a profile by fault and class of the margin ``key``; rejected apart."""
    out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in faults_only(rows):
        if r["profile"] == profile:
            out[r["fault"]]["rejected" if r["rejected"] else klass(r[key])] += 1
    return out


def share(c: dict[str, dict[str, int]], fault: str, keys: tuple[str, ...]) -> str:
    total = sum(v for k, v in c[fault].items() if k != "rejected")
    return f"{sum(c[fault][k] for k in keys)}/{total}"


def twin_counts() -> dict[str, list[int]]:
    """Phase 6a: active cells with an observable consequence, by fault (restriction: visible)."""
    old = json.loads((RESULTS / "fault_audit.json").read_text(encoding="utf-8"))["runs"]
    twin: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in old:
        fam = r["scenario"][-1]
        name = "restriction_position_visible" if r["kind"] == "restriction" else r["kind"]
        if r.get("rejected") or activity_of(r["kind"], fam, r["asset"], name) != "active":
            continue
        twin[name][0] += 1
        twin[name][1] += int(bool(r["consequence"]))
    return twin


def comparison(rows: list[dict[str, Any]]) -> list[str]:
    twin = twin_counts()
    cs = {(p, k): counts(rows, p, k) for p in ("v1", "v2") for k in ("margin", "held_margin")}
    lines = [
        "| fault | 6a twin | v1 m>=1 | v1 m>=3 | v1 held>=1 | v1 held>=3 | v2 m>=1 | v2 m>=3 "
        "| v2 held>=1 | v2 held>=3 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    both, one = ("marginal", "clear"), ("clear",)
    for f in sorted({*cs[("v1", "margin")], *cs[("v2", "margin")]}):
        t = twin.get(f)
        cells = [f"{t[1]}/{t[0]}" if t else "-"]
        for p in ("v1", "v2"):
            for k in ("margin", "held_margin"):
                cells += [share(cs[(p, k)], f, both), share(cs[(p, k)], f, one)]
        lines.append(f"| {f} | " + " | ".join(cells) + " |")
    return lines


def healthy_floor(rows: list[dict[str, Any]]) -> list[str]:
    """Margin of the healthy seeds, and of the latent cells (which equal a healthy run)."""
    head = "| group | profile | runs | m>=1 | m>=3 | held>=1 | held>=3 | median m | median held |"
    lines = [head,
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("healthy"):
            groups[("healthy seeds", r["profile"])].append(r)
        elif r["activity"] == "latent" and not r["rejected"]:
            groups[("latent cells", r["profile"])].append(r)
    for (name, profile), rs in sorted(groups.items()):
        m, h = np.array([r["margin"] for r in rs]), np.array([r["held_margin"] for r in rs])
        lines.append(
            f"| {name} | {profile} | {len(rs)} | {(m >= 1).sum()} | {(m >= 3).sum()} | "
            f"{(h >= 1).sum()} | {(h >= 3).sum()} | {np.median(m):.2f} | {np.median(h):.2f} |"
        )
    return lines


def cell_table(rows: list[dict[str, Any]]) -> list[str]:
    """Every fault cell: margins, time to first exceed, class, and the features at or above 1."""
    head = "| fault | profile | lineup | asset | severity | activity | held m | single-window m "
    lines = [head + "| first exceed (s) | class | features held >= 1 |", "| --- |" + " --- |" * 10]
    for r in sorted(faults_only(rows, active=None), key=lambda r: (r["fault"], r["profile"],
                    r["family"], r["asset"], r["index"])):  # fmt: skip
        coord = "-" if r["coordinate"] is None else f"{r['coordinate']:.4g}"
        if r["rejected"]:
            lines.append(f"| {r['fault']} | {r['profile']} | {r['family']} | {r['asset']} | {coord}"
                         f" | {r['activity']} | rejected {r['rejected']} | | | | |")  # fmt: skip
            continue
        t = "-" if r["t_first_s"] is None else f"{r['t_first_s']:.0f}"
        held = ", ".join(f"{k} {v:.1f}" for k, v in sorted(r["held_by_feature"].items()) if v >= 1)
        lines.append(
            f"| {r['fault']} | {r['profile']} | {r['family']} | {r['asset']} | {coord} | "
            f"{r['activity']} | {r['held_margin']:.2f} | {r['margin']:.2f} | {t} | "
            f"{klass(r['held_margin'])} | {held or '-'} |"
        )
    return lines


def fractions(c: dict[str, int], n: int) -> str:
    return " / ".join(f"{c[k] / n:.2f}" for k in ("invisible", "marginal", "clear"))


def class_fractions(rows: list[dict[str, Any]], profile: str) -> list[str]:
    cm, ch = counts(rows, profile, "margin"), counts(rows, profile, "held_margin")
    latent: dict[str, int] = defaultdict(int)
    for r in faults_only(rows, active=False):
        if r["profile"] == profile and not r["rejected"]:
            latent[r["fault"]] += 1
    head = "| fault | active cells | latent | rejected | m: inv / marg / clear "
    lines = [head + "| held: inv / marg / clear | balanced share |", "| --- |" * 1 + " --- |" * 6]
    for f in sorted(cm):
        n = sum(v for k, v in cm[f].items() if k != "rejected")
        cm_f, ch_f = cm[f], ch[f]
        populated = sum(1 for k in ("invisible", "marginal", "clear") if ch[f][k])
        lines.append(
            f"| {f} | {n} | {latent[f]} | {cm[f]['rejected']} | {fractions(cm_f, n)} | "
            f"{fractions(ch_f, n)} | "
            f"{1 / populated:.2f} each of {populated} populated (held) |"
        )
    return lines


def confusables(rows: list[dict[str, Any]], profile: str) -> tuple[list[str], dict[str, Any]]:
    live = [r for r in faults_only(rows) if r["profile"] == profile and not r["rejected"]
            and r["held_margin"] >= 1]  # fmt: skip
    tally: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for a, b in combinations(live, 2):
        if a["fault"] == b["fault"] or a["family"] != b["family"]:
            continue
        sa, sb = a["signature"], b["signature"]
        names = sorted(set(sa) & set(sb))
        va, vb = np.array([sa[n] for n in names]), np.array([sb[n] for n in names])
        na, nb = np.linalg.norm(va), np.linalg.norm(vb)
        if na == 0 or nb == 0 or float(va @ vb) / (na * nb) <= COSINE:
            continue
        key = tuple(sorted((a["fault"], b["fault"])))
        t = tally[key]  # type: ignore[index]
        t[0] += 1
        t[1] += int(a["changed_tags"] != b["changed_tags"])
    lines = ["| pair | confusable cell pairs | separated by a contact or run status |",
             "| --- | --- | --- |"]  # fmt: skip
    for (x, y), (n, sep) in sorted(tally.items()):
        lines.append(f"| {x} / {y} | {n} | {sep} |")
    return lines, {f"{x}/{y}": v for (x, y), v in tally.items()}


# --- severity classes ----------
def crossing(points: list[tuple[float, float]], level: float) -> float | None:
    """Coordinate where the margin first reaches ``level`` (log-log interpolation), or None."""
    pts = sorted(points)
    if pts[0][1] >= level:
        return pts[0][0]
    for (x0, m0), (x1, m1) in zip(pts, pts[1:], strict=False):
        if m0 < level <= m1 and m0 > 0:
            f = (math.log(level) - math.log(m0)) / (math.log(m1) - math.log(m0))
            return math.exp(math.log(x0) + f * (math.log(x1) - math.log(x0)))
        if m0 < level <= m1:
            return x1
    return None


def asset_class(kind: str, asset: str) -> str:
    if kind == "leak":
        return ("suction" if asset.startswith("E-S") else "pump_branch" if asset.startswith("E-P")
                else "discharge" if asset.startswith("E-D") else "receipt")  # fmt: skip
    if kind in ("restriction", "misroute_a", "misroute_b"):
        return ("pump_branch" if asset.startswith("XV-P") else "tank_outlet"
                if asset.startswith("XV-S") else "tank_inlet")  # fmt: skip
    if kind == "pump":
        return "pump"
    unit = {"FT": "flow", "PT": "pressure", "LT": "level"}
    return unit[asset[:2]]


def boundaries(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per (fault, asset class): median over assets of the coordinates where m reaches 1 and 3."""
    by_asset: dict[tuple[str, str, str, str], list[tuple[float, float]]] = defaultdict(list)
    for r in faults_only(rows):
        if r["profile"] != "v2" or r["rejected"] or r["coordinate"] is None:
            continue
        sign = -1.0 if r["kind"] == "misroute_b" else 1.0
        key = (r["fault"], asset_class(r["kind"], r["asset"]), r["family"], r["asset"])
        by_asset[key].append((sign * r["coordinate"], r[MARGIN_KEY]))
    out: dict[str, dict[str, Any]] = {}
    for (fault, aclass, _fam, _asset), pts in by_asset.items():
        entry = out.setdefault(
            f"{fault}/{aclass}", {"marginal": [], "clear": [], "n": 0, "pts": []}
        )
        entry["n"] += 1
        entry["pts"].append(sorted(pts))
        for name, level in (("marginal", INVISIBLE), ("clear", CLEAR)):
            x = crossing(pts, level)
            entry[name].append(x)
    return out


def class_file(bounds: dict[str, dict[str, Any]]) -> dict[str, Any]:
    prov = "VERUM-PHASE6B-AUDIT-V2"
    params: dict[str, Any] = {}
    for key, e in sorted(bounds.items()):
        for name in ("marginal", "clear"):
            vals = [abs(v) for v in e[name] if v is not None]
            ok = len(vals) == e["n"]
            rec: dict[str, Any]
            if ok:
                rec = {"value": float(np.median(vals)), "unit": "1", "status": "provisional",
                       "evidence_tag": "SIM", "provenance_id": prov}  # fmt: skip
            else:
                level = INVISIBLE if name == "marginal" else CLEAR
                reason = (
                    f"the margin of {e['n'] - len(vals)} of {e['n']} assets does not reach "
                    f"{level:g} within the range"
                )
                rec = {"value": None, "unit": "1", "status": "unresolved", "evidence_tag": "OPEN",
                       "unresolved_reason": reason}  # fmt: skip
            params[f"{key}/{name}_from"] = rec
    return {
        "schema_version": "1.0.0",
        "description": "Severity class boundaries of the agent-side audit, profile v2 (decisions "
        "D77, D78): the severity coordinate (the same as the audit: leak area in m2, closure or "
        "head loss fraction, sensor fraction of span, stuck opening) from which the margin of the "
        "worst design reaches 1 (marginal) and 3 (clear); the median over the assets of the "
        "class. A value at the lower end of the range of the fault means the class begins at or "
        "below that end.",
        "source": "tools/fault_audit_v2_report.py",
        "parameters": params,
    }


def main(write_classes: bool) -> None:
    done = load_processed()
    rows = evaluate_all(done)
    stats = healthy_stats(done)
    lines = ["# Agent-side observability audit (Phase 6b)", "", "## Comparison (active cells)", ""]
    lines += comparison(rows) + ["", "## Healthy floor of the margin", ""] + healthy_floor(rows)
    lines += ["", "## Class fractions, profile v1", ""] + class_fractions(rows, "v1")
    lines += ["", "## Class fractions, profile v2", ""] + class_fractions(rows, "v2")
    conf: dict[str, Any] = {}
    for profile in ("v1", "v2"):
        table, conf[profile] = confusables(rows, profile)
        lines += ["", f"## Confusable pairs (cosine above {COSINE}), profile {profile}", ""] + table
    lines += ["", "## Thresholds (3 sigma of the healthy residual), profile v2", ""]
    for (profile, fam), feats in sorted(stats.items()):
        if profile != "v2":
            continue
        lines += [f"### {fam}", "", "| feature | mean | threshold |", "| --- | --- | --- |"]
        lines += [f"| {n} | {mu:.4g} | {th:.4g} |" for n, (mu, th) in sorted(feats.items())
                  if not n.startswith("persist")]  # fmt: skip
        lines.append("")
    (RESULTS / "fault_audit_v2.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    cells = ["# Fault cells of the agent-side audit", ""] + cell_table(rows)
    (RESULTS / "fault_audit_v2_cells.md").write_text("\n".join(cells) + "\n", encoding="utf-8")
    (RESULTS / "fault_audit_v2.json").write_text(
        json.dumps({"rows": rows, "confusable": conf, "n_severities": N_SEV}), encoding="utf-8"
    )
    print("\n".join(lines))
    if write_classes:
        out = class_file(boundaries(rows))
        Path("config/severity_classes.json").write_text(json.dumps(out, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main("--write-classes" in sys.argv)
