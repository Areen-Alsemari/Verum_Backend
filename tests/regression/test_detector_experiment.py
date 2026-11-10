"""Tests of the metric code and the guards of the detector experiment, on small synthetic inputs."""

from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

FOLDER = Path(__file__).resolve().parents[2] / "tools" / "detector"


def load(name: str) -> Any:
    """Import one module of the experiment folder, which is not a package."""
    if str(FOLDER) not in sys.path:
        sys.path.insert(0, str(FOLDER))
    return importlib.import_module(name)


def arr(values: list[float]) -> Any:
    return np.asarray(values, dtype=np.float64)


def lab(values: list[int]) -> Any:
    return np.asarray(values, dtype=np.intp)


def test_average_precision_matches_a_hand_computed_curve() -> None:
    """Two positives ranked first and third give AP = 0.5 * 1 + 0.5 * 2/3.

    Independent: yes, because the value is worked out by hand from the precision at each hit.
    """
    metrics = load("metrics")
    score = metrics.average_precision(arr([0.9, 0.8, 0.7, 0.6]), lab([1, 0, 1, 0]))
    assert score == pytest.approx(0.5 + 0.5 * 2 / 3)


def test_constant_scores_give_prevalence_and_chance() -> None:
    """A constant score has AP equal to the prevalence and AUROC 0.5.

    Independent: yes, because ties form one block of the curve whatever the labels are.
    """
    metrics = load("metrics")
    y = lab([1, 0, 0, 0, 1, 0, 0, 0])
    flat = arr([1.0] * 8)
    assert metrics.average_precision(flat, y) == pytest.approx(0.25)
    assert metrics.auroc(flat, y) == pytest.approx(0.5)


def test_auroc_orders_perfect_reversed_and_single_class() -> None:
    """AUROC is 1 for a perfect order, 0 for the reverse, and NaN with one class.

    Independent: yes, because the three cases have known answers.
    """
    metrics = load("metrics")
    y = lab([0, 0, 1, 1])
    assert metrics.auroc(arr([0.1, 0.2, 0.8, 0.9]), y) == pytest.approx(1.0)
    assert metrics.auroc(arr([0.9, 0.8, 0.2, 0.1]), y) == pytest.approx(0.0)
    assert math.isnan(metrics.auroc(arr([0.1, 0.2]), lab([0, 0])))


def test_matched_stage_auroc_compares_inside_each_stage_only() -> None:
    """The stage-matched AUROC weights per-stage AUROCs by pairs and skips one-class stages.

    Independent: yes, because stage A gives 1 on 4 pairs, stage B gives 0 on 1 pair, C is ignored.
    """
    metrics = load("metrics")
    score = arr([1, 2, 0, 0.5, 10, 11, 5, 6])
    y = lab([1, 1, 0, 0, 1, 0, 0, 0])
    stage = lab([1, 1, 1, 1, 2, 2, 3, 3])
    assert metrics.matched_stage_auroc(score, y, stage) == pytest.approx(0.8)
    assert metrics.auroc(score, y) != pytest.approx(0.8)


def test_bootstrap_resamples_whole_episodes_and_repeats_with_the_seed() -> None:
    """Resamples are concatenations of whole episodes and are the same for the same seed.

    Independent: yes, because the episodes have distinct sizes that can be checked.
    """
    metrics = load("metrics")
    groups = metrics.episode_groups(["a", "b", "b", "c", "c", "c"])
    assert [len(g) for g in groups] == [1, 2, 3]
    first = metrics.make_resamples(groups, 20, 7)
    second = metrics.make_resamples(groups, 20, 7)
    assert all(np.array_equal(a, b) for a, b in zip(first, second, strict=True))
    for idx in first:
        sizes = np.bincount(idx, minlength=6)
        assert sizes[1] == sizes[2] and sizes[3] == sizes[4] == sizes[5]


def test_interval_brackets_the_point_value() -> None:
    """The 95% interval of a mean over episodes contains the point value.

    Independent: yes, because the metric is the mean of a fixed vector.
    """
    metrics = load("metrics")
    values = arr([1, 2, 3, 4, 5, 6, 7, 8])
    groups = metrics.episode_groups(["a", "a", "b", "b", "c", "c", "d", "d"])
    res = metrics.make_resamples(groups, 200, 1)
    point, lo, hi = metrics.interval(lambda i: float(values[i].mean()), np.arange(8), res)
    assert lo <= point <= hi


def test_cross_fitted_alarms_use_the_other_fold_only() -> None:
    """A fold's threshold is the 95th percentile of the other fold's fault-free scores.

    Independent: yes, because fold 1 holds the scores 0 to 99, whose quantile 94.05 is known.
    """
    metrics = load("metrics")
    score = np.r_[np.arange(100.0), [96.0, 97.0, 98.0, 99.0, 100.0]]
    y = lab([0] * 105)
    folds = lab([1] * 100 + [0] * 5)
    alarms = metrics.cross_fit_alarms(score, y, folds, 0.05)
    assert alarms[100:].tolist() == [True] * 5
    assert alarms[:100].sum() == 0


