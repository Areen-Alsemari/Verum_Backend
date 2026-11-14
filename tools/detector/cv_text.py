"""The results document of the second stage: Phase A evidence and Phase B grouped-CV results.

Input is one work root holding the folders of the first experiment, of the re-run with the new
key (with the regime audit), and of the five grouped-CV systems. Output is the markdown text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv_report as r
import numpy as np
import rekey_compare
from regime_report import table

SYSTEM_HEAD = ["system", "AP", "AUROC", "matched-stage AUROC"]


def load_json(path: Path) -> Any:
    """Parse a JSON file."""
    return json.loads(path.read_text())


def sizes(cv: Path) -> dict[str, Any]:
    """Counts of the train windows used by grouped CV."""
    d = np.load(cv / "B0" / "oof.npz")
    meta = load_json(cv / "B0" / "oof_meta.json")
    y = d["faulty"]
    folds = [int((d["fold"] == k).sum()) for k in range(5)]
    return {
        "windows": len(y), "faulty": int(y.sum()), "prevalence": float(y.mean()),
        "episodes": len(set(meta["episodes"])), "units": len({tuple(u) for u in meta["units"]}),
        "fold_windows": folds,
    }  # fmt: skip


def temperature_mixture(regimes: list[dict[str, Any]]) -> dict[str, float]:
    """Shares of fault-free windows by temperature, and the episode and window counts at 40 C."""
    out: dict[str, float] = {}
    tot_t = sum(x["train_fault_free"] for x in regimes)
    tot_v = sum(x["val_fault_free"] for x in regimes)
    for temp in (25.0, 40.0):
        sel = [x for x in regimes if x["regime"][1] == temp]
        out[f"train_{int(temp)}"] = sum(x["train_fault_free"] for x in sel) / tot_t
        out[f"val_{int(temp)}"] = sum(x["val_fault_free"] for x in sel) / tot_v
        out[f"episodes_{int(temp)}"] = float(sum(x["episodes_train"] for x in sel))
        out[f"windows_{int(temp)}"] = float(sum(x["train_fault_free"] for x in sel))
    return out


def phase_a(root: Path, old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Sections 2.1 to 2.3."""
    audit = load_json(root / "v2" / "regime_audit.json")
    mix = temperature_mixture(audit["conditions"]["regimes"])
    tr, va = audit["train"], audit["validation"]
    rerun = rekey_compare.render(old, new, root / "det" / "work", root / "v2" / "work_conditions")
    rerun[0] = "### 2.3 Re-run of C3 and C4 with the new key (Amendment 2)"
    return [
        "## 2. Phase A: the regime key", "",
        "### 2.1 What the old key contained", "",
        "The key behind the 200-window guard and the per-regime baselines was the latest state of "
        "16 on/off tags: three level switches, the two pump run states and eleven valve contact "
        "states. Restriction and misrouting act on valve positions, so the key of such a window "
        "differs from every fault-free key because of the fault. Train windows with a key that "
        f"no fault-free train window has: restriction {tr['restriction']['key_never_fault_free']}"
        f" of {tr['restriction']['windows']}, misrouting {tr['misrouting']['key_never_fault_free']}"
        f" of {tr['misrouting']['windows']}; validation: restriction "
        f"{va['restriction']['key_never_fault_free']} of {va['restriction']['windows']}, "
        f"misrouting {va['misrouting']['key_never_fault_free']} of {va['misrouting']['windows']}. "
        "The full table, with the tags that differ, is in "
        "`reports/detector_v2_regime_audit.md`.", "",
        "### 2.2 Correction of Amendment 1", "",
        "Train does contain 40 degrees C: 203 episodes, of which "
        f"{int(mix['episodes_40'])} have eligible windows, with {int(mix['windows_40']):,} "
        f"fault-free eligible windows. The shift is in the mixture: {mix['train_25']:.0%} of the "
        "fault-free train windows are at 25 degrees C and no eligible validation window is; "
        f"{mix['val_40']:.0%} of the fault-free validation windows are at 40 degrees C against "
        f"{mix['train_40']:.0%} of the fault-free train windows.", "",
        *rerun,
    ]  # fmt: skip


