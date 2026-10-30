"""Report of the sensitivity study: one section per sweep.

Each section states what was varied, what was measured, and which results are stable or depend on
the selection. The commentary under each table was written for an earlier run and is checked against
the regenerated tables by reading them, while the section on the window factors is computed from the
data. Nothing here is a measurement.

See D42 and D48.
"""

from __future__ import annotations

import json
from typing import Any

STABLE_D23 = (
    "Stable: no window and no rejection in any of the nine runs; the pump margin never gets "
    "near 1 (smallest 2.45). Depends on the selection: the spread of FT-201 scales with sigma "
    "(std about 0.9, 1.7, 3.2 m3/h at 1800 s) and with the inverse square root of the "
    "correlation time (std 1.24, 0.88, 0.61 at sigma 0.05), and the mean flow rises (0.35 "
    "percent from sigma 0.05 to 0.1, 1.0 percent from 0.05 to 0.2) because the factor is "
    "clipped at 0.8 and 1.25 (an asymmetric range around 1). The pumping-minimum screen is "
    "computed at the worst factor f_d = 0.8 (D24, D51), which is the lower clip of the "
    "process, so it does not move with sigma or the correlation time; what moves is how often "
    "the run gets near it (the minimum margin falls from 2.60 to 2.45 as sigma goes from 0.05 "
    "to 0.2)."
)

STABLE_WAVE = (
    "Stable: the peak at the closure instant (14.30 to 14.49 barg, +-0.7 percent) and its "
    "time (20.003 to 20.006 s), because with a 10 s stroke the capped source and the valve "
    "law, not the wave speed, set the head. Depends on the selection: the wave speed itself "
    "(977 to 1184 m/s for DN300), the round trip (0.33 to 0.40 s) and so the ratio used by "
    "D22 (25 to 30), and the instant at which the first `phase_invalid` window opens (19.766 "
    "to 19.776 s), which moves the valid-interval peak between 10.7 and 11.6 barg (8 "
    "percent). The factor 10 of D22 is therefore insensitive to psi and K at the +-10 percent "
    "level of the ratio."
)

STABLE_CHECK = (
    "Stable: the first `phase_invalid` window opens at 10.37 s, 0.37 s after the stop, for "
    "every delay, so no result after it is usable. Depends on the selection: nothing that is "
    "usable; the closing instants and the reverse volumes after the window are artefacts of "
    "the missing vapor model and are not monotone in the delay (0.086, 0.169, 0.076 m3), "
    "while the accounting rule itself is monotone in the controlled test of the ladder (R10). "
    "The pump-stop case needs a cavitation model before the delay can be studied."
)

STABLE_D50 = (
    "Stable: the ESD peak at closure (14.27 to 14.44 barg over the multiplier, 14.39 to 14.41 "
    "over the meter K) because the closure is set by the cap and the valve law; the "
    "recalibrated boundary coefficient (10.0609 m for all three steepnesses, which is the "
    "duty-point invariance doing its job); the delivery flow, within 6 percent over a factor "
    "6 in the multiplier and 2 percent over a factor 8 in the meter K. Depends on the "
    "selection: the NPSH margin ratio, which is inversely proportional to the NPSH3 "
    "coefficient (4.93, 3.08, 2.06 at 9 m; 3.14, 1.96, 1.31 at 1.8 m) and decides which "
    "levels pass the pumping-minimum screen; the pump steepness changes the flow at the low "
    "level by +-1.2 percent and the margin at 1.8 m between 1.92 and 2.02. At the baseline "
    "(coastal, RVP_9_0, reference fittings, f_d = 0.8) the minimum level of TK-101 by NPSH3 "
    "2.5 / 4 / 6 m is 1.80 / 1.80 / 2.64 m at 25 C, 1.80 / 2.37 / 6.09 m at 35 C, 1.80 / 4.21 "
    "/ 8.17 m at 40 C and 3.70 / 6.28 / 10.51 m at 45 C "
    "(`config/pumping_minimum_levels_coastal_RVP_9_0_fd0p8.json`). The pumping-minimum screen "
    "is the result that depends most on the selected NPSH3."
)


def load(name: str) -> Any:
    with open(f"local/results/{name}.json", encoding="utf-8") as fh:
        return json.load(fh)


