"""Checks of the Markdown writer for the rows of a compressed workflow run."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "agents" / "make_compressed_report.py"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("compressed_report_tool", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pass(a6: str, decision: str) -> dict[str, Any]:
    return {
        "agent3": "complete", "agent6": a6, "agent7": "complete", "agent8": "degraded",
        "decision": decision, "agent6_issues": ["X"], "agent8_issues": ["Y"],
    }


def _row(second: dict[str, Any] | None) -> dict[str, Any]:
    first = _pass("degraded", "more_evidence_required")
    base = {
        "window_id": "w", "episode_id": "E", "position": 3, "cutoff_s": 900.0, "first": first,
        "meaningful": True,
    }
    if second is None:
        return base | {"second_pass": "no second pass available"}
    return base | {
        "second_pass": "run", "second": second, "action": "ACT-INSP-03", "target": "P-1",
        "left_degraded": False,
    }


def test_a_row_without_a_second_pass_says_so_and_a_run_row_shows_both_passes() -> None:
    """The last position reports no second pass and a run row carries the second statuses.

    Independent: yes, because the expected cell texts are written out by hand.
    """
    tool = _tool()
    assert "no second pass available" in tool.line(_row(None))
    text = tool.line(_row(_pass("insufficient_evidence", "review_required")))
    assert "insufficient | complete | degraded | review required | no |" in text


def test_the_summary_counts_the_windows_that_stay_degraded_by_action() -> None:
    """The summary names the count of windows that stay degraded and the issue codes.

    Independent: yes, because the counts follow from the two stub rows.
    """
    tool = _tool()
    rows = [_row(_pass("degraded", "review_required")) for _ in range(2)]
    text = tool.summary(rows, rows)
    assert "**2 do not leave degraded**" in text and "2 pump-vibration window(s)" in text
    assert "(X)" in text and "the issue Y" in text