def test_fold_of_reads_the_identifier_as_hexadecimal() -> None:
    """The fold is the parity of the hexadecimal identifier.

    Independent: yes, because 0x10 is even and 0x11 is odd.
    """
    metrics = load("metrics")
    assert metrics.fold_of("EP-000000000010") == 0
    assert metrics.fold_of("EP-000000000011") == 1


def test_shuffled_labels_give_chance_level_metrics() -> None:
    """With permuted labels a perfectly informative score falls to prevalence and 0.5.

    Independent: yes, because the permutation breaks the link between score and label.
    """
    metrics = load("metrics")
    rng = np.random.default_rng(3)
    y = (rng.random(600) < 0.2).astype(np.intp)
    stage = np.repeat(np.arange(1, 7), 100).astype(np.intp)
    out = metrics.shuffle_control(y.astype(np.float64) + 0.1 * rng.random(600), y, stage, 50, 5)
    assert out["ap"][0] == pytest.approx(y.mean(), abs=0.03)
    assert out["auroc"][0] == pytest.approx(0.5, abs=0.03)
    assert out["matched"][0] == pytest.approx(0.5, abs=0.03)


def test_guard_allows_train_and_validation_and_rejects_the_rest() -> None:
    """Train and validation files pass; test, evaluator and foreign episodes are rejected.

    Independent: yes, because the paths are written out in the test.
    """
    guard = load("guard")
    base = "/x/reference_release_v2/verum_reference_v2/"
    kept = {"EP-1"}
    ok = [
        "role_views/a/train.jsonl.gz",
        "role_views/a/validation.jsonl.gz",
        "examples/train/EP-9.jsonl.gz",
        "examples/validation/EP-9.jsonl.gz",
        "knowledge/public_reference.json",
        "role_views_manifest.json",
        "observations/EP-1/observations.jsonl.gz",
    ]
    bad = [
        "role_views/a/test.jsonl.gz",
        "examples/test/EP-9.jsonl.gz",
        "evaluator/x.json",
        "observations/EP-2/observations.jsonl.gz",
        "inspection_records/a.json",
    ]
    assert all(guard.classify(base + p, kept) == "allowed" for p in ok)
    assert all(guard.classify(base + p, kept) == "rejected" for p in bad)
    assert guard.classify("/somewhere/else.py", kept) == "outside"


def test_allowed_feature_columns_are_exactly_the_planned_ones() -> None:
    """The feature columns are the three planned statistics of the 14 numeric tags.

    Independent: yes, because the expected list is built from the plan, not from the code.
    """
    windows = load("windows")
    tags = ["FT-001", "FT-201", "LT-101", "LT-102", "LT-103", "PT-001", "PT-201", "PT-202A",
            "PT-202B", "PT-203", "TT-001", "TT-101", "TT-102", "TT-103"]  # fmt: skip
    expected = {f"{t}:{s}" for t in tags for s in ("mean", "slope_per_s", "spread")}
    columns = windows.feature_columns()
    assert set(columns) == expected and len(columns) == 42
    forbidden = ("age", "count", "rows", "missing", "quality", "available", "position", "stage")
    assert not [c for c in columns if any(f in c for f in forbidden)]
    assert set(windows.SOURCE_FIELD.values()) == {"mean", "slope_per_s", "standard_deviation"}


def test_cusum_grows_with_a_sustained_shift_in_both_directions() -> None:
    """A shift of 2 sigma for 10 samples gives a CUSUM maximum of 15; a flat series gives 0.

    Independent: yes, because each step adds 2 - 0.5 = 1.5 and ten steps give 15.
    """
    cusum = load("cusum")
    series = np.r_[np.zeros(20), np.full(10, 2.0)]
    assert cusum.cusum_max(series, 0.0, 1.0) == pytest.approx(15.0)
    assert cusum.cusum_max(-series, 0.0, 1.0) == pytest.approx(15.0)
    assert cusum.cusum_max(np.zeros(30), 0.0, 1.0) == 0.0


def test_pooled_baseline_serves_rare_and_unseen_regimes() -> None:
    """A regime below the minimum count, and an unseen one, use the pooled baseline.

    Independent: yes, because the two regimes are given different levels on purpose.
    """
    fitting = load("fitting")
    rng = np.random.default_rng(1)
    big, small = (0,), (1,)
    x = np.r_[rng.normal(10, 1, (300, 1, 1)), rng.normal(50, 1, (50, 1, 1))]
    base = fitting.fit_baseline(x, [big] * 300 + [small] * 50)
    med, _ = base.params([big, small, (7,)])
    assert med[0, 0, 0] == pytest.approx(10, abs=0.3)
    assert med[1, 0, 0] == med[2, 0, 0] == base.pooled[0][0, 0]
    assert base.standardise(np.full((1, 1, 1), np.nan), [big])[0, 0, 0] == 0.0


