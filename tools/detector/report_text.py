"""Sections of the results report, written around the tables built by the report module."""

from __future__ import annotations

from typing import Any

import report as r

PLAN_COMMIT = "a29af6d"
HARNESS_COMMIT = "41e4ba4"
REGISTERED = ["C1", "C2a", "C2b", "C3", "C4"]


def head(res: dict[str, Any], meta: dict[str, Any]) -> list[str]:
    """Title and the facts of the run."""
    g, w = meta["guard"], meta["worker_guard"]
    opens = ", ".join(f"{k}: {v}" for k, v in g["allowed_opens_by_folder"].items())
    return [
        "# Detector experiment: results", "",
        "All data are simulated from one synthetic terminal. Nothing here is a statement about "
        "a real plant.", "",
        "| Item | Value |", "|---|---|",
        f"| Plan | `{PLAN_COMMIT}`, with Amendment 1 committed together with the harness |",
        f"| Harness | `{HARNESS_COMMIT}`; diagnostics and report modules come with this report |",
        f"| Validation | {res['windows']} windows with a valid label, {res['faulty']} faulty, "
        f"prevalence {res['prevalence']:.4f} |",
        f"| Fit set | {meta['train_windows']} fault-free train windows |",
        "| Seed | 20261108 for the random score, the bootstrap, the shuffles |",
        f"| Test split | not opened. The audit hook allowed these opens in the main process "
        f"({opens}), and {w['allowed_opens']} raw-observation files of train and validation "
        f"episodes in the workers. Rejected attempts: {len(g['rejected'])} in the main process, "
        f"{w['rejected']} in the workers |",
        f"| Raw rows against summaries | the mean of the raw 300 s rows equals the window summary "
        f"mean (largest absolute difference {meta['raw_mean_vs_summary_max_abs_diff']}) |",
        f"| Missing values | {meta['missing_share_validation']:.4f} of the validation columns |",
        f"| Run time | scoring stage {meta['seconds']:.0f} s |", "",
    ]  # fmt: skip


def results_sections(res: dict[str, Any]) -> list[str]:
    """Registered candidates, fault types and the sensitivity."""
    out = ["## 2. Registered candidates and baselines (validation)", ""]
    out += r.main_table(res, [*r.BASE, *REGISTERED])
    out += ["False-alarm rate and recall use the cross-fitted 5% target. Intervals are 95% "
            "bootstrap intervals over whole episodes (1,000 resamples).", ""]  # fmt: skip
    sh = res["C0_shipped_threshold"]
    out += [f"At its shipped threshold ({sh['threshold']:.4f}) C0 alarms on {sh['far']:.3f} of "
            f"fault-free windows and on {sh['recall']:.3f} of faulty ones.", ""]  # fmt: skip
    out += ["## 3. Recall by fault type at the 5% false-alarm target", ""]
    out += r.type_table(res, ["C0", *REGISTERED])
    out += ["## 4. Sensitivity: temperature level removed (exploratory, outside the stop rule)", ""]
    out += r.main_table(res, ["C1s", "C2as", "C2bs", "C4s"])
    out += [
        "C3 does not use temperature and is not repeated. The sensitivity was declared in "
        "Amendment 1 (corrected by Amendment 2) because the temperature mixture of train "
        "fault-free windows and of validation windows differs.", "",
    ]  # fmt: skip
    return out


def controls_section(res: dict[str, Any]) -> list[str]:
    """Shuffle, matched position and constant-column controls."""
    out = ["## 5. Pre-registered controls", "", "Shuffle test (200 permutations, mean and 2.5% "
           "to 97.5% range):", ""]  # fmt: skip
    out += r.shuffle_table(res)
    out += ["Matched-position control: the matched-stage AUROC column of the tables above, for "
            "every candidate and for C0.", ""]  # fmt: skip
    flagged = res["constant_columns"]["flagged_columns"]
    out += ["Columns taking fewer than 3 distinct values or having zero variance across faulty "
            f"windows: {', '.join(flagged) if flagged else 'none'}.", ""]  # fmt: skip
    return out + r.contributors(res) + [
        "For C1 and C2 the temperature tags are among the largest contributors: those scores are "
        "partly driven by the different temperature mixture of validation. For C3 the "
        "contributors are physical residuals (pump head, discharge loss, mass balance).",
        "",
    ]  # fmt: skip


def posthoc_section(res: dict[str, Any], diag: dict[str, Any]) -> list[str]:
    """Controls added after the results were seen."""
    mix = diag["mix"]
    names = [*r.BASE[2:], *REGISTERED]
    sr = diag["seen_recall"]
    total = {t: res["C3"]["alarms_at_5pct_far"]["recall_by_type"][t]["n"] for t in sr["C3"]}
    out = ["## 6. Post-hoc controls (added after seeing the results)", "",
           "The first results were stronger than expected, so three controls were added. They "
           "take no part in the stop rule.", "",
           "**Regime coverage.** "
           f"{mix['faulty_in_rare_regime']} of the faulty validation windows lie in an operating "
           f"regime with fewer than 200 fault-free train windows, against "
           f"{mix['fault_free_in_rare_regime']} fault-free windows. Almost all restriction and "
           f"misrouting windows are among them (restriction in seen regimes: "
           f"{sr['C3']['restriction'][1]} of {total['restriction']}; "
           f"misrouting: {sr['C3']['misrouting'][1]} of {total['misrouting']}). A detector that "
           "reacts to an unusual regime would look good on exactly these windows, and this "
           "data cannot tell it from a physical detection, because no fault-free validation "
           "window is in such a regime. "
           "So the restriction and misrouting recalls in section 3 are not interpretable.", "",
           "**Placebo.** Windows at positions 1 to 5, before any fault can occur, are labelled by "
           "whether their episode contains a fault later. A score that reads the kind of episode "
           "would separate them.", "",
           ]  # fmt: skip
    out += r.seen_table(diag, names)
    out += [
        "**Recall by type among windows in seen regimes** (alarmed / total, same 5% target):",
        "",
    ]
    out += r.seen_recall_table(diag, ["C3", "C4", "C2b"])
    out += ["**Matched-stage AUROC within each temperature class:**", ""]
    return out + r.temperature_table(diag, ["C0", "C2b", "C3", "C4"])