def window_sweep(rows: list[dict[str, Any]], key: str, values: tuple[float, ...]) -> list[str]:
    out = ["| scenario | " + " | ".join(f"{key} {v:g}" for v in values) + " |"]
    out.append("| --- |" + " --- |" * len(values))
    for s in sorted({r["scenario"] for r in rows}):
        cells = []
        for v in values:
            r = next(x for x in rows if x["scenario"] == s and x["params"][key] == v)
            kinds = sorted({k[0] for k in r["windows"]})
            cells.append(f"{len(r['windows'])}" + (f" ({', '.join(kinds)})" if kinds else ""))
        out.append(f"| {s} | " + " | ".join(cells) + " |")
    return out


def changing(rows: list[dict[str, Any]], key: str) -> list[str]:
    """Scenarios whose set of windows differs between the factors of the sweep."""
    by: dict[str, set[tuple[Any, ...]]] = {}
    for r in rows:
        by.setdefault(r["scenario"], set()).add(tuple(sorted((k[0], k[1]) for k in r["windows"])))
    return sorted(s for s, v in by.items() if len(v) > 1)


def section_windows(
    d22: list[dict[str, Any]], d53: list[dict[str, Any]], d58: list[dict[str, Any]]
) -> list[str]:
    out = ["## 1 Window factors", ""]
    out += ["### Set-point, collapse and closure factor (D22) 5, 10, 20", ""]
    out += window_sweep(d22, "wave_criterion_factor", (5.0, 10.0, 20.0))
    out += [
        "",
        "Scenarios whose windows change with this factor: "
        + (", ".join(changing(d22, "wave_criterion_factor")) or "none")
        + ".",
        "",
    ]
    out += ["### Valve-stroke factor (D53) 10, 20, 25, 30, 50, 55", ""]
    out += window_sweep(
        d53, "wave_criterion_factor_valve_stroke", (10.0, 20.0, 25.0, 30.0, 50.0, 55.0)
    )
    out += [
        "",
        "Scenarios whose windows change with this factor: "
        + (", ".join(changing(d53, "wave_criterion_factor_valve_stroke")) or "none")
        + ".",
        "",
    ]
    out += ["### Minimum flow fraction of a judged stroke (D58) 0.05, 0.10, 0.20", ""]
    out += window_sweep(d58, "stroke_window_min_flow_fraction", (0.05, 0.1, 0.2))
    out += [
        "",
        "Scenarios whose windows change with this fraction: "
        + (", ".join(changing(d58, "stroke_window_min_flow_fraction")) or "none")
        + ".",
        "",
    ]
    return out