def test_pca_keeps_the_fewest_components_reaching_the_variance() -> None:
    """Data with two strong directions in five columns keeps two components.

    Independent: yes, because the data are built from two latent factors plus tiny noise.
    """
    fitting = load("fitting")
    rng = np.random.default_rng(2)
    latent = rng.normal(size=(500, 2)) @ rng.normal(size=(2, 5))
    model = fitting.fit_pca(latent + 0.001 * rng.normal(size=(500, 5)))
    assert model.comps.shape == (5, 2)
    t2, spe = model.ratios(latent[:5])
    assert np.all(t2 < 3) and np.all(spe < 3)


def test_quadratic_fit_recovers_exact_coefficients() -> None:
    """A noiseless quadratic is recovered and its residual is zero.

    Independent: yes, because the data come from known coefficients.
    """
    fitting = load("fitting")
    q = np.linspace(0, 10, 30)
    y = 2.0 + 0.5 * q + 0.1 * q**2
    coef = fitting.fit_quadratic(q, y)
    assert coef == pytest.approx([2.0, 0.5, 0.1])
    assert np.abs(y - fitting.predict_quadratic(coef, q)).max() < 1e-9


def test_residual_dead_zone_and_missing_value() -> None:
    """A residual inside one sigma scores 0, beyond it the excess in sigmas, NaN scores 0.

    Independent: yes, because the numbers follow from the stated dead-zone rule.
    """
    candidates = load("candidates")
    fit = candidates.Fit(np.zeros(3), 2.0)
    assert fit.z(1.9) == 0.0
    assert fit.z(-6.0) == pytest.approx(2.0)
    assert fit.z(float("nan")) == 0.0


def test_pump_state_and_fault_kind_labels() -> None:
    """The pump state comes from the two pump tags; fault kinds group the mechanisms.

    Independent: yes, because the mapping is written out in the test.
    """
    candidates, windows = load("candidates"), load("windows")
    a, b = candidates.PUMP_A, candidates.PUMP_B
    regime = [0] * 16
    assert candidates.pump_state(tuple(regime)) == "none"
    regime[a] = 1
    assert candidates.pump_state(tuple(regime)) == "A"
    regime[b] = 1
    assert candidates.pump_state(tuple(regime)) == "AB"
    assert windows.fault_kind([]) == "none"
    assert windows.fault_kind([{"mechanism": "misroute_a"}]) == "misrouting"
    assert windows.fault_kind([{"mechanism": "leak"}, {"mechanism": "pump"}]) == "multi"


def test_fusion_uses_the_smallest_calibrated_p_value() -> None:
    """The fused score is minus log10 of the smallest (count above + 1) / (n + 1).

    Independent: yes, because the reference scores are four numbers with a known rank.
    """
    candidates = load("candidates")
    train = {"x": arr([1, 2, 3, 4]), "y": arr([1, 2, 3, 4])}
    fused = candidates.fuse(train, {"x": arr([5, 0]), "y": arr([2.5, 0])})
    assert fused.scores[0] == pytest.approx(-math.log10(1 / 5))
    assert fused.scores[1] == pytest.approx(0.0)


def test_shift_guard_removes_only_the_temperature_level_components() -> None:
    """With the guard on, a temperature level offset no longer raises the per-tag baseline score.

    Independent: yes, because the window differs from the training mean only in TT-001 level.
    """
    candidates, windows = load("candidates"), load("windows")
    rng = np.random.default_rng(4)
    n = 400
    train = windows.Windows(
        [str(i) for i in range(n)], ["e"] * n, np.ones(n, dtype=np.intp), np.zeros(n),
        np.zeros(n, dtype=np.intp), ["none"] * n, rng.normal(size=(n, 14, 3)), [(0,) * 16] * n,
    )  # fmt: skip
    model = candidates.PerTag(train)
    model.calibrate(rng.random((n, 14)))
    probe = windows.subset(train, np.arange(n) < 1)
    probe.x[:] = 0.0
    probe.x[0, candidates.TAG["TT-001"], 0] = 500.0
    stats = np.zeros((1, 14))
    plain = model.score(probe, stats)
    guarded = model.score(probe, stats, guard=True)
    column = candidates.TAG["TT-001"]
    assert plain.parts[0, column] > 100.0
    assert guarded.parts[0, column] < 3.0
    others = [j for j in range(14) if j not in candidates.SHIFT_IDX]
    assert np.allclose(plain.parts[0, others], guarded.parts[0, others])
