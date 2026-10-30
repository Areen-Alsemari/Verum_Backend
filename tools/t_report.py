"""Report of the transient scenarios T1 to T4.

Peaks are quoted for the valid interval only, from the command to the start of the first invalid
window of the transient engine, together with the rigid-column peak over the same interval. The
columns at the instant of closure are kept and labelled unusable because a window has opened before
it.

See D22, D45, D53 and D55.
"""

from __future__ import annotations

import json
from typing import Any


def load(name: str) -> Any:
    with open(f"local/results/{name}.json", encoding="utf-8") as fh:
        return json.load(fh)


def pct(a: float, b: float) -> str:
    return f"{100 * (a - b) / b:+.1f} %"


def t1_lines(t1: dict[str, Any], where: dict[str, Any]) -> list[str]:
    f = where["T1"]["first"]
    side = f["side_of_valve"]["XV-R000"]
    dist = f["distance_from_valve_m"]["XV-R000"]
    out = ["## T1 ESD isolation (XV-R000 10 s, XV-R101 30 s, cap 10 barg)", ""]
    out += [
        f"Ratio {t1['ratio']:.1f}. First phase window at {t1['first_phase_window_s']:.2f} s "
        f"(closure completes at {t1['t_close_s']:.2f} s); {t1['n_windows']} windows in the run.",
        f"First point at the vapor pressure: {f['edge']} at {f['offset_from_edge_start_m']:g} m "
        f"from its start, {dist:g} m from XV-R000 ({side}), "
        f"{f['pressure_bar_abs']:.3f} bar absolute against {f['vapor_pressure_bar_abs']:.3f}.",
        "",
        "| location | transient peak, valid (barg) | rigid peak, valid (barg) | rigid - transient "
        "| at closure, transient (unusable) | at closure, rigid (unusable) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for k in ("pt001", "tap", "hdr"):
        m, g = t1["moc_valid"][k], t1["rigid_valid"][k]
        out.append(
            f"| {k} | {m[0]:.2f} ({m[1]:.2f} s) | {g[0]:.2f} ({g[1]:.1f} s) | {pct(g[0], m[0])} "
            f"| {t1['moc_at_closure'][k][0]:.2f} | {t1['rigid_at_closure'][k][0]:.2f} |"
        )
    return out + [""]


def t2_lines(t2: list[dict[str, Any]], where: dict[str, Any]) -> list[str]:
    out = ["## T2 receipt valve strokes with the cap (XV-R000 only)", ""]
    out += [
        "| stroke s | ratio | first window s | first point | transient peak | rigid peak "
        "| rigid minus transient | max flow difference m3/h |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    located = {r["stroke_s"]: r["first"] for r in where["T2"]}
    for r in t2:
        m, g = r["moc_valid"]["pt001"][0], r["rigid_valid"]["pt001"][0]
        f = located.get(r["stroke_s"])
        point = "-"
        if f:
            point = f"{f['edge']} {f['distance_from_valve_m']['XV-R000']:g} m"
            point += f" {f['side_of_valve']['XV-R000']}"
        out.append(
            f"| {r['stroke_s']:g} | {r['ratio']:.1f} | {r['first_phase_window_s']:.2f} | {point} "
            f"| {m:.2f} | {g:.2f} | {pct(g, m)} | {r['flow_max_abs_diff_m3h']:.1f} |"
        )
    out += [
        "",
        "Only a ratio of 55 reaches 5 percent in the valid interval; the sign changes at 20-28.",
        "",
    ]
    return out


def t3_lines(t3: dict[str, Any]) -> list[str]:
    out = ["## T3 pump-branch valve stroke and pump stop", ""]
    out += [
        "| stroke s | ratio | compared until s | discharge peak transient / rigid (barg) "
        "| suction peak transient / rigid (barg) | max flow difference m3/h |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in t3["T3_valve"]:
        out.append(
            f"| {r['stroke_s']:g} | {r['ratio_pump_branch']:.0f} | {r['compare_until_s']:.1f} "
            f"| {r['moc']['disc'][0]:.3f} / {r['rigid']['disc'][0]:.3f} "
            f"| {r['moc']['suct'][0]:.3f} / {r['rigid']['suct'][0]:.3f} "
            f"| {r['flow_max_abs_diff_m3h']:.2f} |"
        )
    out += [
        "",
        "Pump stop (no rigid-column counterpart; D6): values after the first window are unusable.",
        "",
    ]
    out += [
        "| delay s | first window s | closure of the check valve s | reverse volume m3 |",
        "| --- | --- | --- | --- |",
    ]
    for r in t3["T3_pump_stop"]:
        out.append(
            f"| {r['delay_s']:g} | {r['first_phase_window_s']:.2f} | {r['closed_at_s']:.2f} "
            f"| {r['reverse_volume_m3']:.4f} |"
        )
    return out + [""]


def t4_lines(t4: dict[str, Any]) -> list[str]:
    out = [
        "## T4 receipt set-point steps: inertial head, rigid column against transient mean",
        "",
    ]
    for name, case in t4.items():
        out += [
            f"### {name} (level {case['level_m']:.3f} m, Lambda_down {case['lambda_down']:.2f})",
            "",
        ]
        out += [
            "| instant | flow m3/h | dQ/dt m3/s2 | PT-001 rigid barg "
            "| Lambda_down x abs(dQ/dt) bar | transient 2 s mean barg | difference / dip "
            "| end of E002 head m |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for label, p in case["points"].items():
            if "qdot_m3s2" in p:
                out.append(
                    f"| {label} | {p['flow_m3h']:.1f} | {p['qdot_m3s2']:.4f} "
                    f"| {p['pt001_barg']:.3f} "
                    f"| {p['hand_lambda_qdot_bar']:.3f} | {p['moc_window_mean_pt001_barg']:.3f} "
                    f"| {p['difference_over_dip_percent']:+.1f} % | {p['tap_head_m']:.2f} |"
                )
            else:
                out.append(
                    f"| {label} | {p['flow_m3h']:.1f} | | {p['pt001_barg']:.3f} "
                    f"| | | | {p['tap_head_m']:.2f} |"
                )
        out.append("")
    return out


def main() -> None:
    t12, t3, where, t4 = load("t12"), load("t3"), load("phase_location"), load("t4_dip")
    lines = ["# Scenarios T1 to T4: transient engine against the rigid-column engine", ""]
    lines += [
        "Both engines start from the same lineup, levels and receipt flow. Values are for the "
        "valid interval (decision D55); the columns at closure are unusable.",
        "",
    ]
    lines += t1_lines(t12["T1"], where) + t2_lines(t12["T2"], where) + t3_lines(t3) + t4_lines(t4)
    with open("local/results/t_scenarios.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("written")


if __name__ == "__main__":
    main()