def section_d23(d23: list[dict[str, Any]]) -> list[str]:
    out = [
        "## 2 D23 demand process: sigma of log f_d 0.05, 0.1, 0.2; correlation 900, 1800, 3600 s",
        "",
    ]
    out += [
        "S0-F, 3600 s, delivery from TK-102. Delivery flow on E-D1 (true value, m3/h) and the "
        "smallest NPSH margin ratio.",
        "",
    ]
    out += ["| sigma | correlation time s | mean | std | min | max | minimum margin | windows |"]
    out += ["| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in d23:
        f, p = r["ft201_like_flow_m3h"], r["params"]
        out.append(
            f"| {p['demand_sigma_log']:g} | {p['demand_correlation_time_s']:g} | {f['mean']:.2f} "
            f"| {f['std']:.2f} | {f['min']:.1f} | {f['max']:.1f} | {r['npsh_margin_min']:.3f} "
            f"| {len(r['windows'])} |"
        )
    return out + ["", STABLE_D23, ""]


def section_wave(wave: list[dict[str, Any]]) -> list[str]:
    out = [
        "## 4 Wave-speed restraint psi and bulk modulus (transient engine, ESD closure of T1)",
        "",
    ]
    out += [
        "| psi | bulk modulus Pa | DN300 speed m/s | round trip s | peak at closure barg "
        "| time of peak s | peak before the first window barg | first window s |"
    ]
    out += ["| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in wave:
        out.append(
            f"| {r['psi']:g} | {r['bulk_pa']:.1e} | {r['speeds']['300']:.0f} "
            f"| {r['round_trip_s']:.3f} | {r['peak_at_closure_barg']:.2f} | {r['t_peak_s']:.3f} "
            f"| {r['valid_peak_barg']:.2f} | {r['first_phase_window_s']:.2f} |"
        )
    return out + ["", STABLE_WAVE, ""]


def section_check_valve(t3: dict[str, Any]) -> list[str]:
    out = ["## 5 Check-valve delay 0.05, 0.3, 1 s (pump stop, T3)", ""]
    out += ["| delay s | first window s | closure of the check valve s | reverse volume m3 |"]
    out += ["| --- | --- | --- | --- |"]
    for r in t3["T3_pump_stop"]:
        out.append(
            f"| {r['delay_s']:g} | {r['first_phase_window_s']:.2f} | {r['closed_at_s']:.2f} "
            f"| {r['reverse_volume_m3']:.4f} |"
        )
    return out + ["", STABLE_CHECK, ""]


def section_d50(d50: dict[str, Any]) -> list[str]:
    out = ["## 6 D50 sweeps", ""]
    out += ["### Fitting loss multiplier 0.5, 1, 2, 3", ""]
    out += ["| multiplier | flow 9 m | margin 9 m | flow 1.8 m | margin 1.8 m | ESD peak barg |"]
    out += ["| --- | --- | --- | --- | --- | --- |"]
    for r in d50["k_multiplier"]:
        a, b = r["tk101_9.0"], r["tk101_1.8"]
        out.append(
            f"| {r['mult']:g} | {a['flow_m3h']:.1f} | {a['margin']:.2f} | {b['flow_m3h']:.1f} "
            f"| {b['margin']:.3f} | {r['esd']['peak_at_closure_barg']:.2f} |"
        )
    out += ["", "### Meter loss K 0.5, 1, 2, 4", ""]
    out += ["| meter K | flow 9 m | margin 9 m | flow 1.8 m | margin 1.8 m | ESD peak barg |"]
    out += ["| --- | --- | --- | --- | --- | --- |"]
    for r in d50["meter_k"]:
        a, b = r["tk101_9"], r["tk101_1.8"]
        out.append(
            f"| {r['meter_k']:g} | {a['flow_m3h']:.1f} | {a['npsh_margin_ratio']:.2f} "
            f"| {b['flow_m3h']:.1f} | {b['npsh_margin_ratio']:.3f} "
            f"| {r['esd']['peak_at_closure_barg']:.2f} |"
        )
    out += ["", "### Pump curve steepness k = 8, 12, 16 m (duty point kept by recalibrating c)", ""]
    out += ["| k m | shutoff ratio | c m | flow 9 m | margin 9 m | flow 1.8 m | margin 1.8 m |"]
    out += ["| --- | --- | --- | --- | --- | --- | --- |"]
    for r in d50["pump_steepness"]:
        a, b = r["tk101_9"], r["tk101_1.8"]
        out.append(
            f"| {r['k_m']:g} | {r['shutoff_ratio']:.2f} | {r['c_recalibrated_m']:.4f} "
            f"| {a['flow_m3h']:.1f} | {a['npsh_margin_ratio']:.2f} | {b['flow_m3h']:.1f} "
            f"| {b['npsh_margin_ratio']:.3f} |"
        )
    out += ["", "### NPSH3 coefficient 2.5, 4, 6 m", ""]
    out += [
        "| NPSH3 m | margin at 9 m | margin at 1.8 m | flow m3/h |",
        "| --- | --- | --- | --- |",
    ]
    for r in d50["npsh3"]:
        a, b = r["tk101_9"], r["tk101_1.8"]
        out.append(
            f"| {r['npsh3_m']:g} | {a['npsh_margin_ratio']:.2f} | {b['npsh_margin_ratio']:.3f} "
            f"| {a['flow_m3h']:.1f} |"
        )
    return out + ["", STABLE_D50, ""]


def main() -> None:
    lines = ["# D42 study: the sensitivity sweeps as one report", ""]
    lines += [
        "Each section says what was varied, what was measured, which results are stable and "
        "which depend on the selection. All values are synthetic design selections (D48).",
        "",
    ]
    lines += section_windows(load("d42_d22"), load("d42_d53"), load("d42_d58"))
    lines += section_d23(load("d42_d23"))
    lines += [
        "## 3 D39 dead-leg time constant 10, 60, 300 s",
        "",
        "Not rerun; see `local/results/d39_sweep.md`. Depends strongly on the selection, on "
        "one tag (PT-001 after an isolation).",
        "",
    ]
    lines += (
        section_wave(load("d42_wave"))
        + section_check_valve(load("t3"))
        + section_d50(load("d42_d50"))
    )
    with open("local/results/d42_study.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("ok")


if __name__ == "__main__":
    main()
