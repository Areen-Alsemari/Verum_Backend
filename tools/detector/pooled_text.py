"""The document for the pooled-R4 comparison, the input check and the stress test of C3.

Input is one work root holding the saved results of the per-regime characterisation, of the
pooled characterisation, of the grouped-CV systems, of the stress test and of the input check.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv_eval
import numpy as np
import signature as sig
from c3_text import POLICY_NAMES, TAGS, f3
from input_check import field_list
from regime_report import table
from windows import FAULT_TYPES


def load_json(path: Path) -> Any:
    """Parse a JSON file."""
    return json.loads(path.read_text())


def window_rows(a: dict[str, Any], b: dict[str, Any], diff: dict[str, Any]) -> list[list[Any]]:
    """Window-level metrics of both versions and the paired difference, per set."""
    rows = []
    for tag, title in TAGS.items():
        for name, res in (("per-regime R4", a), ("pooled R4", b)):
            w = res[tag]["window_level"]["C3"]
            al, d = w["alarms_at_5pct_far"], w["discrimination"]
            rows.append([title, name, f3(d["ap"]), f3(d["matched_auroc"]), f3(al["far"]),
                         f3(al["recall_all"])])  # fmt: skip
        pd = diff[tag]
        rows.append(
            [title, "pooled minus per-regime", f3(pd["ap"]), f3(pd["matched_auroc"]), "", ""]
        )
    return rows


def type_rows(a: dict[str, Any], b: dict[str, Any], tag: str) -> list[list[Any]]:
    """Recall by fault type at the 5% window target, per-regime next to pooled."""
    rows = []
    for t in FAULT_TYPES:
        ra = a[tag]["window_level"]["C3"]["alarms_at_5pct_far"]["recall_by_type"][t]
        rb = b[tag]["window_level"]["C3"]["alarms_at_5pct_far"]["recall_by_type"][t]
        rows.append([t, ra["n"], f3(ra["recall"]), f3(rb["recall"])])
    return rows


def policy_rows(a: dict[str, Any], b: dict[str, Any], tag: str) -> list[list[Any]]:
    """The three policies, per-regime next to pooled."""
    rows = []
    for p in POLICY_NAMES:
        for name, res in (("per-regime", a), ("pooled", b)):
            v = res[tag]["policies"][p]
            fa, de = v["false_alarms"], v["detection"]["all"]
            rows.append([p, name, f"{fa['share'][0]:.3f}", fa["per_day"][0], f3(de["rate"]),
                         f"{v['delay']['quartiles_s'][1]:.0f}", v["delay"]["never"]])  # fmt: skip
    return rows


def controls_rows(b: dict[str, Any]) -> list[list[Any]]:
    """Shuffle and placebo of the pooled version."""
    rows = []
    for tag, title in TAGS.items():
        w = b[tag]["window_level"]["C3"]
        sh = w["shuffle"]
        ep = [f"{p}: {' '.join(f'{x:.3f}' for x in b[tag]['policies'][p]['shuffle_detection'])}"
              for p in POLICY_NAMES]  # fmt: skip
        plc = [f"{p}: {f3(b[tag]['policies'][p]['placebo_rate_difference'])}" for p in POLICY_NAMES]
        rows.append([title, f"{sh['ap'][0]:.3f} / {sh['auroc'][0]:.3f} / {sh['matched'][0]:.3f}",
                     f3(w["placebo"]), "; ".join(ep), "; ".join(plc)])  # fmt: skip
    return rows


def pooled_section(root: Path) -> list[str]:
    """Section 2."""
    a, b = load_json(root / "c3" / "results.json"), load_json(root / "c3p4" / "results.json")
    cv = root / "cv"
    diff = {t: cv_eval.compare_systems(cv / "B0", cv / "P4", t, "C3") for t in TAGS}
    head = ["set", "version", "AP", "matched-stage AUROC", "FAR at 5% target", "recall"]
    out = [
        "## 2. Pooled R4 against the per-regime version",
        "",
        "Same folds, same fits for R1 to R3, same thresholds. Pooled R4 is one quadratic of "
        "PT-001 on FT-001 mean for all windows; the set conditions are not read.",
        "",
        *table(head, window_rows(a, b, diff)),
    ]
    for tag, title in TAGS.items():
        rows = type_rows(a, b, tag)
        out += [f"**Recall by fault type at the 5% window target, {title}:**", ""]
        out += table(["fault type", "windows", "per-regime", "pooled"], rows)
    head = ["policy", "version", "fault-free episodes alarmed", "false alarms per day",
            "faulty episodes detected", "median delay (s)", "never detected"]  # fmt: skip
    for tag, title in TAGS.items():
        out += [f"**Alarm policies, {title}:**", "", *table(head, policy_rows(a, b, tag))]
    out += ["**Controls of the pooled version** (window shuffle: AP / AUROC / matched; "
            "placebo: matched AUROC at positions 1 to 5; episode shuffle detection rate: mean "
            "2.5% 97.5%; episode placebo: rate difference):", ""]  # fmt: skip
    head = ["set", "window shuffle", "window placebo", "episode shuffle", "episode placebo"]
    return out + table(head, controls_rows(b)) + [classification_note(a, b)]


def classification_note(a: dict[str, Any], b: dict[str, Any]) -> str:
    """Whether the signature classification changed."""
    same = a["classification"] == b["classification"]
    return (
        "The residual signature classification of section 3 of the C3 report is "
        + ("unchanged" if same else "changed")
        + " with pooled R4.\n"
    )


def input_section(inputs: dict[str, Any]) -> list[str]:
    """Section 3."""
    req, per = inputs["request"], inputs["perturbation"]
    rows = [[r["tag"], r["field"], r["unit"], "yes" if r["value_present"] else "no"]
            for r in req["fields"]]  # fmt: skip
    return [
        "## 3. Minimal-input check", "",
        f"The pooled C3 reads {len(field_list())} fields. The contract example request "
        f"(representation `{req['representation']}`) carries all of them with the expected unit: "
        f"fields present {req['all_present']}, units match {req['units_match']}.", "",
        *table(["tag", "summary field", "unit in the request", "present with a value"], rows),
        "Perturbation tests on the validation windows (largest absolute change of any score):", "",
        *table(["perturbation", "largest change"],
               [[k.replace("_", " "), v] for k, v in per.items()]),  # fmt: skip
        "The three perturbations are: every other statistic overwritten by 12345; the regime "
        "key set to arbitrary values and the order of the windows shuffled; each of the first "
        "100 windows scored alone. A change of exactly 0.0 means the scores depend on the "
        "twelve fields and on nothing else: no set condition, no earlier window, no other "
        "window of the set. The 1/1 window-level version therefore needs one `summary_v1` "
        "window and the pinned parameters. Scoring the example request itself gives "
        f"{req['example_score']} with residuals R1 to R4 {req['example_residuals']}.", "",
    ]  # fmt: skip


def stress_rows(res: dict[str, Any], tag: str) -> list[list[Any]]:
    """One row per stress setting of one set."""
    names = {
        "clean": "no perturbation", "missing_1": "1 tag missing", "missing_2": "2 tags missing",
        "missing_3": "3 tags missing", "noise_1": "noise 1x", "noise_2": "noise 2x",
        "noise_3": "noise 3x",
    }  # fmt: skip
    rows = []
    for key, label in names.items():
        v = res[tag][key]
        rows.append([label, f3(v["ap"]), f3(v["matched_auroc"]), f3(v["far"]), f3(v["recall"]),
                     f"{v['scorable_all']:.3f}", f"{v['scorable_faulty']:.3f}"])  # fmt: skip
    return rows


def stress_section(res: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    """Section 4."""
    head = ["setting", "AP", "matched-stage AUROC", "false-alarm rate", "recall",
            "windows scorable", "faulty windows scorable"]  # fmt: skip
    pumps = spec["pump_states"]
    share = {k: v["none"] / sum(v.values()) for k, v in pumps.items()}
    out = [
        "## 4. Stress test",
        "",
        "Nothing is refitted or tuned. The models are those of the folds and of the validation "
        "fit; the threshold is the clean one of the same set (OOF "
        f"{res['oof']['thresholds']}, validation {res['val']['thresholds']} for the two parity "
        "folds) and is applied unchanged to the perturbed scores. Unknown evidence is neither "
        "zero nor healthy: a residual with an unknown input drops out, and a window with no "
        "residual left cannot be scored, counts as not alarmed and ranks last. One seeded draw "
        "per setting; intervals are bootstrap over episodes. Definitions are in section 14.3 "
        "of the plan.",
        "",
    ]
    for tag, title in TAGS.items():
        out += [f"**{title}:**", "", *table(head, stress_rows(res, tag))]
    return out + [
        "Reading:", "",
        "- Missing tags lower recall and the false-alarm rate together, because fewer residuals "
        "enter the maximum. AP and matched-stage AUROC fall steadily with each missing tag.",
        "- Noise raises the false-alarm rate a great deal at the fixed threshold: noise on all "
        "ten inputs at once adds up in every residual, so the clean threshold is far too low "
        "for noisy windows. Recall rises for the same reason. The ranking measures (AP, matched "
        "AUROC) show the loss of discrimination without the threshold.",
        "- Unscorable windows appear only when every residual is lost. R2 and R3 apply only "
        "while a pump runs; windows with no pump running (train "
        f"{share['train']:.1%}, validation {share['validation']:.1%}) have R1 and R4 only, "
        "which read seven of the twelve inputs. That is why the scorable share is lower out of "
        "fold than on validation.",
        "- The noise scale is defined per input from the fault-free residual scale (plan "
        "section 14.3). It is a realism check, not an estimate of the real sensor noise, which "
        "this work does not know.", "",
    ]  # fmt: skip


def asset_rows(cv: Path) -> list[list[Any]]:
    """Exceed fractions of R1 to R4 for sensor-fault windows by faulty tag (descriptive)."""
    rows = []
    for tag in TAGS:
        d = np.load(cv / f"{tag}.npz")
        meta = json.loads((cv / f"{tag}_meta.json").read_text())
        y, parts = d["faulty"].astype(np.intp), d["parts_C3"]
        ref = np.load(cv / "oof.npz")
        if tag == "oof":
            thr = sig.fold_thresholds(parts, y, d["fold"].astype(np.intp))
        else:
            thr = sig.reference_thresholds(ref["parts_C3"], ref["faulty"].astype(np.intp), len(y))
        kind, who = np.asarray(meta["kind"]), np.asarray(meta["true_tag"])
        for k in ("bias", "drift", "stuck"):
            for asset in sorted(set(who[(kind == k) & (who != "")])):
                sel = (kind == k) & (who == asset)
                if sel.sum() >= 8:
                    ex = (parts[sel] > thr[sel]).mean(axis=0)
                    rows.append([tag, k, asset, int(sel.sum()), *[f"{v:.2f}" for v in ex]])
    return rows


def transfer(cv: Path) -> dict[str, float]:
    """False-alarm rate and recall on validation at the OOF fault-free 95th percentile."""
    o, v = np.load(cv / "oof.npz"), np.load(cv / "val.npz")
    thr = float(np.percentile(o["score_C3"][o["faulty"] == 0], 95))
    s, y = v["score_C3"], v["faulty"]
    return {"threshold": thr, "far": float((s[y == 0] > thr).mean()),
            "recall": float((s[y == 1] > thr).mean())}  # fmt: skip


def _ex(b: dict[str, Any], tag: str, fault: str) -> list[float]:
    return list(b[tag]["signature"][fault]["exceed"])


def _pump_lines(b: dict[str, Any]) -> list[str]:
    pump = {t: _ex(b, t, "pump") for t in TAGS}
    other = max(pump[t][j] for t in TAGS for j in (0, 3))
    return [
        f"- Pump: R2 exceeds its own threshold in {pump['oof'][1]:.2f} of pump-fault windows out "
        f"of fold and {pump['val'][1]:.2f} on validation, R3 in {pump['oof'][2]:.2f} and "
        f"{pump['val'][2]:.2f}, R1 and R4 in at most {other:.2f}. R2 without R3 supports a loss "
        "of pump head. R2 with R3 together also occurs for faults of PT-202A or FT-201 (table "
        "below), so R2 alone is not exclusive to the pump.",
    ]


def _drift_leak_lines(b: dict[str, Any]) -> list[str]:
    drift = {t: _ex(b, t, "drift") for t in TAGS}
    leak = {t: _ex(b, t, "leak") for t in TAGS}
    return [
        f"- Drift: R1 exceeds in {drift['oof'][0]:.2f} of drift windows out of fold and "
        f"{drift['val'][0]:.2f} on validation. In the single-fault episodes the drifting tag is "
        "FT-001 or a tank level (table below).",
        f"- Leak: R1 exceeds in {leak['oof'][0]:.2f} out of fold and {leak['val'][0]:.2f} on "
        f"validation, and R2 in {leak['oof'][1]:.2f} and {leak['val'][1]:.2f}; the two sets "
        "disagree on whether R1 is distinct for leaks.",
    ]


def _ambiguity_lines() -> list[str]:
    return [
        "**Leak against flow-meter error.** R1 is the mismatch between the receipt flow, the "
        "delivery flow and the change of tank inventory from the level slopes. A leak between "
        "the meters produces such a mismatch. So does a bias, drift or stuck value of FT-001 or "
        "FT-201, and so does a drifting level sensor (table below: R1 exceeds in 0.69 to 1.00 "
        "of those windows out of fold). R1 alone therefore cannot separate a leak from a "
        "flow-meter or level-sensor fault. The sign of the residual, which this work does not "
        "use (z is an absolute value) and has not tested, and evidence from other tags or from "
        "an inspection would be needed for that. Agent 2 should report a mass imbalance and "
        "name the leak and the instrument faults as candidates, not a leak.",
        "",
    ]


def claims_section(b: dict[str, Any], assets: list[list[Any]], tr: dict[str, float]) -> list[str]:
    """Section 5: what a deployed Agent 2 can claim."""
    head = ["set", "fault", "faulty tag", "windows", "R1", "R2", "R3", "R4"]
    return [
        "## 5. What a deployed Agent 2 can claim", "",
        "**Window-level evidence only.** For one `summary_v1` window the pooled C3 gives a score "
        "and four residuals. The statement it supports is: this window's residuals exceed what "
        "fault-free windows of the grouped-CV folds show, by this much, in these residuals. It "
        "does not give an episode, an onset, a fault identity or a location, and a window "
        "without an alarm is not evidence of health (recall at the 5% window target is about "
        "0.5 out of fold and 0.66 on validation, and below 0.4 for restriction, leak, bias and "
        "misrouting out of fold).", "",
        "**A fixed threshold does not carry over unchanged.** The 95th percentile of the "
        f"out-of-fold fault-free scores is {tr['threshold']:.2f}. Applied to validation it gives "
        f"a false-alarm rate of {tr['far']:.3f} and a recall of {tr['recall']:.3f}, against the "
        "0.05 target by construction in each set separately. The threshold needs to be set and "
        "monitored on the data the agent will see.", "",
        "**The alarm policy needs history.** The 1/1 window-level version needs one request. "
        "The 2/3 and 3/5 policies, which detected more faulty episodes at the same "
        "fault-free-episode target (section 2), need the scores of the previous windows of the "
        "same episode, which a single-window request does not carry. Without stored state the "
        "agent can only state window-level evidence.", "",
        "**Residual-level statements supported by the signature matrix** (descriptive, small "
        "numbers for some types):", "",
        *_pump_lines(b), *_drift_leak_lines(b), "",
        *_ambiguity_lines(),
        "**Not claimable:** restriction, misrouting, stuck values and multi-component faults "
        "share residuals, and bias has no signature out of fold and a shared one on "
        "validation (registered classification, section 3 of the C3 report); misrouting has 9 "
        "and 15 windows. R4 is distinct for no fault type. Pressure-sensor faults show partly "
        "in R2 and R3 (table below) but not consistently across the two sets.", "",
        *table(head, assets),
        "The table is a descriptive check made for this section, not part of the registered "
        "classification: fraction of single-fault sensor-fault windows in which each residual "
        "exceeds its own threshold, by faulty tag, for tags with at least 8 windows.", "",
        "The statements depend on the tag-to-location mapping taken from tag names, parts of "
        "which are unverified (section 4.2 of the C3 report), and on simulator data.", "",
    ]  # fmt: skip


def limits_section() -> list[str]:
    """Section 6."""
    return [
        "## 6. Limits and deviations",
        "",
        "- Pooled R4 is compared on the same windows and folds as the per-regime version. The "
        "per-regime scores are those saved in the C3 stage; the pooled run reproduces every "
        "other part of C3 exactly.",
        "- The stress test uses one random draw per setting. The intervals are over episodes "
        "and do not include the variation between draws.",
        "- The noise scales come from the fitted residual scales (plan section 14.3), and "
        "missing tags are drawn uniformly. Real sensor failures are not uniform and are "
        "correlated across tags.",
        "- The per-asset table was added in the report and was named in the plan (section "
        "14.4) as a descriptive check; nothing was tuned on it.",
        "- The contract example request is a fixture; scoring it shows that the fields are "
        "readable, not that its values are plant values.",
        "- The test split was not opened; the audit hook recorded no rejected attempt.",
        "",
    ]


def summary(root: Path, inputs: dict[str, Any], stress: dict[str, Any]) -> list[str]:
    """Section 1."""
    cv = root / "cv"
    d = {t: cv_eval.compare_systems(cv / "B0", cv / "P4", t, "C3") for t in TAGS}
    s1, s3 = stress["oof"]["missing_1"], stress["oof"]["missing_3"]
    return [
        "# Pooled R4, minimal inputs, stress test", "",
        "C3 alone, as in the C3 report. Protocol: section 14 of the experiment plan, committed "
        "before this stage was run.", "",
        "## 1. Summary", "",
        f"- Pooled R4 (no set conditions) against the per-regime R4: AP difference "
        f"{f3(d['oof']['ap'])} out of fold and {f3(d['val']['ap'])} on validation; matched-stage "
        f"AUROC difference {f3(d['oof']['matched_auroc'])} and {f3(d['val']['matched_auroc'])}.",
        f"- The pooled version reads {len(field_list())} fields, all in a `summary_v1` request; "
        "scores do not change when anything else changes, including the regime key, the order "
        "and the other windows (largest change "
        f"{max(inputs['perturbation'].values())}).",
        f"- Out of fold, one missing tag takes AP from {stress['oof']['clean']['ap'][0]:.3f} to "
        f"{s1['ap'][0]:.3f} and three to {s3['ap'][0]:.3f}, with {s3['scorable_all']:.0%} of "
        "windows still scorable.",
        "- A deployed Agent 2 can state window-level residual evidence, not a leak, an episode "
        "or health (section 5).", "",
    ]  # fmt: skip


def render(root: Path) -> str:
    """The whole document."""
    inputs = load_json(root / "stress" / "inputs.json")
    stress = load_json(root / "stress" / "results.json")
    b = load_json(root / "c3p4" / "results.json")
    spec = load_json(root / "cv" / "B0" / "spec.json")
    cv = root / "cv" / "P4"
    lines = [
        *summary(root, inputs, stress), *pooled_section(root), *input_section(inputs),
        *stress_section(stress, spec), *claims_section(b, asset_rows(cv), transfer(cv)),
        *limits_section(),
    ]  # fmt: skip
    return "\n".join(lines)
