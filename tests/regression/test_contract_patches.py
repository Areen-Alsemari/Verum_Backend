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
    assert names == ["canonical_sensor_contract.json", "dataset_release_policy.json"]
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
    assert len(patch.entries) == 13
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


# --- PT-203 and the distribution boundary --------------------------------------------


def _json(root: Path, *parts: str) -> Any:
    return json.loads(root.joinpath(*parts).read_text(encoding="utf-8"))


def test_pt203_reference_is_unchanged_and_text_no_longer_says_fixed(root: Path) -> None:
    patched = _json(root, "config", "canonical_sensor_contract.json")["sensors"]["PT-203"]
    original = _json(root, "config", "reference", "canonical_sensor_contract.json")["sensors"][
        "PT-203"
    ]
    assert patched["measured_variable_ref"] == original["measured_variable_ref"]
    assert patched["measured_variable_ref"]["field"] == "pressure_pa_abs"
    assert "fixed pressure" in original["adapter"]
    for word in ("fixed pressure", "Dirichlet", "no fault-dependent"):
        assert word not in patched["adapter"]
    assert "varies with flow" in patched["adapter"]


def test_policy_labels_the_value_as_the_reservoir_pressure(root: Path) -> None:
    policy = _json(root, "config", "dataset_release_policy.json")
    assert "fixed_distribution_boundary_gauge_Pa" not in policy
    assert policy["reservoir_gauge_pressure_Pa"] == 200000
    original = _json(root, "config", "reference", "dataset_release_policy.json")
    assert original["fixed_distribution_boundary_gauge_Pa"] == policy["reservoir_gauge_pressure_Pa"]


def test_boundary_law_entry_holds_the_form_and_no_coefficient(root: Path) -> None:
    law = _json(root, "config", "dataset_release_policy.json")["distribution_boundary_law"]
    assert law["form"] == "dH_d = c * (Q / 300)^2"
    assert law["c_source"] == "config/delivery_boundary.json"
    assert not any(isinstance(v, (int, float)) for v in law.values())


def test_no_working_contract_calls_pt203_fixed_or_constant(root: Path) -> None:
    for name in (
        "canonical_sensor_contract.json",
        "dataset_release_policy.json",
        "topology_contract.json",
    ):
        text = (root / "config" / name).read_text(encoding="utf-8").lower()
        assert "dirichlet" not in text
        assert "fixed_distribution" not in text
        assert "fixed pressure" not in text


def test_add_and_remove_markers() -> None:
    from verum.contracts.patches import ABSENT, REMOVE

    patch = parse_patch_file(
        {
            "file": "x.json",
            "entries": [
                {"path": "/a", "old": 1, "new": REMOVE, "reason": "r"},
                {"path": "/b", "old": ABSENT, "new": 2, "reason": "r"},
            ],
        }
    )
    assert apply_patches({"a": 1}, patch) == {"b": 2}
    with pytest.raises(ContractError, match="absent"):
        apply_patches({"a": 1, "b": 1}, patch)
    with pytest.raises(ContractError, match="expected"):
        apply_patches({"a": 5}, patch)
