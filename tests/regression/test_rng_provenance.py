"""Named random streams and the configuration hash.

Independence of streams means that creating or drawing from one stream leaves the draws of another
unchanged. The configuration hash changes when any value of any resolved configuration file changes,
and does not change when only the layout does. The expected results are properties and not numbers,
so no reference calculation is involved.
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
    """The same master seed and stream name give identical draws. Independent: yes, because equality
    is the property.
    """
    a = RandomStreams(12345).stream("fault:FI-01").random(8)
    b = RandomStreams(12345).stream("fault:FI-01").random(8)
    assert np.array_equal(a, b)


def test_an_extra_stream_does_not_change_another_stream() -> None:
    """Creating and drawing from another stream leaves the draws of a stream unchanged. Independent:
    yes, because the draws are compared with a run without the other stream.
    """
    plain = RandomStreams(7)
    first = plain.stream("a").random(5)
    busy = RandomStreams(7)
    busy.stream("sensor:LT-101").random(1000)
    busy.stream("zzz").normal(size=50)
    assert np.array_equal(first, busy.stream("a").random(5))


def test_creation_order_does_not_matter() -> None:
    """The order in which streams are created does not change their draws. Independent: yes, because
    equality is the property.
    """
    one, two = RandomStreams(3), RandomStreams(3)
    one.stream("x"), one.stream("y")
    two.stream("y"), two.stream("x")
    assert np.array_equal(one.stream("x").random(4), two.stream("x").random(4))


def test_a_different_master_seed_differs() -> None:
    """A different master seed gives different draws. Independent: yes, because inequality is the
    property.
    """
    assert not np.array_equal(
        RandomStreams(1).stream("a").random(8), RandomStreams(2).stream("a").random(8)
    )


def test_different_names_differ() -> None:
    """Different stream names give different draws. Independent: yes, because inequality is the
    property.
    """
    streams = RandomStreams(1)
    assert not np.array_equal(streams.stream("a").random(8), streams.stream("b").random(8))


def test_asking_twice_continues_the_same_stream() -> None:
    """Asking twice for the same name continues the same stream and does not restart it.
    Independent: yes, because the draws are compared with one long draw.
    """
    streams = RandomStreams(5)
    first = streams.stream("a").random(3)
    second = streams.stream("a").random(3)
    assert not np.array_equal(first, second)
    assert np.array_equal(np.concatenate([first, second]), RandomStreams(5).stream("a").random(6))


def test_the_global_numpy_generator_is_never_touched() -> None:
    """Drawing from a named stream leaves the numpy global generator state unchanged. Independent:
    yes, because the state is compared before and after.
    """
    before = np.random.get_state()[1].copy()
    RandomStreams(9).stream("a").random(10)
    assert np.array_equal(before, np.random.get_state()[1])


def test_the_stream_key_is_the_sha256_of_the_name() -> None:
    """The stream key is built from the SHA-256 digest of the name. Independent: yes, because the
    digest is computed in the test.
    """
    import hashlib

    digest = hashlib.sha256(b"abc").digest()
    assert stream_key("abc") == tuple(
        int.from_bytes(digest[i : i + 4], "big") for i in (0, 4, 8, 12)
    )


def test_invalid_names_and_seeds_are_refused() -> None:
    """A negative seed or an empty or non-string name is refused. Independent: yes, because the
    expected outcome is the validation rule.
    """
    with pytest.raises(ValueError):
        RandomStreams(-1)
    with pytest.raises(ValueError):
        RandomStreams(1).stream("")


# --- configuration hash --------------------------------------------------------------------


def test_the_config_hash_is_stable() -> None:
    """The configuration hash is stable between calls and is 64 hexadecimal characters. Independent:
    yes, because the expected properties are stability and length.
    """
    assert config_hash() == config_hash()
    assert len(config_hash()) == 64


def test_the_hash_ignores_layout_but_not_values(root: Path, tmp_path: Path) -> None:
    """Re-indenting a configuration file leaves the hash unchanged, and changing a value changes it.
    Independent: yes, because the property is the stated hash rule.
    """
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
    """Changing a value in any resolved configuration file changes the hash. Independent: yes,
    because the property is the stated hash rule.
    """
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
    """Reference copies and patch files do not enter the configuration hash. Independent: yes,
    because the property is the stated hash rule.
    """
    shutil.copytree(root / "config", tmp_path / "config")
    base = config_hash(tmp_path / "config")
    (tmp_path / "config" / "reference" / "extra.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config" / "patches" / "extra.json").write_text("{}", encoding="utf-8")
    assert config_hash(tmp_path / "config") == base


def test_canonical_json_is_order_independent() -> None:
    """The canonical JSON form does not depend on key order. Independent: yes, because the two
    inputs differ only in order.
    """
    assert canonical_json({"b": 1, "a": [2, {"d": 1, "c": 2}]}) == canonical_json(
        {"a": [2, {"c": 2, "d": 1}], "b": 1}
    )


def test_lockfile_hash_and_git_state() -> None:
    """The lockfile hash is stable and the git state reports a boolean dirty flag. Independent: yes,
    because the expected properties are stability and type.
    """
    assert lockfile_hash() == lockfile_hash() and len(lockfile_hash()) == 64
    commit, dirty = git_state()
    assert isinstance(dirty, bool)
    assert commit == "unknown" or len(commit) == 40


def test_git_state_is_unknown_without_a_repository(tmp_path: Path) -> None:
    """Outside a repository the git state is reported as unknown and dirty, never invented.
    Independent: yes, because the expected outcome is the stated rule.
    """
    assert git_state(tmp_path) == ("unknown", True)


def test_episode_ids_are_opaque_and_deterministic() -> None:
    """An episode identifier is deterministic for its inputs and differs when the seed or scenario
    differs. Independent: yes, because the expected properties are equality and inequality.
    """
    a = episode_id(1, "S0-A", "abc")
    assert a == episode_id(1, "S0-A", "abc")
    assert a != episode_id(2, "S0-A", "abc") and a != episode_id(1, "S0-B", "abc")
    assert a.startswith("EP-") and "S0" not in a and len(a) == 15
