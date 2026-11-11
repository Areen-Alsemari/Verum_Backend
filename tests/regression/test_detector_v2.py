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