def protocol(size: dict[str, Any]) -> list[str]:
    """Section 3.1."""
    return [
        "## 3. Phase B: enhancements under grouped cross-validation", "",
        "### 3.1 Data and protocol", "",
        f"Grouped CV uses {size['windows']:,} eligible train windows from {size['episodes']:,} "
        f"episodes, {size['faulty']:,} faulty (prevalence {size['prevalence']:.4f}), in "
        f"{size['units']} units (family, atmosphere, temperature) assigned to 5 folds of "
        f"{', '.join(f'{n:,}' for n in size['fold_windows'])} windows. Each fold is fitted on the "
        "fault-free windows of the other units and scores every window of its units. The "
        "validation benchmark is fitted on all fault-free train windows. The alarm threshold is "
        "the 95th percentile of fault-free scores of the other parity fold (5% false-alarm "
        "target); intervals are 95% bootstrap over episodes (1,000 resamples, seed 20261108).", "",
    ]  # fmt: skip


def systems(res: dict[str, Any], dec: dict[str, Any]) -> list[str]:
    """Sections 3.2 and 3.3."""
    labels = [c[0] for c in r.CHAIN]
    out = ["### 3.2 Systems (fused score C4 of each system)", ""]
    for tag, title in r.TAGS.items():
        out += [f"**{title}:**", "", *table(SYSTEM_HEAD, r.discrimination_rows(res, tag, labels))]
    head = ["system", "against", "OOF AP difference", "OOF matched AUROC difference", "decision",
            "validation AP difference", "validation matched AUROC difference"]  # fmt: skip
    return [
        *out, "### 3.3 Stop rule: paired differences against the previous kept system", "",
        "A system is kept only if the lower bounds of the OOF differences of AP and of "
        "matched-stage AUROC are both above zero. Validation differences are shown for "
        "information.", "",
        *table(head, r.paired_rows(dec)),
    ]  # fmt: skip


def components(res: dict[str, Any], final: str) -> list[str]:
    """Section 3.4."""
    out = ["### 3.4 Components and the condition-only reference", ""]
    for lab in ("B0", final):
        for tag, title in r.TAGS.items():
            rows = r.component_rows(res, tag, lab)
            out += [f"**{lab}, {title}:**", "", *table(["score", *SYSTEM_HEAD[1:]], rows)]
    return out + [
        "`prior` scores a window by the fault prevalence of its set-condition regime among the "
        "fit windows. It sits at chance level, so the set conditions alone carry no information "
        "about faults in these splits and a gain over it is not explained by the conditions.",
        "",
    ]


def operating(res: dict[str, Any]) -> list[str]:
    """Section 3.5."""
    labels = [c[0] for c in r.CHAIN]
    head = ["system", "false-alarm rate", "false alarms per day", "recall, all faults",
            "delay quartiles (s)", "episodes never alarmed", "localisation top-1",
            "localisation top-3"]  # fmt: skip
    out = ["### 3.5 Operating point at the 5% false-alarm target (fused score)", ""]
    for tag, title in r.TAGS.items():
        out += [f"**{title}:**", "", *table(head, r.operating_rows(res, tag, labels))]
    return out + [
        "False alarms per day are the false-alarm rate times 288 windows. Delay is the cutoff "
        "of the first alarmed faulty window minus the earliest onset, over episodes with at "
        "least one alarm; episodes never alarmed are counted separately and not imputed. "
        "Localisation covers single-component sensor faults (bias, drift, stuck) of "
        "single-fault episodes: the faulty tag is ranked among the 14 by the per-tag evidence "
        "of the system, and ties count against it. Chance is 7.1% for top-1 and 21.4% for "
        "top-3. Equipment faults are not scored because the reference declares no "
        "instrument-to-equipment mapping.", "",
    ]  # fmt: skip


def by_type(res: dict[str, Any], final: str) -> list[str]:
    """Section 3.6."""
    picks = [("B0", "C4"), (final, "C4"), (final, "C3")]
    head = ["fault type", "faulty windows", "B0 fused", f"{final} fused", "C3 alone"]
    out = ["### 3.6 Recall by fault type at the 5% false-alarm target", ""]
    for tag, title in r.TAGS.items():
        out += [f"**{title}:**", "", *table(head, r.type_rows(res, tag, picks))]
    return out


