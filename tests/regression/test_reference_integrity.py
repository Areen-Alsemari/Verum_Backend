"""Integrity of the committed reference copies and of the working copies.

The manifest lists the hash of every file of the audited package, and the machine-readable subset
that the tests need is committed with each file matching its entry. The schema directory and every
contract without a patch stay byte-identical to the reference. The checks that need the full
untracked package are kept outside the repository tests.
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
    """Each committed reference file has the SHA-256 listed in the manifest. Independent: yes,
    because the hash is recomputed from the file.
    """
    digest = hashlib.sha256((root / "config" / "reference" / name).read_bytes()).hexdigest()
    assert _manifest(root)[name] == digest


def test_manifest_has_the_expected_entry_count(root: Path) -> None:
    """The manifest has 23 entries. Independent: yes, because the count is the audited value."""
    assert len(_manifest(root)) == 23


def test_reference_directory_holds_only_listed_files(root: Path) -> None:
    """The reference directory holds exactly the listed files. Independent: yes, because the
    directory is compared with the list.
    """
    base = root / "config" / "reference"
    on_disk = {p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()}
    assert on_disk == set(REFERENCE_JSON)


@pytest.mark.parametrize("name", SCHEMA_FILES)
def test_schema_copy_is_unchanged(root: Path, name: str) -> None:
    """Each audited schema in the working directory is byte-identical to its reference copy.
    Independent: yes, because the two files are compared directly.
    """
    file = f"{name}.schema.json"
    copy = (root / "schemas" / file).read_bytes()
    assert copy == (root / "config" / "reference" / "schemas" / file).read_bytes()


PROPOSED_SCHEMAS = [
    "hydraulic_state",
    "solver_diagnostics",
    "mass_ledger",
    "events",
    "episode",
    "simulation_rejected",
    "boundary_state",
    "validity_windows",
    "fault_spec",
    "inspection_truth",
]


def test_schema_directory_holds_the_six_audited_and_ten_proposed_schemas(root: Path) -> None:
    """The schema directory holds the six audited and the ten proposed schemas and no others.
    Independent: yes, because the expected names are written out in the test.
    """
    names = sorted(p.name for p in (root / "schemas").glob("*.json"))
    assert names == sorted(f"{n}.schema.json" for n in [*SCHEMA_FILES, *PROPOSED_SCHEMAS])


@pytest.mark.parametrize("name", PROPOSED_SCHEMAS)
def test_proposed_schemas_are_marked_and_versioned(root: Path, name: str) -> None:
    """Each proposed schema carries the backend-proposed marker and a versioned identifier.
    Independent: yes, because the check reads the schema documents directly.
    """
    import json

    schema = json.loads((root / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
    assert schema["x-status"] == "backend-proposed"
    assert schema["$id"] == f"urn:verum:{name}:0.7.0"
    assert schema["properties"]["hidden"] == {"const": True}
    assert "hidden" in schema["required"]


@pytest.mark.parametrize("name", SCHEMA_FILES)
def test_audited_schemas_carry_no_proposal_marker(root: Path, name: str) -> None:
    """No audited schema carries the proposal marker. Independent: yes, because the check scans the
    schema text.
    """
    text = (root / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8")
    assert "backend-proposed" not in text


@pytest.mark.parametrize("name", UNPATCHED_CONTRACTS)
def test_unpatched_contract_copy_is_unchanged(root: Path, name: str) -> None:
    """Each contract that has no patch is byte-identical to its reference copy. Independent: yes,
    because the two files are compared directly.
    """
    assert (root / "config" / name).read_bytes() == (
        root / "config" / "reference" / name
    ).read_bytes()
