"""Tests for the pooled R4 version, unknown evidence and the stress perturbations."""

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


def synthetic(n: int = 600, seed: int = 5) -> Any:
    """Fault-free windows from a simple plant: balanced flows, pressures linear in flow."""
    windows, cand = load("windows"), load("candidates")
    rng = np.random.default_rng(seed)
    x = np.zeros((n, 14, 3))
    q = rng.uniform(300.0, 600.0, n)
    col = cand.TAG
    x[:, col["FT-201"], 0] = q
    x[:, col["FT-001"], 0] = q + rng.normal(0.0, 0.5, n)
    for tag in ("LT-101", "LT-102", "LT-103"):
        x[:, col[tag], 1] = rng.normal(0.0, 1e-5, n)
    x[:, col["PT-201"], 0] = 2.0 + rng.normal(0.0, 0.01, n)
    for pump in ("A", "B"):
        x[:, col[f"PT-202{pump}"], 0] = 8.0 + 0.004 * q + rng.normal(0.0, 0.01, n)
    x[:, col["PT-203"], 0] = 7.0 + 0.004 * q + rng.normal(0.0, 0.01, n)
    x[:, col["PT-001"], 0] = 1.0 + 0.002 * q + rng.normal(0.0, 0.01, n)
    lineup = []
    for i in range(n):
        key = [0] * 16
        key[cand.PUMP_A if i % 2 == 0 else cand.PUMP_B] = 1
        lineup.append(tuple(key))
    regime = [("coastal", 25.0, 300.0)] * n
    return windows.Windows(
        [str(i) for i in range(n)], ["e"] * n, np.ones(n, dtype=np.intp), np.zeros(n),
        np.zeros(n, dtype=np.intp), ["none"] * n, x, lineup, regime,
    )  # fmt: skip


def test_pooled_r4_scores_do_not_depend_on_the_regime_key() -> None:
    """Scrambling every regime key leaves the pooled scores exactly unchanged.

    Independent: yes, because the keys are replaced by values no fit has seen.
    """
    from dataclasses import replace

    cand = load("candidates")
    w = synthetic()
    model = cand.Residuals(w, pooled_r4=True)
    scrambled = replace(w, regime=[("x", float(i), -1.0) for i in range(len(w.ids))])
    assert np.array_equal(model.score(w).scores, model.score(scrambled).scores)


def test_unknown_inputs_remove_only_the_residuals_that_read_them() -> None:
    """A missing input makes its residuals unknown; the rest still give a score.

    Independent: yes, because the dependencies are listed in the plan and checked one by one.
    """
    cand = load("candidates")
    w = synthetic()
    model = cand.Residuals(w, pooled_r4=True)
    model.unknown = float("nan")
    one = load("windows").subset(w, np.arange(len(w.ids)) < 1)
    clean = model.score(one)
    assert np.isfinite(clean.parts).all()

    def parts(edit: Any) -> Any:
        probe = load("windows").subset(w, np.arange(len(w.ids)) < 1)
        edit(probe)
        return model.score(probe)

    r = parts(lambda p: p.x.__setitem__((0, cand.TAG["FT-001"], 0), np.nan))
    assert np.isnan(r.parts[0, [0, 3]]).all() and np.isfinite(r.parts[0, [1, 2]]).all()
    assert np.isfinite(r.scores[0])

    def lose_pump_tag(p: Any) -> None:
        p.lineup[0] = tuple(-1 if i == cand.PUMP_A else v for i, v in enumerate(p.lineup[0]))

    pump = parts(lose_pump_tag)
    assert np.isnan(pump.parts[0, [1, 2]]).all() and np.isfinite(pump.parts[0, [0, 3]]).all()
    flow = parts(lambda p: p.x.__setitem__((0, cand.TAG["FT-201"], 0), np.nan))
    assert np.isnan(flow.parts[0, [0, 1, 2]]).all() and np.isfinite(flow.parts[0, 3])
    both = parts(lambda p: (p.x.__setitem__((0, cand.TAG["FT-201"], 0), np.nan),
                            p.x.__setitem__((0, cand.TAG["PT-001"], 0), np.nan)))  # fmt: skip
    assert np.isnan(both.scores[0])


def test_unknown_mode_matches_the_default_when_nothing_is_missing() -> None:
    """With complete inputs the unknown mode returns the default scores.

    Independent: yes, because the same complete windows are scored both ways.
    """
    cand = load("candidates")
    w = synthetic()
    model = cand.Residuals(w, pooled_r4=True)
    default = model.score(w).scores
    model.unknown = float("nan")
    assert np.array_equal(model.score(w).scores, default)