def controls(res: dict[str, Any]) -> list[str]:
    """Section 3.7."""
    labels = [c[0] for c in r.CHAIN]
    head = ["system", "shuffle AP", "shuffle AUROC", "shuffle matched AUROC",
            "placebo matched AUROC", "constant columns"]  # fmt: skip
    out = ["### 3.7 Controls (fused score of every system)", ""]
    for tag, title in r.TAGS.items():
        out += [f"**{title}:**", "", *table(head, r.control_rows(res, tag, labels))]
    for tag, title in r.TAGS.items():
        rows = r.contributor_rows(res, tag, labels)
        out += [f"**Largest contributors on faulty windows, {title}:**", "",
                *table(["system", "score", "top contributors (share)"], rows)]  # fmt: skip
    cond = res["B0"]["oof"]["condition_inputs"]
    return out + [
        "Shuffle means sit at prevalence and 0.5. The placebo separates windows of positions 1 "
        "to 5 by whether the episode contains a fault later; a lower bound above 0.5 would mean "
        "the score reads the kind of episode. No column used by a component is constant across "
        f"faulty windows. The set conditions that enter E1 take {cond['atmosphere']} (atmosphere), "
        f"{cond['temperature_c']} (temperature) and {cond['setpoint_m3h']} (set point) distinct "
        "values in train.", "",
    ]  # fmt: skip


def candidates(res: dict[str, Any], dec: dict[str, Any], root: Path) -> list[str]:
    """Section 3.8: one paragraph per candidate."""
    b0 = load_json(root / "B0" / "spec.json")
    e2 = load_json(root / "E1_E2" / "spec.json")
    pumps = b0["pump_states"]
    a, b = b0["mass_balance"], e2["mass_balance"]
    ar = [res[k]["oof"]["C3"]["alarms_at_5pct_far"]["recall_by_type"] for k in ("E1", "E1+E3")]
    share = dict(res["E1+E3"]["oof"]["C3"]["top_contributors"])
    return [
        "### 3.8 Candidates", "",
        f"**E1, set-point-conditioned baselines: {_verdict(dec['E1'])}.** In a fault-free plant "
        "the expected level of each column follows the set conditions, so a regression "
        "generalises to combinations with few fault-free windows. The gain is in the fused "
        "score; C1n, C2a and C2b stay near prevalence (section 3.4).", "",
        f"**E2, mass balance with flow terms: {_verdict(dec['E1+E2'])}.** The R1 of C3 already "
        "contains the storage term. Fitted tank areas on all fault-free train windows are "
        f"{a['area_LT-101']:.1f}, {a['area_LT-102']:.1f} and {a['area_LT-103']:.1f} without the "
        f"added terms and {b['area_LT-101']:.1f}, {b['area_LT-102']:.1f} and "
        f"{b['area_LT-103']:.1f} with them: all positive, and almost the same. The added "
        f"flow-meter term is {b['FT-201_mean']:.4f} per unit of FT-201 and the set-point term "
        f"{b['setpoint']:.4f} per m3/h. The differences from the previous system are zero within "
        "the interval.", "",
        f"**E3, related sensor pair residuals: {_verdict(dec['E1+E3'])}.** R6 (the two pump "
        "discharges when both pumps run) never applies: no train or validation window has both "
        f"pumps running (windows per pump state in train: {_pumps(pumps['train'])}; in "
        f"validation: {_pumps(pumps['validation'])}). R5 (tank temperatures against their "
        "median) became the largest contributor to C3 (share "
        f"{share.get('R5_temperature_pair', 0):.2f} on faulty windows out of fold) and lowered "
        "AP and matched-stage AUROC. Recall of C3 at the 5% "
        f"target for bias went from {ar[0]['bias']['recall'][0]:.3f} to "
        f"{ar[1]['bias']['recall'][0]:.3f} and for drift from {ar[0]['drift']['recall'][0]:.3f}"
        f" to {ar[1]['drift']['recall'][0]:.3f}, so it did not help the faults it was meant "
        "for. The reason was not investigated within the time-box.", "",
        f"**E4, out-of-sample calibration: {_verdict(dec['E1+E4'])}.** Reference scores come "
        "from inner grouped cross-fitting instead of the fit windows. Out of fold it adds to AP "
        "and to matched-stage AUROC. On validation it restores the alarm rule: the 95th "
        "percentile of fault-free scores is no longer the maximum score (section 3.5).", "",
    ]  # fmt: skip


