"""Tests for the C3 characterisation: alarm policies, calibration, signatures, counts."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import numpy as np

FOLDER = Path(__file__).resolve().parents[2] / "tools" / "detector"


def load(name: str) -> Any:
    """Import one module of the experiment folder, which is not a package."""
    if str(FOLDER) not in sys.path:
        sys.path.insert(0, str(FOLDER))
    return importlib.import_module(name)


def episodes(rows: list[tuple[str, int, float, int]]) -> Any:
    """Episodes from (episode, stage, score, faulty) rows, onset 0 for faulty episodes."""
    policies = load("policies")
    d = {
        "stage": np.asarray([r[1] for r in rows], dtype=np.float64),
        "faulty": np.asarray([r[3] for r in rows], dtype=np.float64),
        "cutoff": np.asarray([r[1] * 300.0 for r in rows]),
        "onset_s": np.asarray([0.0 if r[3] else np.nan for r in rows]),
    }
    meta = {"episodes": [r[0] for r in rows], "kind": ["pump" if r[3] else "none" for r in rows]}
    return policies.build(d, meta, np.asarray([r[2] for r in rows]))


def test_k_of_n_counts_exceedances_in_the_last_n_positions_only() -> None:
    """A missing position never counts, and an old exceedance leaves the window.

    Independent: yes, because the expected states are counted by hand.
    """
    policies = load("policies")
    e = episodes([("a", 1, 9.0, 0), ("a", 2, 0.0, 0), ("a", 4, 9.0, 0), ("a", 5, 9.0, 0)])
    two_of_three = policies.alarm_state(e, 1.0, 2, 3)
    assert two_of_three.tolist() == [False, False, False, True]
    one_of_one = policies.alarm_state(e, 1.0, 1, 1)
    assert one_of_one.tolist() == [True, False, True, True]
    three_of_five = policies.alarm_state(e, 1.0, 3, 5)
    assert three_of_five.tolist() == [False, False, False, True]


def test_calibration_picks_the_smallest_threshold_meeting_the_target() -> None:
    """The threshold is the smallest candidate with at most the target share alarming.

    Independent: yes, because four episodes with known peaks are written out.
    """
    policies = load("policies")
    rows = [(f"e{i}", 1, peak, 0) for i, peak in enumerate([1.0, 2.0, 3.0, 4.0])]
    e = episodes(rows)
    everyone = [0, 1, 2, 3]
    assert policies.calibrate(e, everyone, 1, 1, 0.25) == 3.0
    assert policies.calibrate(e, everyone, 1, 1, 0.0) == 4.0  # strictly above counts
    assert policies.calibrate(e, everyone, 1, 1, 1.0) == 1.0
    assert policies.share_alarmed(e, 3.0, 1, 1, everyone) == 0.25


def test_policy_metrics_count_episodes_once_and_report_delay() -> None:
    """False-alarm episodes, detection and delay on a three-episode set.

    Independent: yes, because the three episodes are written out with known answers.
    """
    policy_eval = load("policy_eval")
    policies = load("policies")
    rows = [("free", 1, 9.0, 0), ("free", 2, 0.0, 0), ("hit", 1, 0.0, 0), ("hit", 2, 0.0, 1),
            ("hit", 3, 9.0, 1), ("miss", 1, 0.0, 0), ("miss", 2, 0.0, 1)]  # fmt: skip
    e = episodes(rows)
    state = policies.alarm_state(e, 1.0, 1, 1)
    c = policy_eval.Context(e)
    fa = policy_eval.false_alarms(e, state, c)
    assert fa["fault_free_episodes"] == 1
    assert fa["alarmed"] == 1
    det = policy_eval.detection(e, state, c)["all"]
    assert (det["n"], det["detected"]) == (2, 1)
    out = policy_eval.delays(e, state)
    assert out["detected"] == 1
    assert out["never"] == 1
    assert out["quartiles_s"] == [900.0, 900.0, 900.0]


def test_signature_classification_follows_the_registered_rule() -> None:
    """Distinct needs 0.30 and twice the second; below 0.15 is none; else shared.

    Independent: yes, because the boundary cases are written out.
    """
    sig = load("signature")
    assert sig.classify([0.30, 0.15, 0.0, 0.0]) == "distinct R1"
    assert sig.classify([0.30, 0.16, 0.0, 0.0]) == "shared"
    assert sig.classify([0.0, 0.0, 0.60, 0.2]) == "distinct R3"
    assert sig.classify([0.14, 0.05, 0.0, 0.0]) == "none"
    assert sig.classify([0.20, 0.0, 0.0, 0.0]) == "shared"


def test_thresholds_use_fault_free_windows_of_other_folds_only() -> None:
    """A fold's threshold ignores its own windows and every faulty window.

    Independent: yes, because the values are written out.
    """
    sig = load("signature")
    parts = np.zeros((6, 4))
    parts[:, 0] = [1.0, 1.0, 9.0, 9.0, 5.0, 50.0]
    y = np.asarray([0, 0, 0, 0, 0, 1])
    fold = np.asarray([0, 0, 1, 1, 1, 1])
    thr = sig.fold_thresholds(parts, y, fold)
    assert thr[0, 0] == np.percentile([9.0, 9.0, 5.0], 95)
    assert thr[2, 0] == 1.0


def test_signature_row_shares_tops_and_exceedances() -> None:
    """Share, top contributor, none and exceed fractions for a hand-built set.

    Independent: yes, because the four windows are written out.
    """
    sig = load("signature")
    parts = np.asarray([[2.0, 2.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0], [0.0, 3.0, 0.0, 1.0],
                        [4.0, 0.0, 0.0, 0.0]])  # fmt: skip
    thr = np.full_like(parts, 1.5)
    row = sig._row(parts, thr)
    assert row["n"] == 4
    assert row["none"] == 0.25
    assert row["exceed"] == [0.5, 0.5, 0.0, 0.0]
    assert row["top"][0] == 0.5
    assert abs(row["share"][1] - (0.5 + 0.75) / 4) < 1e-9


def test_cramers_v_is_one_for_perfect_association_and_zero_for_independence() -> None:
    """The association measure on two small tables.

    Independent: yes, because both answers follow from the table by inspection.
    """
    lineup = load("lineup_facts")
    assert abs(lineup.cramers_v(np.asarray([[10.0, 0.0], [0.0, 10.0]])) - 1.0) < 1e-12
    assert abs(lineup.cramers_v(np.asarray([[5.0, 5.0], [5.0, 5.0]]))) < 1e-12


def test_mode_table_counts_faults_and_valve_assets() -> None:
    """Episodes, episodes with a fault and valve-fault counts per mode.

    Independent: yes, because three episodes are written out.
    """
    lineup, cond = load("lineup_facts"), load("conditions")

    def make(mode: str, faults: tuple[tuple[str, str, float], ...]) -> Any:
        return cond.Condition("coastal", 25.0, 300.0, False, mode, "receipt", faults)

    conds = {
        "a": make("M1", (("restriction_obstruction", "XV-R101", 10.0),)),
        "b": make("M1", ()),
        "c": make("M2", (("bias", "PT-001", 5.0),)),
    }
    rows = lineup.per_mode(conds)
    assert rows["M1"]["episodes"] == 2
    assert rows["M1"]["with_fault"] == 1
    assert rows["M1"]["valve_faults"] == {"XV-R101": 1}
    assert rows["M2"]["valve_faults"] == {}
