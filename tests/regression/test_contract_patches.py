"""Contract patches: applying them to the reference reproduces ``config/``.

Inputs: ``config/reference/`` (unmodified originals), ``config/patches/`` and
the working contracts in ``config/``. Outputs: pass/fail.
Key assumptions: a patch entry states the value it replaces, so applying it to
anything but the reference fails; every entry has a reason. The working copy
must equal the patched reference in content and in byte layout.

Source: ``CONTRIBUTING.md`` (inputs and configuration);
``canonical_sensor_contract.json`` (withheld tags).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from verum.contracts import ContractError
from verum.contracts.patches import (
    apply_patches,
    load_patch_file,
    parse_patch_file,
    render_like,
)

WITHHELD = ["YS-201A", "YS-201B", "VT-201A", "VT-201B", "IT-201A", "IT-201B"]


def _patch_names(root: Path) -> list[str]:
    return sorted(p.name for p in (root / "config" / "patches").glob("*.json"))


def test_every_patch_reproduces_its_working_contract(root: Path) -> None:
    names = _patch_names(root)
    assert names == ["canonical_sensor_contract.json"]
    for name in names:
        reference = (root / "config" / "reference" / name).read_bytes()
        patched = apply_patches(json.loads(reference), load_patch_file(name))
        assert (root / "config" / name).read_bytes() == render_like(reference, patched)


def test_reference_is_not_modified_by_patching(root: Path) -> None:
    name = "canonical_sensor_contract.json"
    reference = json.loads((root / "config" / "reference" / name).read_text(encoding="utf-8"))
    before = json.dumps(reference)
    apply_patches(reference, load_patch_file(name))
    assert json.dumps(reference) == before


def test_withheld_patch_content(root: Path) -> None:
    patch = load_patch_file("canonical_sensor_contract.json")
    by_path = {e.path: e for e in patch.entries}
    assert len(patch.entries) == 12
    for tag in WITHHELD:
        ref = by_path[f"/sensors/{tag}/measured_variable_ref"]
        status = by_path[f"/sensors/{tag}/status"]
        assert ref.new is None and isinstance(ref.old, dict)
        assert (status.old, status.new) == ("withheld_missing_device_model", "withheld")
        assert ref.reason and status.reason


def test_patch_fails_on_a_changed_reference(root: Path) -> None:
    name = "canonical_sensor_contract.json"
    document: dict[str, Any] = json.loads((root / "config" / name).read_text(encoding="utf-8"))
    with pytest.raises(ContractError, match="expected"):
        apply_patches(document, load_patch_file(name))


def test_patch_paths_are_checked(root: Path) -> None:
    raw: dict[str, Any] = {
        "file": "x.json",
        "entries": [{"path": "/sensors/NOPE/status", "old": "a", "new": "b", "reason": "r"}],
    }
    document = json.loads((root / "config" / "canonical_sensor_contract.json").read_text())
    with pytest.raises(ContractError, match="no key"):
        apply_patches(document, parse_patch_file(raw))


@pytest.mark.parametrize(
    "entry",
    [
        {"path": "/a", "old": 1, "new": 2},
        {"path": "/a", "old": 1, "new": 2, "reason": ""},
        {"path": "/a", "old": 1, "new": 2, "reason": "r", "extra": 1},
    ],
)
def test_malformed_entries_are_rejected(entry: dict[str, Any]) -> None:
    with pytest.raises(ContractError):
        parse_patch_file({"file": "x.json", "entries": [entry]})