def test_dropping_inputs_makes_exactly_m_of_twelve_unknown_per_window() -> None:
    """Each window loses m inputs, drawn without replacement, and nothing else changes.

    Independent: yes, because the count of lost inputs is read off the perturbed arrays.
    """
    stress, cand = load("stress"), load("candidates")
    w = synthetic(200)
    out = stress.drop_inputs(w, np.random.default_rng(2), 3)
    lost = np.zeros(200, dtype=int)
    for tag, stat in stress.NUMERIC_INPUTS:
        lost += np.isnan(out.x[:, cand.TAG[tag], stat]).astype(int)
    for pos in stress.PUMP_POSITIONS:
        lost += np.asarray([key[pos] == -1 for key in out.lineup]).astype(int)
    assert (lost == 3).all()
    numeric_lost = sum(
        int(np.isnan(out.x[:, cand.TAG[t], s]).sum()) for t, s in stress.NUMERIC_INPUTS
    )
    assert int(np.isnan(out.x).sum()) == numeric_lost


def test_noise_scales_move_the_residual_by_one_fault_free_scale() -> None:
    """The flow noise equals the R1 scale and a level slope noise is that scale per tank area.

    Independent: yes, because the expected values follow from the stated mapping.
    """
    stress, cand = load("stress"), load("candidates")
    w = synthetic()
    model = cand.Residuals(w, pooled_r4=True)
    sd = stress.noise_scales(model)
    names = [t for t, _ in stress.NUMERIC_INPUTS]
    assert sd[names.index("FT-001")] == model.mass.sigma
    area = model.mass.coef[0]
    assert abs(sd[names.index("LT-101")] - model.mass.sigma / (3600.0 * area)) < 1e-15
    assert sd[names.index("PT-001")] == model.fits[("R4", "*", "")].sigma


def test_noise_touches_only_the_ten_numeric_inputs_and_repeats_with_the_seed() -> None:
    """Other columns and the lineup stay as they were; the same seed gives the same noise.

    Independent: yes, because untouched columns are compared with the input.
    """
    stress, cand = load("stress"), load("candidates")
    w = synthetic(100)
    scales = np.ones(10)
    a = stress.add_noise(w, np.random.default_rng(4), scales, 2)
    b = stress.add_noise(w, np.random.default_rng(4), scales, 2)
    assert np.array_equal(a.x, b.x)
    used = {(cand.TAG[t], s) for t, s in stress.NUMERIC_INPUTS}
    for j in range(14):
        for s in range(3):
            same = np.array_equal(a.x[:, j, s], w.x[:, j, s])
            assert same == ((j, s) not in used)
    assert a.lineup == w.lineup


def test_unscorable_windows_rank_last_and_never_alarm() -> None:
    """A NaN score counts as not alarmed and sits below every scorable window.

    Independent: yes, because five windows are written out with known answers.
    """
    stress_eval = load("stress_eval")
    ev = load("evaluate")
    s = np.asarray([np.nan, 5.0, 1.0, np.nan, 4.0])
    d = {"faulty": np.asarray([1.0, 1.0, 0.0, 1.0, 0.0]), "stage": np.ones(5)}
    meta = {"episodes": ["EP-A", "EP-B", "EP-C", "EP-D", "EP-E"], "kind": ["pump"] * 5}
    c = ev.Context(d, meta)
    out = stress_eval.one_setting(s, c, np.asarray([3.0, 3.0]))
    assert out["scorable_all"] == 0.6
    assert abs(out["scorable_faulty"] - 1 / 3) < 1e-4
    assert abs(out["recall"][0] - 1 / 3) < 1e-4  # values are rounded to four decimals
    assert out["far"][0] == 0.5


def test_permute_reorders_every_per_window_field_together() -> None:
    """Ids, arrays and lists follow the same permutation.

    Independent: yes, because the permutation is written out.
    """
    check = load("input_check")
    w = synthetic(4)
    out = check.permute(w, np.asarray([3, 2, 1, 0]))
    assert out.ids == ["3", "2", "1", "0"]
    assert np.array_equal(out.x[0], w.x[3])
    assert out.lineup[0] == w.lineup[3]


def test_field_list_holds_the_twelve_inputs() -> None:
    """Ten statistics and two pump latest values.

    Independent: yes, because the list is written out in the plan.
    """
    check = load("input_check")
    rows = check.field_list()
    assert len(rows) == 12
    assert ("LT-103", "slope_per_s") in rows
    assert ("P-101B", "latest_value") in rows
    assert sum(f == "mean" for _, f in rows) == 7
