"""Tests for the second detector experiment: set conditions, the regime key and grouped folds."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

FOLDER = Path(__file__).resolve().parents[2] / "tools" / "detector"


def load(name: str) -> Any:
    """Import one module of the experiment folder, which is not a package."""
    if str(FOLDER) not in sys.path:
        sys.path.insert(0, str(FOLDER))
    return importlib.import_module(name)


def doc(temperature: float = 40.0, onsets: tuple[float, ...] = ()) -> dict[str, Any]:
    strata = {"atmosphere": "coastal", "temperature_c": temperature, "setpoint_m3h": 400,
              "stress": temperature == 45.0, "mode": "m", "family": "PIPE_LEAK"}  # fmt: skip
    faults = [{"subtype": "leak", "asset_id": f"A{i}", "onset_s": o} for i, o in enumerate(onsets)]
    return {"strata": strata, "faults": faults}


def test_guard_allows_only_the_label_file_of_allowed_episodes() -> None:
    """The label file of an allowed episode opens; other files and other episodes do not.

    Independent: yes, because the paths are written out in the test.
    """
    guard = load("guard")
    base = "/x/reference_release_v2/verum_reference_v2/evaluator/source_episodes/"
    kept = {"EP-1"}
    assert guard.classify(base + "EP-1/labels.json", kept) == "allowed"
    assert guard.classify(base + "EP-2/labels.json", kept) == "rejected"
    assert guard.classify(base + "EP-1/truth.json", kept) == "rejected"
    assert guard.classify(base + "EP-1/sub/labels.json", kept) == "rejected"


def test_regime_key_holds_only_operator_set_values() -> None:
    """The key is atmosphere, temperature and set point; faults and onsets do not enter it.

    Independent: yes, because the expected tuple is written out.
    """
    cond = load("conditions")
    healthy = cond.parse(doc())
    faulty = cond.parse(doc(onsets=(900.0, 600.0)))
    assert healthy.regime == ("coastal", 40.0, 400.0)
    assert faulty.regime == healthy.regime
    assert faulty.onset_s == 600.0
    assert healthy.onset_s is None


def test_unit_is_family_atmosphere_temperature() -> None:
    """The unit of the campaign split ignores the set point.

    Independent: yes, because the expected tuple is written out.
    """
    cond = load("conditions")
    one = cond.parse(doc(temperature=45.0))
    assert one.unit == ("PIPE_LEAK", "coastal", 45.0)
    assert one.stress is True


def test_nearest_key_names_the_tags_that_differ() -> None:
    """The nearest fault-free key is the one with the fewest differing tags.

    Independent: yes, because the keys are tiny and the answer is counted by hand.
    """
    audit = load("regime_audit")
    tags = audit.BOOL_TAGS
    n = len(tags)
    base = tuple(False for _ in range(n))
    near = tuple(i == 3 for i in range(n))
    far = tuple(i in (0, 1, 2) for i in range(n))
    probe = tuple(i in (3, 5) for i in range(n))
    best, diff = audit.nearest(probe, [base, near, far])
    assert best == near
    assert diff == [tags[5]]


def tiny_windows(n: int = 4) -> Any:
    import numpy as np

    windows = load("windows")
    lineup = [(i % 2,) + (0,) * 15 for i in range(n)]
    return windows.Windows(
        [f"w{i}" for i in range(n)], ["EP-A", "EP-A", "EP-B", "EP-B"][:n],
        np.ones(n, dtype=np.intp),
        np.arange(n, dtype=np.float64), np.zeros(n, dtype=np.intp), ["none"] * n,
        np.zeros((n, 14, 3)), lineup, list(lineup),
    )  # fmt: skip


def test_rekeying_replaces_the_regime_and_keeps_the_lineup() -> None:
    """The regime becomes the set conditions; the lineup key stays for the pump state.

    Independent: yes, because the expected keys are written out.
    """
    cond = load("conditions")
    w = tiny_windows()
    conds = {"EP-A": cond.parse(doc(25.0)), "EP-B": cond.parse(doc(40.0, (600.0,)))}
    out = cond.apply(w, conds)
    assert out.regime[0] == ("coastal", 25.0, 400.0)
    assert out.regime[3] == ("coastal", 40.0, 400.0)
    assert out.lineup == w.lineup
    assert out.unit[0] == ("PIPE_LEAK", "coastal", 25.0)
    assert out.onset_s[3] == 600.0
    assert out.onset_s[0] != out.onset_s[0]


def test_subset_keeps_every_per_window_field_aligned() -> None:
    """Selecting windows selects the same rows of lineup, regime, unit and onset.

    Independent: yes, because the selection is written out.
    """
    import numpy as np

    cond, windows = load("conditions"), load("windows")
    w = tiny_windows()
    conds = {"EP-A": cond.parse(doc(25.0)), "EP-B": cond.parse(doc(40.0, (600.0,)))}
    picked = windows.subset(cond.apply(w, conds), np.asarray([False, True, False, True]))
    assert picked.ids == ["w1", "w3"]
    assert picked.lineup == [(1,) + (0,) * 15] * 2
    assert [r[1] for r in picked.regime] == [25.0, 40.0]
    assert picked.unit[1][2] == 40.0
    assert picked.onset_s[1] == 600.0


def test_comparison_helpers_format_and_difference() -> None:
    """The change column is new minus old, three decimals, signed.

    Independent: yes, because the numbers are written out.
    """
    rc = load("rekey_compare")
    assert rc.delta([0.5, 0.4, 0.6], [0.75, 0.7, 0.8]) == "+0.250"
    assert rc.delta([0.5, 0.4, 0.6], [0.25, 0.1, 0.3]) == "-0.250"
    assert rc.fmt([0.5, 0.25, 0.75]) == "0.500 (0.250 to 0.750)"


def test_units_are_assigned_to_folds_by_sorted_position() -> None:
    """Unit i of the sorted list goes to fold i mod k, and a unit never splits.

    Independent: yes, because the expected assignment is counted by hand.
    """
    systems = load("systems")
    units = [("b", "x", 25.0), ("a", "x", 25.0), ("c", "y", 40.0), ("a", "x", 25.0)]
    got = systems.fold_map(units, 2)
    assert got == {("a", "x", 25.0): 0, ("b", "x", 25.0): 1, ("c", "y", 40.0): 0}


def test_regression_baseline_recovers_a_known_condition_law() -> None:
    """A column that is an exact quadratic in the set conditions leaves a zero residual.

    Independent: yes, because the law is written out and evaluated by hand.
    """
    import numpy as np

    fitting = load("fitting")
    regimes = [(a, t, q) for a in ("coastal", "inland") for t in (25.0, 35.0, 45.0)
               for q in (300.0, 450.0, 600.0)] * 3  # fmt: skip
    x = np.zeros((len(regimes), 14, 3))
    for i, (a, t, q) in enumerate(regimes):
        x[i, 0, 0] = 2.0 + 0.5 * (t - 35.0) / 10.0 + 3.0 * ((q - 450.0) / 150.0) ** 2
        x[i, 0, 0] += 1.0 if a == "inland" else 0.0
    base = fitting.fit_regression_baseline(x, regimes)
    pred, _ = base.params(regimes)
    assert np.allclose(pred[:, 0, 0], x[:, 0, 0], atol=1e-9)
    z = base.standardise(x, regimes)
    assert np.allclose(z[:, 0, 0], 0.0, atol=1e-3)


def test_out_of_sample_reference_never_scores_a_window_with_a_model_fitted_on_it() -> None:
    """With E4 each reference score comes from a model that did not see that window.

    Independent: yes, because a stub model returns 1 for windows it was fitted on and 0 for others.
    """
    import numpy as np

    systems = load("systems")
    candidates = load("candidates")
    w = tiny_windows(4)
    w.unit = [("f", "a", 25.0), ("f", "a", 25.0), ("g", "a", 35.0), ("h", "a", 40.0)]

    class Stub:
        def __init__(self, fit: Any, spec: Any) -> None:
            self.seen = set(fit.ids)

        def score(self, w: Any) -> dict[str, Any]:
            s = np.asarray([1.0 if i in self.seen else 0.0 for i in w.ids])
            return {"C": candidates.Scored(s, s[:, None], ["C"])}

    original = systems.Components
    systems.Components = Stub
    try:
        inner = systems.reference(w, systems.Spec(e4=True))["C"]
        plain = systems.reference(w, systems.Spec(e4=False))["C"]
    finally:
        systems.Components = original
    assert np.all(inner == 0.0)
    assert np.all(plain == 1.0)


def test_keep_rule_needs_both_lower_bounds_above_zero() -> None:
    """A candidate stays only if both paired lower bounds are positive.

    Independent: yes, because the three cases are written out.
    """
    cv_eval = load("cv_eval")
    good = {"ap": [0.05, 0.01, 0.09], "matched_auroc": [0.03, 0.002, 0.06]}
    one_bad = {"ap": [0.05, 0.01, 0.09], "matched_auroc": [0.03, -0.01, 0.06]}
    zero = {"ap": [0.0, 0.0, 0.0], "matched_auroc": [0.0, 0.0, 0.0]}
    assert cv_eval.keep_rule(good) is True
    assert cv_eval.keep_rule(one_bad) is False
    assert cv_eval.keep_rule(zero) is False


def test_detection_delay_counts_first_alarm_and_never_alarmed_episodes() -> None:
    """Delay is the first alarmed faulty cutoff minus the onset; silent episodes are counted.

    Independent: yes, because two episodes are written out with known answers.
    """
    import numpy as np

    cv_eval = load("cv_eval")
    eps = ["A", "A", "A", "B", "B"]
    y = np.asarray([0, 1, 1, 1, 1])
    alarms = np.asarray([True, False, True, False, False])
    cutoff = np.asarray([300.0, 600.0, 900.0, 600.0, 900.0])
    onset = np.asarray([np.nan, 450.0, 450.0, 500.0, 500.0])
    out = cv_eval.detection_delay(alarms, y, eps, cutoff, onset)
    assert out["episodes"] == 2
    assert out["never_alarmed"] == 1
    assert out["quartiles_s"] == [450.0, 450.0, 450.0]


def test_tag_rank_counts_ties_against_the_faulty_tag() -> None:
    """The faulty tag is first only if its evidence is strictly the largest.

    Independent: yes, because the evidence rows are written out.
    """
    import numpy as np

    cv_eval = load("cv_eval")
    tags = np.zeros((3, 14))
    tags[0, 2] = 5.0
    tags[1, 2] = 5.0
    tags[1, 7] = 5.0
    tags[2, 2] = 1.0
    tags[2, 7] = 3.0
    tags[2, 9] = 2.0
    names = load("windows").NUMERIC_TAGS
    got = cv_eval.tag_ranks(tags, [names[2], names[2], names[2], ""][:3])
    assert got.tolist() == [1.0, 2.0, 3.0]


def test_pair_residuals_are_zero_for_agreeing_sensors_and_positive_for_an_offset() -> None:
    """Equal tank temperatures give no residual; one offset tank gives evidence on that tag.

    Independent: yes, because the offsets are chosen by hand.
    """
    import numpy as np

    candidates, windows = load("candidates"), load("windows")
    rng = np.random.default_rng(3)
    n = 300
    w = tiny_windows(4)
    x = np.zeros((n, 14, 3))
    for tag in ("TT-101", "TT-102", "TT-103"):
        x[:, candidates.TAG[tag], 0] = 30.0 + rng.normal(0.0, 0.05, n)
    w = windows.Windows(
        [str(i) for i in range(n)], ["e"] * n, np.ones(n, dtype=np.intp), np.zeros(n),
        np.zeros(n, dtype=np.intp), ["none"] * n, x, [(0,) * 16] * n, [(0,) * 16] * n,
    )  # fmt: skip
    pair = candidates.PairResiduals(w, ["A"] * n)
    probe = windows.subset(w, np.arange(n) < 2)
    probe.x[1, candidates.TAG["TT-102"], 0] += 5.0
    score, tags = pair.score(probe, ["A", "A"])
    typical, _ = pair.score(w, ["A"] * n)
    assert float(np.median(typical[:, 0])) < 3.0
    assert score[1, 0] > 20.0
    assert int(np.argmax(tags[1])) == candidates.TAG["TT-102"]


def test_condition_prior_is_the_regime_fault_rate() -> None:
    """The condition-only reference gives each window the fault rate of its regime in the fit set.

    Independent: yes, because the rates are counted by hand.
    """
    import numpy as np

    cv, windows = load("cv"), load("windows")
    w = tiny_windows(4)
    w.regime = [("c", 25.0, 300.0), ("c", 25.0, 300.0), ("c", 35.0, 300.0), ("c", 45.0, 300.0)]
    w.faulty = np.asarray([1, 0, 0, 1], dtype=np.intp)
    apply = windows.subset(w, np.asarray([True, False, True, True]))
    got = cv.regime_prior(w, apply)
    assert got.tolist() == [0.5, 0.0, 1.0]