def recall_text(diag: dict[str, Any]) -> str:
    """Recall by type in seen regimes for C3 and C4, as counts and percentages."""
    parts = []
    for t in ("pump", "stuck", "drift", "bias", "leak"):
        cells = []
        for n in ("C3", "C4"):
            hit, tot = diag["seen_recall"][n][t]
            cells.append(f"{n} {hit}/{tot} ({100 * hit / tot:.0f}%)")
        parts.append(f"{t} " + ", ".join(cells))
    return "; ".join(parts)


def conclusion_section(res: dict[str, Any], diag: dict[str, Any]) -> list[str]:
    """What is and is not supported, and the deviations."""
    seen = diag["seen_regime"]
    c3, c4 = seen["C3"], seen["C4"]
    return (
        [
            "## 7. What is supported and what is not",
            "",
            "Supported, for this simulated terminal and these validation windows:",
            "",
            f"- Fault-free-trained physics residuals (C3) and their fixed fusion with PCA and "
            f"per-tag scores (C4) separate faulty from fault-free windows far better than the "
            f"current forest and the trivial baselines, also at matched episode stage "
            f"({r.ci(res['C3']['discrimination']['matched_auroc'])} and "
            f"{r.ci(res['C4']['discrimination']['matched_auroc'])}).",
            f"- The advantage survives restricting to windows in regimes seen in fault-free "
            f"training: C3 AP {r.ci(c3['ap_ci'])}, matched {r.ci(c3['matched_ci'])}; C4 AP "
            f"{r.ci(c4['ap_ci'])}, matched {r.ci(c4['matched_ci'])}.",
            "- The placebo AUROC of every model is near 0.5: the scores do not read the kind of "
            "episode before a fault begins.",
            f"- At 5% false alarms, among windows in seen regimes (C3, C4): {recall_text(diag)}.",
            "",
        ]
        + unsupported_lines()
        + deviation_lines()
    )


def unsupported_lines() -> list[str]:
    """What the results do not support."""
    return [
        "Not supported:", "",
        "- That the current forest has any skill here: its AP interval contains the prevalence "
        "and its matched-stage AUROC interval contains 0.5.",
        "- That per-tag baselines with CUSUM (C1) or PCA on all tags (C2a) work: C1 fails the "
        "stop rule, C2a and C2b are driven by tank levels and temperatures and are weak on "
        "seen regimes.",
        "- Anything about restriction and misrouting faults (section 6), and about 45 degrees C "
        "(only 18 faulty windows; matched AUROC much lower).",
        "- Any claim on real plants, other terminals, or the test split, which stays untouched "
        "for one confirming run. Window-level detection is not localisation: nothing here "
        "names the faulty asset.",
        "- Thresholds are cross-fitted on validation fault-free windows; the intervals do not "
        "include that uncertainty, nor the in-sample calibration of the C4 p-values. The "
        "tag-to-location mapping used by C3 follows the tag names and is an assumption.", "",
    ]  # fmt: skip


def deviation_lines() -> list[str]:
    """Deviations from the plan."""
    return [
        "## 8. Deviations from the plan", "",
        "- Amendment 1 (temperature mixture differs between train and validation; its claim that "
        "40 degrees C is absent from train was wrong and is corrected in Amendment 2) added the "
        "four sensitivity variants; it was committed before any label-based metric was computed.",
        "- Section 6 was added after the results were seen, for the reason given there.",
        "- The plan said C1 runs on raw series; the raw rows come from the same window as the "
        "summary and the CUSUM therefore uses more input than the Agent 2 request carries.",
        "- Ties in C4 (p-values cannot fall below 1/(n+1)) make part of its score range flat; "
        "ties are handled by average ranks.", "",
    ]  # fmt: skip


def reproduction() -> list[str]:
    """Exact commands."""
    cmd = ".venv/bin/python tools/detector/run.py"
    rel = "data/reference_release_v2/verum_reference_v2"
    return [
        "## 9. Reproduction", "", "```bash",
        "git switch detector-experiment",
        f"{cmd} score --release {rel} --work WORK",
        f"{cmd} evaluate --work WORK --out WORK/results.json",
        f"{cmd} diagnose --release {rel} --work WORK --out WORK/diagnostics.json",
        f"{cmd} report --work WORK --results WORK/results.json "
        "--diagnostics WORK/diagnostics.json --out reports/detector_experiment_results.md",
        ".venv/bin/pytest tests/regression/test_detector_experiment.py -q", "```", "",
        "Seed 20261108 for every random draw. The scoring stage takes about two minutes, the "
        "evaluation about 20 seconds.", "",
    ]  # fmt: skip


def assemble(res: dict[str, Any], diag: dict[str, Any], meta: dict[str, Any]) -> str:
    """The whole report."""
    lines = head(res, meta) + ["## 1. Summary", ""] + r.summary_lines(res, diag)
    lines += results_sections(res) + controls_section(res) + posthoc_section(res, diag)
    lines += conclusion_section(res, diag) + reproduction()
    return "\n".join(lines)
