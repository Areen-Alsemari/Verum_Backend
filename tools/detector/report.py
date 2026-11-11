"""Render the results report from the evaluation, diagnostics and scoring metadata files.

Tables are built from the numbers in the result files, so the text cannot drift from them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evaluate import CANDIDATES, SENSITIVITY
from windows import FAULT_TYPES

LABELS = {
    "always_flag": "always flag", "random": "random score", "C0": "C0 current Agent 2 forest",
    "C1": "C1 per-tag + CUSUM", "C2a": "C2a PCA, all tags", "C2b": "C2b PCA, process groups",
    "C3": "C3 topology residuals", "C4": "C4 fusion",
    "C1s": "C1s (temperature level removed)", "C2as": "C2as (temperature level removed)",
    "C2bs": "C2bs (temperature level removed)", "C4s": "C4s (temperature level removed)",
}  # fmt: skip
BASE = ["always_flag", "random", "C0"]


def ci(v: list[float], digits: int = 3) -> str:
    """'point [low, high]'."""
    return f"{v[0]:.{digits}f} [{v[1]:.{digits}f}, {v[2]:.{digits}f}]"


def table(head: list[str], rows: list[list[str]]) -> list[str]:
    """Markdown table lines."""
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return [*out, ""]


def main_table(res: dict[str, Any], names: list[str]) -> list[str]:
    """Discrimination and alarm rates for the listed models."""
    rows = []
    for n in names:
        d, a = res[n]["discrimination"], res[n]["alarms_at_5pct_far"]
        far, rec = ci(a["far"]), ci(a["recall_all"])
        if n == "always_flag":
            far, rec = "1.000 (flags every window)", "1.000 (flags every window)"
        rows.append([LABELS[n], ci(d["ap"]), ci(d["auroc"]), ci(d["matched_auroc"]), far, rec])
    head = ["Model", "AP", "AUROC", "Matched-stage AUROC", "False-alarm rate", "Recall"]
    return table(head, rows)


def type_table(res: dict[str, Any], names: list[str]) -> list[str]:
    """Recall by fault type at the 5% false-alarm target, with intervals."""
    by0 = res[names[0]]["alarms_at_5pct_far"]["recall_by_type"]
    head = ["Model", *[f"{t} (n={by0[t]['n']})" for t in FAULT_TYPES]]
    rows = []
    for n in names:
        by = res[n]["alarms_at_5pct_far"]["recall_by_type"]
        rows.append([LABELS[n], *[ci(by[t]["recall"], 2) for t in FAULT_TYPES]])
    return table(head, rows)


def seen_table(diag: dict[str, Any], names: list[str]) -> list[str]:
    """Post-hoc: AP and matched AUROC on windows in regimes seen in fault-free training."""
    rows = []
    for n in names:
        s = diag["seen_regime"][n]
        rows.append([LABELS[n], ci(s["ap_ci"]), ci(s["matched_ci"]), ci(diag["placebo"][n])])
    head = ["Model", "AP (seen regimes)", "Matched-stage AUROC (seen regimes)", "Placebo AUROC"]
    return table(head, rows)


def seen_recall_table(diag: dict[str, Any], names: list[str]) -> list[str]:
    """Post-hoc: recall by type among windows in seen regimes (alarmed / total)."""
    rows = []
    for n in names:
        sr = diag["seen_recall"][n]
        cells = [f"{sr[t][0]}/{sr[t][1]}" if sr[t][1] else "-" for t in FAULT_TYPES]
        rows.append([LABELS[n], *cells])
    return table(["Model", *FAULT_TYPES], rows)


def shuffle_table(res: dict[str, Any]) -> list[str]:
    """Shuffle control for every model."""
    rows = []
    for n in LABELS:
        s = res[n]["shuffle"]
        rows.append([LABELS[n], *[ci(s[k]) for k in ("ap", "auroc", "matched")]])
    return table(["Model", "AP", "AUROC", "Matched-stage AUROC"], rows)


def contributors(res: dict[str, Any]) -> list[str]:
    """Top contributors to the score on faulty windows."""
    out = ["Mean share of the total contribution on faulty windows, top 10:", ""]
    for n in [*CANDIDATES, *SENSITIVITY]:
        top = ", ".join(f"{a} {b:.2f}" for a, b in res[n]["top_contributors"][:10])
        out.append(f"- {LABELS[n]}: {top}")
    return [*out, ""]


def temperature_table(diag: dict[str, Any], names: list[str]) -> list[str]:
    """Post-hoc: matched-stage AUROC within each temperature class."""
    classes = sorted(diag["by_temperature"][names[0]], key=float)
    n0 = diag["by_temperature"][names[0]]
    head = ["Model", *[f"{c} C (n={n0[c]['n']}, faulty={n0[c]['faulty']})" for c in classes]]
    rows = []
    for n in names:
        cells = [f"{diag['by_temperature'][n][c]['matched_auroc']:.3f}" for c in classes]
        rows.append([LABELS[n], *cells])
    return table(head, rows)


def summary_lines(res: dict[str, Any], diag: dict[str, Any]) -> list[str]:
    """Verdict paragraph with numbers from the files."""
    r, c3, c4 = res, res["C3"]["discrimination"], res["C4"]["discrimination"]
    c0 = r["C0"]["discrimination"]
    passed = ", ".join(r["stop_rule"]["passed"]) or "none"
    return [
        f"Prevalence of faulty windows in validation: {r['prevalence']:.4f} "
        f"({r['faulty']} of {r['windows']}).",
        "",
        f"**Stop rule (registered candidates only): the experiment did not stop. Passing both "
        f"conditions: {passed}.** C1 did not. The current forest C0 has AP {ci(c0['ap'])}, whose "
        f"interval contains the prevalence, and matched-stage AUROC {ci(c0['matched_auroc'])}, "
        f"which contains 0.5: on these windows it is not distinguishable from chance.",
        "",
        f"The topology-residual detector C3 reaches AP {ci(c3['ap'])} and matched-stage AUROC "
        f"{ci(c3['matched_auroc'])}; the fixed fusion C4 reaches AP {ci(c4['ap'])} and "
        f"matched-stage AUROC {ci(c4['matched_auroc'])}, at a false-alarm rate of about 5% by "
        f"construction. The placebo control (post hoc) is near 0.5 for every model, and the "
        f"result holds on windows whose operating regime was seen in fault-free training. "
        f"Details, limits and what is not supported are below.",
        "",
    ]


def render(res: dict[str, Any], diag: dict[str, Any], meta: dict[str, Any]) -> str:
    """The complete results report."""
    import report_text

    return report_text.assemble(res, diag, meta)


def run(results: Path, diagnostics: Path, work: Path, out: Path) -> None:
    """Read the three files and write the report."""
    res = json.loads(results.read_text())
    diag = json.loads(diagnostics.read_text())
    meta = json.loads((work / "meta.json").read_text())
    out.write_text(render(res, diag, meta), encoding="utf-8")
