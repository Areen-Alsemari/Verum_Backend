"""Integrity of the committed reference copies and of the working copies.

Inputs: ``vendor/MANIFEST.sha256``, ``config/reference/``, ``schemas/`` and the
unpatched files in ``config/``. Outputs: pass/fail.
Key assumptions:
    * The manifest lists the hash of every file of the audited package. The
      package itself is not committed; ``config/reference/`` holds the
      machine-readable subset that tests need, and each file must still match
      its manifest entry.
    * ``schemas/`` is a working copy and stays byte-identical to the reference.
    * Contract files that have no patch stay byte-identical to the reference;
      patched contracts are covered by ``test_contract_patches.py``.
    * The checks that need the full untracked package live in
      ``local/checks/test_vendor_integrity.py``.

Source: ``VERUM_INTEGRATION_README.md`` section G.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

SCHEMA_FILES = [
    "fault_truth",
    "inspection_request",
    "inspection_result",
    "observation",
    "observation_audit",
    "paramvalue",
]
UNPATCHED_CONTRACTS = [
    "topology_contract.json",
    "fluid_contract.json",
]
REFERENCE_JSON = [
    "topology_contract.json",
    "fluid_contract.json",
    "canonical_sensor_contract.json",
    "dataset_release_policy.json",
    "preflight_results.json",
    "pilot_agent_observations_ANALYTIC_ONLY.json",
    "pilot_hidden_truth_ANALYTIC_ONLY.json",
    *[f"schemas/{n}.schema.json" for n in SCHEMA_FILES],
]


def _manifest(root: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in (root / "vendor" / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        entries[name] = digest
    return entries


@pytest.mark.parametrize("name", REFERENCE_JSON)
def test_reference_file_matches_manifest(root: Path, name: str) -> None:
    digest = hashlib.sha256((root / "config" / "reference" / name).read_bytes()).hexdigest()
    assert _manifest(root)[name] == digest


def test_manifest_has_the_expected_entry_count(root: Path) -> None:
    assert len(_manifest(root)) == 23


def test_reference_directory_holds_only_listed_files(root: Path) -> None:
    base = root / "config" / "reference"
    on_disk = {p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()}
    assert on_disk == set(REFERENCE_JSON)


@pytest.mark.parametrize("name", SCHEMA_FILES)
def test_schema_copy_is_unchanged(root: Path, name: str) -> None:
    file = f"{name}.schema.json"
    copy = (root / "schemas" / file).read_bytes()
    assert copy == (root / "config" / "reference" / "schemas" / file).read_bytes()


def test_schema_directory_holds_exactly_six_schemas(root: Path) -> None:
    assert len(list((root / "schemas").glob("*.json"))) == 6


@pytest.mark.parametrize("name", UNPATCHED_CONTRACTS)
def test_unpatched_contract_copy_is_unchanged(root: Path, name: str) -> None:
    assert (root / "config" / name).read_bytes() == (
        root / "config" / "reference" / name
    ).read_bytes()
