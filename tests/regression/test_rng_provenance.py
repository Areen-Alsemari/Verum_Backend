"""Named random streams and the configuration hash.

Inputs: ``verum.rng``, ``verum.provenance`` and copies of ``config/``. Outputs:
pass/fail.
Key assumptions: independence of streams means that creating or drawing from one
stream leaves the draws of another unchanged; the configuration hash changes when
any value of any resolved configuration file changes and not when only the
layout does. Expected values are properties, not numbers, so no reference
calculation is involved (independent of the implementation by construction).

Source: ``revised/05_simulation_validation_dataset.md`` sections 6.10, 8.6 and 13.1.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from verum.provenance import (
    canonical_json,
    config_hash,
    episode_id,
    git_state,
    lockfile_hash,
)
from verum.rng import RandomStreams, stream_key

# --- random streams ---------------------------------------------------------------------


def test_same_seed_and_name_give_identical_draws() -> None:
    a = RandomStreams(12345).stream("fault:FI-01").random(8)
    b = RandomStreams(12345).stream("fault:FI-01").random(8)
    assert np.array_equal(a, b)


def test_an_extra_stream_does_not_change_another_stream() -> None:
    plain = RandomStreams(7)
    first = plain.stream("a").random(5)
    busy = RandomStreams(7)
    busy.stream("sensor:LT-101").random(1000)
    busy.stream("zzz").normal(size=50)
    assert np.array_equal(first, busy.stream("a").random(5))


def test_creation_order_does_not_matter() -> None:
    one, two = RandomStreams(3), RandomStreams(3)
    one.stream("x"), one.stream("y")
    two.stream("y"), two.stream("x")
    assert np.array_equal(one.stream("x").random(4), two.stream("x").random(4))


def test_a_different_master_seed_differs() -> None:
    assert not np.array_equal(
        RandomStreams(1).stream("a").random(8), RandomStreams(2).stream("a").random(8)
    )


def test_different_names_differ() -> None:
    streams = RandomStreams(1)
    assert not np.array_equal(streams.stream("a").random(8), streams.stream("b").random(8))


def test_asking_twice_continues_the_same_stream() -> None:
    streams = RandomStreams(5)
    first = streams.stream("a").random(3)
    second = streams.stream("a").random(3)
    assert not np.array_equal(first, second)
    assert np.array_equal(np.concatenate([first, second]), RandomStreams(5).stream("a").random(6))


def test_the_global_numpy_generator_is_never_touched() -> None:
    before = np.random.get_state()[1].copy()
    RandomStreams(9).stream("a").random(10)
    assert np.array_equal(before, np.random.get_state()[1])


def test_the_stream_key_is_the_sha256_of_the_name() -> None:
    import hashlib

    digest = hashlib.sha256(b"abc").digest()
    assert stream_key("abc") == tuple(
        int.from_bytes(digest[i : i + 4], "big") for i in (0, 4, 8, 12)
    )


def test_invalid_names_and_seeds_are_refused() -> None:
    with pytest.raises(ValueError):
        RandomStreams(-1)
    with pytest.raises(ValueError):
        RandomStreams(1).stream("")


# --- configuration hash --------------------------------------------------------------------


def test_the_config_hash_is_stable() -> None:
    assert config_hash() == config_hash()
    assert len(config_hash()) == 64


def test_the_hash_ignores_layout_but_not_values(root: Path, tmp_path: Path) -> None:
    shutil.copytree(root / "config", tmp_path / "config")
    base = config_hash(tmp_path / "config")
    path = tmp_path / "config" / "hydraulics.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(document, indent=8), encoding="utf-8")
    assert config_hash(tmp_path / "config") == base


def _all_config_files(root: Path) -> list[str]:
    base = root / "config"
    names = [p.relative_to(base).as_posix() for p in sorted(base.glob("*.json"))]
    return names + [p.relative_to(base).as_posix() for p in sorted(base.glob("scenarios/*.json"))]


def _change_first_number(node: Any) -> bool:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                node[key] = value + 1
                return True
            if _change_first_number(value):
                return True
    if isinstance(node, list):
        for i, value in enumerate(node):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                node[i] = value + 1
                return True
            if _change_first_number(value):
                return True
    return False


def test_every_resolved_config_file_is_covered_and_changes_the_hash(
    root: Path, tmp_path: Path
) -> None:
    names = _all_config_files(root)
    assert len(names) >= 10
    for name in names:
        work = tmp_path / name.replace("/", "_")
        shutil.copytree(root / "config", work)
        base = config_hash(work)
        path = work / name
        document = json.loads(path.read_text(encoding="utf-8"))
        if not _change_first_number(document):
            document["_note"] = "changed"
        path.write_text(json.dumps(document), encoding="utf-8")
        assert config_hash(work) != base, name


def test_reference_and_patch_files_do_not_enter_the_hash(root: Path, tmp_path: Path) -> None:
    shutil.copytree(root / "config", tmp_path / "config")
    base = config_hash(tmp_path / "config")
    (tmp_path / "config" / "reference" / "extra.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config" / "patches" / "extra.json").write_text("{}", encoding="utf-8")
    assert config_hash(tmp_path / "config") == base


def test_canonical_json_is_order_independent() -> None:
    assert canonical_json({"b": 1, "a": [2, {"d": 1, "c": 2}]}) == canonical_json(
        {"a": [2, {"c": 2, "d": 1}], "b": 1}
    )


def test_lockfile_hash_and_git_state() -> None:
    assert lockfile_hash() == lockfile_hash() and len(lockfile_hash()) == 64
    commit, dirty = git_state()
    assert isinstance(dirty, bool)
    assert commit == "unknown" or len(commit) == 40


def test_git_state_is_unknown_without_a_repository(tmp_path: Path) -> None:
    assert git_state(tmp_path) == ("unknown", True)


def test_episode_ids_are_opaque_and_deterministic() -> None:
    a = episode_id(1, "S0-A", "abc")
    assert a == episode_id(1, "S0-A", "abc")
    assert a != episode_id(2, "S0-A", "abc") and a != episode_id(1, "S0-B", "abc")
    assert a.startswith("EP-") and "S0" not in a and len(a) == 15