def _pumps(c: dict[str, int]) -> str:
    names = {"A": "A only", "B": "B only", "AB": "both", "none": "none"}
    return ", ".join(f"{names[k]} {v:,}" for k, v in c.items())


def _verdict(d: dict[str, Any]) -> str:
    return "kept" if d["keep"] else "dropped"


def limits(res: dict[str, Any], dec: dict[str, Any], root: Path) -> list[str]:
    """Section 4."""
    final = r.kept_chain(dec)[-1]
    folder = next(x[1] for x in r.CHAIN if x[0] == final)
    vs = r.versus_c3(root, folder, "B0")
    return [
        "## 4. Reading of the results", "",
        "- The stop rule was applied to systems (fusions). No fused system beats C3 alone out "
        f"of fold: the paired difference of the final fusion minus C3 alone is "
        f"{r.f3(vs['oof']['ap'])} in AP and "
        f"{r.f3(vs['oof']['matched_auroc'])} in matched-stage AUROC out of fold, and "
        f"{r.f3(vs['val']['ap'])} and {r.f3(vs['val']['matched_auroc'])} on validation. The "
        "components that carry no signal are fused by the minimum p-value; a plausible reason "
        "for the loss is that they raise scores of fault-free windows, which was not tested.",
        "- C3, the topology residuals, carries almost all detectable signal: pump, stuck and "
        "drift faults are found, restriction and leak partly, misrouting and bias poorly. "
        "These are residuals fitted on a few tags; this is a result about this simulator and "
        "these windows, and tests of reduced models are not independent validation.",
        "- Under the old key the validation results of C2b (AP 0.648) and C4 (AP 0.887) rested "
        "on baselines selected by the on/off tags. Fault effects in the key (restriction and "
        "misrouting) can contribute, and so can the commanded lineup, which an operator sets and "
        "which the key of Amendment 2 does not contain. This work does not separate the two; "
        "a key that adds the commanded mode would, and was not run because it is outside the "
        "registered candidates.",
        "- Grouped CV leaves out whole units, but fault-free windows of the same atmosphere and "
        "temperature from other families stay in the fit set. Validation has fewer such windows, "
        "and its numbers are in places higher than CV: do not read the difference as a trend.",
        "- The pump state used by R2 and R3 comes from the pump run tags, as before. Windows "
        "with no pump running (the state `none`) get no pump residual.",
        "- Delay is bounded by the 300 s window grid. Many faulty episodes are never alarmed at "
        "the 5% target, so the delay quartiles describe only the episodes that are.",
        "- The test split was not opened: the guard recorded no rejected attempt.", "",
    ]  # fmt: skip


def deviations() -> list[str]:
    """Section 5."""
    return [
        "## 5. Deviations from the plan",
        "",
        "- The audit hook was widened to the label file of train and validation episodes (plan "
        "section 11.2), the only source of the set conditions and fault onsets.",
        "- B0 uses C1n, which has no CUSUM component, as registered in section 12.2. The "
        "Amendment 2 re-run keeps the CUSUM.",
        "- The stop rule was applied to fused systems; section 4 gives the reading against C3.",
        "- E3 and E4 were applied to the system kept after E1, because E2 was dropped.",
        "- The five systems were run twice: the second run added the recorded R1 terms and "
        "pump-state counts; scores and metrics were identical.",
        "- C1 and C2 rows were added to the old-key comparison because they feed C4.",
        "",
    ]


