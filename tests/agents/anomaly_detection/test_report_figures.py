"""The figures Agent 2 quotes must be the figures of the written characterisation reports."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from verum.agents.anomaly_detection import text

pytestmark = pytest.mark.fast
REPORTS = Path(__file__).resolve().parents[3] / "reports"
FAULT_TYPES = ["restriction", "pump", "bias", "drift", "stuck", "leak", "misrouting", "multi"]


def report(name: str) -> str:
    """Text of one written report."""
    return (REPORTS / name).read_text(encoding="utf-8")


def table_rows(body: str, start: str) -> list[list[str]]:
    """Cells of the table that follows the first line containing the marker."""
    lines = body.splitlines()
    first = next(i for i, line in enumerate(lines) if start in line)
    rows = []
    for line in lines[first + 1 :]:
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip("|").split("|")])
        elif rows:
            break
    return [r for r in rows if not r[0].startswith("---")][1:]


def point(cell: str) -> str:
    """The point value of a cell that reads 'value (low to high)'."""
    return cell.split(" ")[0]


def three(values: list[str]) -> str:
    """Three values written as 'a, b and c'."""
    return f"{values[0]}, {values[1]} and {values[2]}"


def pooled_recall(body: str, marker: str) -> dict[str, str]:
    """Pooled-version recall per fault type from one recall table."""
    return {r[0]: r[3] for r in table_rows(body, marker)}


def test_figures_are_the_ones_in_the_pooled_report() -> None:
    """Every quoted AP, AUROC, recall and stress figure is read back from the report tables.

    Independent: yes, because the expected strings are parsed from the written report.
    """
    body = report("detector_v4_pooled_stress.md")
    head = [r for r in table_rows(body, "| set | version |") if r[1] == "pooled R4"]
    oof, val = head[0], head[1]
    assert text.FIGURES["oof_ap"] == oof[2] and text.FIGURES["oof_matched"] == oof[3]
    assert text.FIGURES["val_ap"] == val[2] and text.FIGURES["val_matched"] == val[3]
    assert text.FIGURES["oof_recall"] == oof[5] and text.FIGURES["val_recall"] == val[5]


def test_recall_by_fault_type_matches_the_pooled_columns() -> None:
    """The per-type recall strings are the pooled columns of the two recall tables.

    Independent: yes, because the expected strings are parsed from the written report.
    """
    body = report("detector_v4_pooled_stress.md")
    oof = pooled_recall(body, "Recall by fault type at the 5% window target, grouped CV")
    val = pooled_recall(body, "Recall by fault type at the 5% window target, validation")
    for kind in FAULT_TYPES:
        both = f"{oof[kind]} and {val[kind]}"
        assert text.FIGURES[kind] == both.replace(" (1.000 to 1.000)", ""), kind


def test_stress_figures_match_the_stress_tables() -> None:
    """Missing-tag and noise figures are the out-of-fold rows of the stress table.

    Independent: yes, because the expected strings are parsed from the written report.
    """
    body = report("detector_v4_pooled_stress.md")
    rows = {r[0]: r for r in table_rows(body, "**grouped CV (out of fold, train):**")}
    missing = [rows[f"{n} tag{'s' if n > 1 else ''} missing"] for n in (1, 2, 3)]
    noise = [rows[f"noise {k}x"] for k in (1, 2, 3)]
    assert text.FIGURES["missing_ap"] == three([point(r[1]) for r in missing])
    assert text.FIGURES["missing_scorable"] == three([r[5] for r in missing])
    assert text.FIGURES["noise_ap"] == three([point(r[1]) for r in noise])
    assert text.FIGURES["noise_far"] == three([point(r[3]) for r in noise])


def test_threshold_and_transfer_figures_match_the_text_of_the_report() -> None:
    """The window threshold, the validation false-alarm rate and recall, and the two ranges.

    Independent: yes, because the expected strings are read from the written reports.
    """
    pooled = report("detector_v4_pooled_stress.md")
    pattern = r"scores is (\S+)\. Applied to validation it gives a false-alarm rate of (\S+) and"
    sentence = re.search(pattern + r" a recall of (\S+),", pooled)
    assert sentence is not None
    assert (text.FIGURES["threshold"], text.FIGURES["val_far"]) == sentence.group(1, 2)
    assert text.FIGURES["val_recall_fixed"] == sentence.group(3)
    assert text.FIGURES["r1_instrument"] in pooled
    assert f"within {text.FIGURES['area_match']}" in report("detector_v3_c3_characterisation.md")


def test_the_limitations_quote_every_figure() -> None:
    """Each figure is present in the limitation text the agent produces.

    Independent: yes, because the check is on the strings, not on the agent's logic.
    """
    from verum.agents.anomaly_detection.parameters import load_parameters

    joined = " ".join(text.method_limitations(load_parameters()))
    for name, figure in text.FIGURES.items():
        assert figure in joined, name


def test_episode_figures_match_the_alarm_policy_tables() -> None:
    """The fault-free episode shares are read back from the two alarm policy tables.

    Independent: yes, because the expected strings are parsed from the written report.
    """
    body = report("detector_v4_pooled_stress.md")
    oof = table_rows(body, "**Alarm policies, grouped CV (out of fold, train):**")
    val = table_rows(body, "**Alarm policies, validation (held-out combinations):**")
    assert text.FIGURES["episode_far_oof"] == {r[1]: r[2] for r in oof if r[0] == "2/3"}["pooled"]
    assert text.FIGURES["episode_far_val"] == {r[1]: r[2] for r in val if r[0] == "2/3"}["pooled"]
    shares = sorted(r[2] for r in val)
    assert text.FIGURES["episode_far_range"] == f"{shares[0]} to {shares[-1]}"
