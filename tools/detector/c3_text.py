"""The characterisation document for C3 alone: operating points, signatures and feasibility.

Input is one work folder with the results of the characterisation, the commanded-mode counts and
the parameter summary. Output is the markdown text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from regime_report import table
from signature import NAMES
from windows import FAULT_TYPES

TAGS = {"oof": "grouped CV (out of fold, train)", "val": "validation (held-out combinations)"}
POLICY_NAMES = ["1/1", "2/3", "3/5"]


def f3(v: list[float]) -> str:
    """Point value and interval."""
    return f"{v[0]:.3f} ({v[1]:.3f} to {v[2]:.3f})"


def load_json(path: Path) -> Any:
    """Parse a JSON file."""
    return json.loads(path.read_text())


def window_section(res: dict[str, Any]) -> list[str]:
    """Section 2.1: the window-level reference."""
    head = ["set", "false-alarm rate", "false alarms per day", "recall, all faults",
            "AP", "matched-stage AUROC"]  # fmt: skip
    rows, types = [], []
    for tag, title in TAGS.items():
        w = res[tag]["window_level"]["C3"]
        a, d = w["alarms_at_5pct_far"], w["discrimination"]
        rows.append([title, f3(a["far"]), w["false_alarms_per_day"], f3(a["recall_all"]),
                     f3(d["ap"]), f3(d["matched_auroc"])])  # fmt: skip
    for t in FAULT_TYPES:
        cells = [res[tag]["window_level"]["C3"]["alarms_at_5pct_far"]["recall_by_type"][t]
                 for tag in TAGS]  # fmt: skip
        types.append(
            [t, cells[0]["n"], f3(cells[0]["recall"]), cells[1]["n"], f3(cells[1]["recall"])]
        )
    return [
        "### 2.1 Window level at the reference threshold",
        "",
        "Threshold: 95th percentile of fault-free window scores of the other parity fold "
        "(5% window false-alarm target).",
        "",
        *table(head, rows),
        "**Recall by fault type:**",
        "",
        *table(
            ["fault type", "OOF windows", "OOF recall", "validation windows", "validation recall"],
            types,
        ),  # fmt: skip
    ]


def policy_rows(res: dict[str, Any], tag: str) -> list[list[Any]]:
    """One row per policy with the episode-level headline numbers."""
    rows = []
    for name in POLICY_NAMES:
        v = res[tag]["policies"][name]
        fa, de = v["false_alarms"], v["detection"]["all"]
        q = v["delay"]["quartiles_s"]
        rows.append([
            name, ", ".join(f"{t:.2f}" for t in v["thresholds"]),
            f"{fa['alarmed']}/{fa['fault_free_episodes']} ({f3(fa['share'])})",
            f3(fa["window_rate"]), f3(fa["per_day"]),
            f"{de['detected']}/{de['n']} ({f3(de['rate'])})",
            " / ".join(f"{x:.0f}" for x in q), v["delay"]["never"],
        ])  # fmt: skip
    return rows


def policy_section(res: dict[str, Any]) -> list[str]:
    """Section 2.2."""
    head = ["policy", "threshold(s)", "fault-free episodes with any alarm",
            "alarm rate on fault-free windows", "false alarms per day",
            "faulty episodes detected", "delay quartiles (s)", "never detected"]  # fmt: skip
    out = [
        "### 2.2 Alarm policies (k of the last n windows)",
        "",
        "Threshold per policy: the smallest value with at most 5% of fault-free calibration "
        "episodes alarming, using the scores of other folds (out of fold) or the out-of-fold "
        "train scores (validation). Out of fold there is one threshold per fold. The thresholds "
        "were fixed by this rule before any result was seen; all three policies are shown.",
        "",
    ]
    for tag, title in TAGS.items():
        out += [f"**{title}:**", "", *table(head, policy_rows(res, tag))]
    out += type_tables(res)
    return out


def type_tables(res: dict[str, Any]) -> list[str]:
    """Detection rate and window recall by fault type for the three policies."""
    out = ["**Episode detection rate by fault type** (type of the first faulty window):", ""]
    for tag, title in TAGS.items():
        rows = []
        for t in FAULT_TYPES:
            cells = [res[tag]["policies"][p]["detection"][t] for p in POLICY_NAMES]
            rows.append([t, cells[0]["n"], *[f3(c["rate"]) for c in cells]])
        out += [f"*{title}:*", "", *table(["fault type", "episodes", *POLICY_NAMES], rows)]
    out += ["**Window recall by fault type** (share of faulty windows at which the policy "
            "is alarming):", ""]  # fmt: skip
    for tag, title in TAGS.items():
        rows = []
        for t in FAULT_TYPES:
            cells = [res[tag]["policies"][p]["window_recall"][t] for p in POLICY_NAMES]
            rows.append([t, cells[0]["n"], *[f3(c["recall"]) for c in cells]])
        out += [f"*{title}:*", "", *table(["fault type", "windows", *POLICY_NAMES], rows)]
    return out


def control_section(res: dict[str, Any]) -> list[str]:
    """Section 2.3."""
    head = ["set", "shuffle AP", "shuffle AUROC", "shuffle matched AUROC",
            "placebo matched AUROC", "constant columns"]  # fmt: skip
    rows = []
    for tag, title in TAGS.items():
        w = res[tag]["window_level"]
        sh = w["C3"]["shuffle"]
        flags = ", ".join(w["constant_columns"]) or "none"
        means = [f"{sh[k][0]:.3f}" for k in ("ap", "auroc", "matched")]
        rows.append([title, *means, f3(w["C3"]["placebo"]), flags])
    ep = []
    for tag, title in TAGS.items():
        for p in POLICY_NAMES:
            v = res[tag]["policies"][p]
            ep.append([title, p, f3(v["detection"]["all"]["rate"]),
                       " ".join(f"{x:.3f}" for x in v["shuffle_detection"]),
                       f3(v["placebo_rate_difference"])])  # fmt: skip
    return [
        "### 2.3 Controls",
        "",
        *table(head, rows),
        "Episode level: the shuffle gives the onsets of the faulty episodes to randomly chosen "
        "episodes (200 permutations; mean, 2.5%, 97.5%) and recomputes the detection rate; the "
        "placebo is the difference in alarming rate on fault-free windows at positions 1 to 5 "
        "between episodes that later contain a faulty window and episodes that never do.",
        "",
        *table(
            ["set", "policy", "detection rate", "shuffled detection rate", "placebo difference"], ep
        ),  # fmt: skip
    ]


def signature_section(res: dict[str, Any]) -> list[str]:
    """Section 3."""
    out = [
        "## 3. Residual signature matrix",
        "",
        "Each cell is: mean share in the score / fraction of windows in which the residual is "
        "the largest / fraction in which it exceeds its own 95th-percentile threshold from "
        "fault-free windows the model did not see. `none` is the fraction of windows in which "
        "all four residuals are zero (no top contributor). The fault-free row is the reference: "
        "its exceed fractions should sit near 0.05.",
        "",
    ]
    for tag, title in TAGS.items():
        rows = []
        for t, r in res[tag]["signature"].items():
            cells = [f"{r['share'][j]:.2f} / {r['top'][j]:.2f} / {r['exceed'][j]:.2f}"
                     for j in range(4)]  # fmt: skip
            rows.append([t, r["n"], *cells, f"{r['none']:.2f}"])
        out += [f"**{title}:**", "", *table(["fault type", "windows", *NAMES, "none"], rows)]
    cls = res["classification"]
    rows = [[t, c["oof"], c["val"], c["verdict"]] for t, c in cls.items()]
    return out + [
        "**Classification** (rule fixed in the plan: distinct when the largest exceed fraction "
        "is at least 0.30 and at least twice the second; none when it is below 0.15; shared "
        "otherwise; a type is called distinct only if both sets agree):",
        "",
        *table(["fault type", "out of fold", "validation", "verdict"], rows),
    ]


def input_rows() -> list[list[str]]:
    """Section 4.1: every input of C3 and whether a request carries it."""
    yes = "yes, summary_v1 signal field"
    return [
        ["FT-001, FT-201", "window `mean`", "R1 mass balance", yes],
        ["LT-101, LT-102, LT-103", "window `slope_per_s`", "R1 storage term", yes],
        ["PT-001 and FT-001 `mean`", "window `mean`", "R4 receipt line", yes],
        [
            "PT-201, PT-202A, PT-202B, PT-203",
            "window `mean`",
            "R2 pump head, R3 discharge loss",
            yes,
        ],
        [
            "P-101A, P-101B",
            "`latest_value` (observed run state)",
            "pump-state selector of R2, R3",
            "yes, boolean signal",
        ],  # fmt: skip
        [
            "atmosphere, temperature set point, flow set point",
            "episode conditions",
            "selects the R4 fit by regime",
            "no",
        ],  # fmt: skip
        ["fitted coefficients and scales", "constants", "all residuals", "no, a pinned file"],
        ["alarm thresholds", "constants", "all policies", "no, a pinned file"],
        ["scores of the previous windows", "history", "2/3 and 3/5 policies", "no"],
    ]


def _inputs_part(params: dict[str, Any]) -> list[str]:
    """Section 4.1."""
    return [
        "## 4. Runtime feasibility (read-only)",
        "",
        "### 4.1 Inputs of C3 against an Agent 2 request",
        "",
        *table(["tag(s)", "quantity", "used by", "carried by a request"], input_rows()),
        "Not used by C3: raw 300 s rows (the `sequence_v1` representation), arrival ages, "
        "row and sample counts, quality flags, minimum and maximum, standard deviation. The "
        "CUSUM of the first experiment used raw rows; C3 does not.",
        "",
        "- The contract request holds the same 30 summary signals as the role-view records the "
        "results were computed on, with the same fields; the request input is the observation "
        "summary and a forecast report, nothing else.",
        "- The Agent 2 code reads `input.observations.summary.signals` only, so it handles "
        "`summary_v1` and not `sequence_v1`. C3 needs `summary_v1`.",
        "- The summary mean and slope are computed over all measured samples of the window, "
        "including samples flagged suspect or bad (an example request shows a minimum of 0.11 "
        "beside a mean of 594.8). C3 reads them as they are, in every result above, and applies "
        "no quality screening. A missing statistic counts as no evidence.",
        "- C3 needs 12 of the 30 tags. The existing coverage gate of the forest (90% of the 30 "
        "tags) is not a gate for C3; which tags must be usable is a design decision that this "
        "work does not make.",
        "- **Missing from a request:** the set conditions, and the history of earlier scores. "
        f"{params['regime_specific_fits']} of the {params['fits']} fits are per set-condition "
        "regime (R4); without the conditions a request can only use the pooled R4 fit, the "
        "same fallback that already served 74.0% of validation windows under the new key "
        "(validation AP of C3 was 0.739 with the old key and 0.730 with the new one; "
        "`reports/detector_v2_results.md`, section 2.3). That "
        "is not a test of a pooled-only R4 and is not claimed as one. The k-of-n policies need "
        "the scores of the last n-1 windows of the same episode, which a single-window request "
        "does not carry; they need stored state or a request that attaches earlier windows.",
        "",
    ]


def _mapping_part(params: dict[str, Any]) -> list[str]:
    """Section 4.2."""
    fit, dec = params["tank_areas_fitted"], params["tank_areas_declared"]["TK-101"]
    return [
        "### 4.2 Pinned parameter file and the tag-to-location mapping",
        "",
        f"The fitted model holds {params['numbers']} numbers in {params['fits']} fits "
        f"(R2 {params['fits_by_residual']['R2']}, R3 {params['fits_by_residual']['R3']}, R4 "
        f"{params['fits_by_residual']['R4']}) plus the mass-balance coefficients: "
        f"{params['json_bytes']:,} bytes as JSON, plus one threshold per policy. It fits in a "
        "small pinned file, with the tag-to-role mapping written in the same file.",
        "",
        "How the mapping is derived: the declared reference gives 28 connections forming one "
        "line (receipt meter, receipt header, three tank branches, suction header, two pump "
        "branches, discharge header, delivery meter) and lists the 30 instruments with unit and "
        "sampling only. It gives no instrument location; the pressure transmitters appear as "
        "assets and in no connection. The mapping is therefore taken from the tag names: FT-001 "
        "receipt meter, FT-201 delivery meter, LT-10i tank TK-10i, PT-001 receipt line, PT-201 "
        "suction header, PT-202A and PT-202B discharge of pumps P-101A and P-101B, PT-203 "
        "discharge header.",
        "",
        f"What the data support: the fitted tank areas are {fit[0]}, {fit[1]} and {fit[2]} m2 "
        f"against {dec} m2 from the declared 30 m diameter, within 0.3%. That supports the "
        "level tags as tank inventory and the sign convention of FT-001 as inflow and FT-201 as "
        "outflow in R1. It does not tell the three tanks apart, since they are identical.",
        "",
        "What is unverified: that PT-201 sits on the suction header and PT-203 on the "
        "discharge header; that PT-202A belongs to pump A and PT-202B to pump B; that the "
        "pump-head and loss curves (empirical quadratic fits per pump state, valid inside the "
        "operating range seen in training) correspond to physical quantities. The reference "
        "carries no pump curve to compare with. These residuals are fitted to simulator data, "
        "so a good score is not independent validation.",
        "",
    ]


def feasibility_section(params: dict[str, Any]) -> list[str]:
    """Section 4: runtime feasibility, read-only."""
    return [*_inputs_part(params), *_mapping_part(params)]


MODE_HEAD = ["commanded mode", "episodes", "episodes with a fault", "most frequent faulty valves"]


def mode_rows(lineup: dict[str, Any]) -> list[list[Any]]:
    """Counts per commanded mode with the three most frequent faulty valves."""
    rows = []
    for mode, r in lineup["modes"].items():
        top = sorted(r["valve_faults"].items(), key=lambda kv: -kv[1])[:3]
        rows.append([mode, r["episodes"], r["with_fault"], ", ".join(f"{a} {n}" for a, n in top)])
    return rows


def _top_valve(r: dict[str, Any]) -> tuple[str, int, int]:
    valve, n = max(r["valve_faults"].items(), key=lambda kv: kv[1])
    return valve, n, sum(r["valve_faults"].values())


def example_sentence(lineup: dict[str, Any]) -> str:
    """The mode whose most frequent faulty valve carries the largest share of its valve faults."""
    rows = {m: _top_valve(r) for m, r in lineup["modes"].items() if r["valve_faults"]}
    mode = max(rows, key=lambda m: rows[m][1] / rows[m][2])
    valve, n, total = rows[mode]
    return f"in mode `{mode}`, valve `{valve}` carries {n} of the {total} valve faults"


def _availability_part(lineup: dict[str, Any]) -> list[str]:
    """Sections 5.1 and 5.2."""
    assoc = lineup["association"]
    return [
        "## 5. Commanded-lineup feasibility (read-only, nothing evaluated)",
        "",
        "### 5.1 Is the commanded state in a request?",
        "",
        "No. A request carries 30 observed signals. Eleven of them are valve contact states "
        "(`XV-*`), two are pump run states and three are level switches; all are what the plant "
        "reports, not what was commanded. No field of the request, of the contract or of the "
        "declared reference is named or described as a commanded state, lineup or set point. "
        "The commanded operating mode (for example `RECEIVE_101_DELIVER_102_A`) exists in the "
        "episode label file, which holds the campaign strata and is not available to an agent. "
        "The reference also declares the limit `contact_is_not_true_valve_position`: a contact "
        "state is not the true valve position.",
        "",
        "### 5.2 Is it independent of the injected fault?",
        "",
        "No, in two ways. The observed contact states change with some faults (restriction "
        "with visible position and misrouting act on valve positions; the regime audit in "
        "`reports/detector_v2_regime_audit.md` shows it). The commanded mode is a campaign "
        "stratum, and the faults are not placed independently of it: among "
        f"{lineup['episodes']:,} episodes with eligible windows the association of mode with the "
        f"valve a fault is on is Cramer's V {assoc['mode_vs_faulty_valve']}, and with having any "
        f"fault {assoc['mode_vs_any_fault']}. For example, {example_sentence(lineup)}. The "
        "mode `RECEIVE_101_102` does not appear among the episodes with an eligible window.",
        "",
        *table(MODE_HEAD, mode_rows(lineup)),
    ]


def _check_part() -> list[str]:
    """Sections 5.3 and 5.4."""
    return [
        "### 5.3 How a commanded-against-observed check would be defined",
        "",
        "For each valve v in the lineup, the commanded state c_v(t) is open or closed according "
        "to the active mode, and the observed state o_v(t) is the contact `latest_value` in the "
        "window. The mismatch is m_v(t) = 1 when o_v differs from c_v. The window evidence is "
        "the set of mismatched valves, with a debounce (for example the k-of-n rule above) and "
        "with windows inside a stated valve travel time after a commanded change excluded. It "
        "would act on the 11 valve contacts and nothing else.",
        "",
        "### 5.4 What could make it leak the label",
        "",
        "- If the commanded state is taken from the label file (the mode stratum), it is truth "
        "side information, and the check would be using the campaign design, not an input.",
        "- If it is reconstructed from the observed states of the same episode (for instance "
        "the most common state), the fault contaminates the reference it is compared with.",
        "- For misrouting and for restriction with a visible position, the fault is defined as "
        "a valve not in its commanded state. The check would then restate the label, and a high "
        "recall on those two types would be by construction and not a detection result.",
        "- A valve fault that leaves the contact unchanged (restriction by obstruction) cannot "
        "be seen by the check at all.",
        "- Mode is associated with where faults are placed (Cramer's V above), so a model fed "
        "the mode can learn the campaign's placement prior.",
        "- A contact that disagrees with the true position (the declared limit) would produce "
        "mismatches without a process fault, and valve travel after a commanded change would "
        "produce them in the switch-type episodes.",
        "",
        "Not evaluated: no model was run and no recall or false-alarm number is given for it.",
        "",
    ]


def lineup_section(lineup: dict[str, Any]) -> list[str]:
    """Section 5: commanded lineup feasibility, read-only."""
    return [*_availability_part(lineup), *_check_part()]


def reading_section(res: dict[str, Any]) -> list[str]:
    """Section 6: how to read the numbers."""
    over = [res["val"]["policies"][p]["false_alarms"]["share"] for p in POLICY_NAMES]
    return [
        "## 6. Reading the numbers",
        "",
        "- Calibration does not transfer fully to validation: the share of fault-free "
        f"validation episodes with an alarm is {over[0][0]:.3f}, {over[1][0]:.3f} and "
        f"{over[2][0]:.3f} for the three policies against the 0.05 target; the interval of "
        "the 1/1 policy lies above 0.05. Out of fold the shares sit at the target.",
        "- The same shift shows in the signature matrix: on validation, fault-free windows "
        "exceed the thresholds of R2 and R3 about 9% of the time against 5% by construction.",
        "- Episodes have 2 to 12 eligible windows, median 5. A policy that needs three "
        "exceedances (3/5) cannot alarm in an episode with fewer than three eligible windows, "
        "and the delay of any policy is bounded by the 300 s grid.",
        "- A k-of-n policy needs k exceedances in the last n windows, so its window recall is "
        "lower than 1/1 at the first faulty windows of an episode even when the episode "
        "detection rate is higher (pump faults: window recall 1.00 for 1/1 and lower for 2/3 "
        "and 3/5, episode detection about 0.9 or more for all).",
        "- The episode-level placebo differences are close to zero. The one interval that "
        "excludes zero (validation, 3/5) is negative: episodes that later contain a fault "
        "alarm slightly less at positions 1 to 5, which is not the direction of a leak.",
        "- Detection means alarming at one or more faulty-labelled windows of the episode. A "
        "false alarm before the onset in a faulty episode is counted in the window alarm rate "
        "of fault-free windows, not in the fault-free episode count.",
        "- The signature matrix is descriptive. Misrouting has 9 train and 15 validation "
        "windows (2 and 3 episodes); its row cannot support a conclusion.",
        "- Thresholds for the out-of-fold evaluation use the out-of-fold scores of the other "
        "folds; those scores come from models whose fit data included the evaluated fold's "
        "fault-free windows. Only fault-free scores are used and no label of the evaluated "
        "fold, but it is not a fully nested calibration.",
        "- C3 is fitted to simulator data and its parts are empirical fits; tests of a reduced "
        "model are not independent validation. The test split was not opened.",
        "",
    ]


def _window_line(res: dict[str, Any]) -> str:
    o, v = (res[t]["window_level"]["C3"] for t in ("oof", "val"))
    return (
        "- Window level at a 5% window false-alarm target: recall "
        f"{f3(o['alarms_at_5pct_far']['recall_all'])} out of fold and "
        f"{f3(v['alarms_at_5pct_far']['recall_all'])} on validation, "
        f"{o['false_alarms_per_day']} and {v['false_alarms_per_day']} false alarms per day."
    )


def _policy_line(res: dict[str, Any]) -> str:
    def rate(tag: str, p: str) -> float:
        return float(res[tag]["policies"][p]["detection"]["all"]["rate"][0])

    def per_day(p: str) -> float:
        return float(res["oof"]["policies"][p]["false_alarms"]["per_day"][0])

    detect = "; ".join(f"{p} {rate('oof', p):.2f} / {rate('val', p):.2f}" for p in POLICY_NAMES)
    days = ", ".join(str(per_day(p)) for p in POLICY_NAMES)
    return (
        "- Policies at a 5% fault-free-episode target, detection rate of faulty episodes "
        f"(out of fold / validation): {detect}. False alarms per day out of fold: {days}."
    )


def summary(res: dict[str, Any], params: dict[str, Any]) -> list[str]:
    """Section 1."""
    cls = res["classification"]
    distinct = [
        f"{t} ({c['verdict'].split()[-1]})" for t, c in cls.items() if c["verdict"].startswith("d")
        and c["verdict"] != "disagree"
    ]  # fmt: skip
    differ = [t for t, c in cls.items() if c["verdict"] == "disagree"]
    return [
        "# C3 alone: operating characterisation, residual signatures, feasibility", "",
        "C3 is the topology residual detector of the plan with the operator-set condition key. "
        "C1, C2, C4 and every fusion are dropped. Protocol: section 13 of the experiment "
        "plan, committed before this stage was run.", "",
        "## 1. Summary", "",
        _window_line(res), _policy_line(res),
        f"- Distinct residual signatures in both sets: {', '.join(distinct) or 'none'}. "
        f"Classification differs between the sets for {', '.join(differ) or 'none'}; the other "
        "types share residuals.",
        "- Runtime: every input except the set conditions and the alarm history is in a "
        f"summary_v1 request; the fitted model is {params['numbers']} numbers "
        f"({params['json_bytes']:,} bytes).",
        "- Commanded lineup: not in a request, and not independent of where faults are placed. "
        "Nothing was evaluated.", "",
    ]  # fmt: skip


def deviations_section() -> list[str]:
    """Section 7."""
    return [
        "## 7. Deviations from the plan",
        "",
        "- Parts 3 and 4 were registered as read-only. Two small computations support them and "
        "evaluate nothing: C3 was fitted once on all fault-free train windows to count its "
        "parameters and compare the tank areas with the declared geometry, and the label files "
        "of train and validation episodes were tabulated by commanded mode. Both go through the "
        "same audit hook; no score of a held-out window was computed for them.",
        "- The window-level reference, shuffle and placebo of the C3 score reuse the "
        "evaluation code of the second stage unchanged.",
        "- Nothing was tuned on the signature matrix or on the policy results.",
        "",
    ]


def render(work: Path) -> str:
    """The whole document."""
    res = load_json(work / "results.json")
    params = load_json(work / "params.json")
    lineup = load_json(work / "lineup.json")
    lines = [
        *summary(res, params), "## 2. Operating characterisation", "",
        *window_section(res), *policy_section(res), *control_section(res),
        *signature_section(res), *feasibility_section(params), *lineup_section(lineup),
        *reading_section(res), *deviations_section(),
    ]  # fmt: skip
    return "\n".join(lines)