def reproduction() -> list[str]:
    """Section 6."""
    base = ".venv/bin/python tools/detector/run.py"
    rel = "data/reference_release_v2/verum_reference_v2"
    return [
        "## 6. Reproduction", "",
        "Seed 20261108 everywhere. WORK is a scratch folder.", "",
        "```",
        f"{base} score --release {rel} --work WORK/v2/work_lineup --key lineup",
        f"{base} score --release {rel} --work WORK/v2/work_conditions --key conditions",
        f"{base} evaluate --work WORK/v2/work_conditions --out WORK/v2/results_conditions.json",
        f"{base} cv --release {rel} --work WORK/cv/B0 --spec ''",
        f"{base} cv --release {rel} --work WORK/cv/E1 --spec E1",
        f"{base} cv --release {rel} --work WORK/cv/E1_E2 --spec E1,E2",
        f"{base} cv --release {rel} --work WORK/cv/E1_E3 --spec E1,E3",
        f"{base} cv --release {rel} --work WORK/cv/E1_E4 --spec E1,E4",
        f"{base} cveval --work WORK/cv/<system> --out WORK/cv/<system>/results.json",
        f"{base} cvreport --work WORK --out reports/detector_v2_results.md",
        "```", "",
    ]  # fmt: skip


def render(root: Path) -> str:
    """The whole document."""
    cv = root / "cv"
    res, dec = r.load(cv), r.decisions(cv)
    old = load_json(root / "det" / "results.json")
    new = load_json(root / "v2" / "results_conditions.json")
    final = r.kept_chain(dec)[-1]
    lines = [
        *summary(res, dec, cv, sizes(cv), old), *phase_a(root, old, new), *protocol(sizes(cv)),
        *systems(res, dec), *components(res, final), *operating(res), *by_type(res, final),
        *controls(res), *candidates(res, dec, cv), *limits(res, dec, cv), *deviations(),
        *reproduction(),
    ]  # fmt: skip
    return "\n".join(lines)


def summary(
    res: dict[str, Any], dec: dict[str, Any], cv: Path, size: dict[str, Any], old: dict[str, Any]
) -> list[str]:
    """Section 1."""
    final = r.kept_chain(dec)[-1]
    f, b = res[final]["oof"], res["B0"]["oof"]
    ap_old = old["C4"]["discrimination"]["ap"][0]
    kept = [x for x in r.kept_chain(dec) if x != "B0"]
    return [
        "# Detector experiment, second stage", "",
        "Regime key and four enhancements under grouped cross-validation. The protocol is in "
        "sections 11 and 12 of the plan, committed before the runs it governs. Validation is "
        "reported separately as the held-out-combination benchmark and decides nothing.", "",
        "## 1. Summary", "",
        "- The key of the first experiment contained fault effects for restriction and "
        "misrouting. With operator-set conditions as the key, C3 is unchanged on validation "
        f"(AP {res['B0']['val']['C3']['discrimination']['ap'][0]:.3f}) while the fused score "
        f"C4 falls from {ap_old:.3f} to {res['B0']['val']['C4']['discrimination']['ap'][0]:.3f} "
        "and the 5% threshold gives no alarm (section 2.3).",
        f"- Grouped CV, {size['units']} units, {size['windows']:,} windows, {size['faulty']:,} "
        f"faulty (prevalence {size['prevalence']:.3f}): the baseline system has AP "
        f"{r.f3(b['C4']['discrimination']['ap'])}.",
        f"- Kept by the stop rule: {', '.join(kept)}. Dropped: "
        f"{', '.join(k for k, v in dec.items() if not v['keep'])}. Final system {final}: AP "
        f"{r.f3(f['C4']['discrimination']['ap'])}, matched-stage AUROC "
        f"{r.f3(f['C4']['discrimination']['matched_auroc'])}.",
        f"- C3 alone has AP {r.f3(f['C3']['discrimination']['ap'])}, above every fusion; the "
        "per-tag baseline and PCA components stay at chance level in every system (section 4).",
        f"- On validation, the final system alarms at the 5% target with false-alarm rate "
        f"{r.f3(res[final]['val']['C4']['alarms_at_5pct_far']['far'])} and recall "
        f"{r.f3(res[final]['val']['C4']['alarms_at_5pct_far']['recall_all'])}; the systems before "
        "E4 give no alarm at all there (saturated fusion score).", "",
    ]  # fmt: skip
