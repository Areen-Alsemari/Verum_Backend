"""What an episode directory records about the inspection parameters of its checkout."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from verum.inspection import history, models, workflow
from verum.inspection.catalog import load_catalog
from verum.inspection.parameters import parameters_digest, provenance_block

pytestmark = pytest.mark.fast


def config_copy(tmp_path: Path, name: str) -> Path:
    """A copy of the configuration directory that a test may edit.

    The catalog is cached by directory, so each variant gets a directory of its own.
    """
    root = Path(__file__).resolve().parents[2]
    shutil.copytree(root / "config", tmp_path / name)
    return tmp_path / name


def edit_catalog(config: Path, change: str) -> None:
    """Write a catalog file whose schema version is replaced."""
    path = config / "inspection_catalog.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["schema_version"] = change
    path.write_text(json.dumps(document), encoding="utf-8")


def test_the_recorded_catalog_version_is_the_version_of_the_file(tmp_path: Path) -> None:
    """The block names the schema version written in the catalog file and follows a change of it.

    Independent: yes, because the expected versions are the literals that the test writes.
    """
    plain, changed = config_copy(tmp_path, "plain"), config_copy(tmp_path, "changed")
    edit_catalog(changed, "9.8.7")
    assert provenance_block(plain)["inspection_catalog_version"] == "1.0.0"
    assert provenance_block(changed)["inspection_catalog_version"] == "9.8.7"
    assert load_catalog(changed).version == "9.8.7"


def leaves(node: Any, path: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """The path of every value of a JSON document that holds no further structure."""
    if isinstance(node, dict):
        return [p for k, v in node.items() for p in leaves(v, (*path, k))]
    if isinstance(node, list):
        return [p for i, v in enumerate(node) for p in leaves(v, (*path, i))]
    return [path]


def changed_copy(document: Any, path: tuple[Any, ...]) -> Any:
    """A copy of the document in which the value at the path is replaced by a different one."""
    clone = json.loads(json.dumps(document))
    parent = clone
    for step in path[:-1]:
        parent = parent[step]
    value = parent[path[-1]]
    if isinstance(value, bool):
        parent[path[-1]] = not value
    elif isinstance(value, (int, float)):
        parent[path[-1]] = value + 1
    elif isinstance(value, str):
        parent[path[-1]] = value + "x"
    else:
        parent[path[-1]] = 1
    return clone


def test_the_digest_changes_when_any_value_of_the_catalog_changes(tmp_path: Path) -> None:
    """Changing any one value of the catalog file, a cost, a unit, a threshold, a workflow
    constant or a history probability, gives another digest, and a change of formatting does not.

    Independent: yes, because each variant is built here from the file and compared with the
    digest of the original.
    """
    root = Path(__file__).resolve().parents[2]
    document = json.loads((root / "config" / "inspection_catalog.json").read_text("utf-8"))
    base = parameters_digest(root / "config")
    (tmp_path / "inspection_catalog.json").write_text(json.dumps(document, indent=7), "utf-8")
    assert parameters_digest(tmp_path) == base
    paths = leaves(document)
    assert len(paths) > 150
    unchanged = []
    for path in paths:
        text = json.dumps(changed_copy(document, path))
        (tmp_path / "inspection_catalog.json").write_text(text, encoding="utf-8")
        if parameters_digest(tmp_path) == base:
            unchanged.append(path)
    assert unchanged == []


CONSTANTS = [
    (models, "AGREEMENT", 2.0),
    (workflow, "CALIBRATION_VALID_DAYS", (31, 335)),
    (workflow, "CALIBRATION_VALID_DAYS", (30, 336)),
    (history, "PRIOR_INSPECTIONS", (0, 5)),
    (history, "PRIOR_CALIBRATIONS", (1, 4)),
    (history, "PRIOR_WORK_ORDERS", (0, 4)),
]


@pytest.mark.parametrize(("module", "name", "other"), CONSTANTS)
def test_the_digest_changes_when_a_named_constant_of_the_code_changes(
    monkeypatch: pytest.MonkeyPatch, module: Any, name: str, other: Any
) -> None:
    """The agreement band, the calibration validity and the three history counts are in the digest.

    Independent: yes, because the constant is replaced by a literal and the digests are compared.
    """
    base = parameters_digest()
    monkeypatch.setattr(module, name, other)
    assert parameters_digest() != base


def test_the_provenance_block_holds_the_version_and_the_digest() -> None:
    """The block has exactly the two fields and the digest is the one of the checkout.

    Independent: yes, because the field names are written out in the test.
    """
    block = provenance_block()
    assert set(block) == {"inspection_catalog_version", "inspection_parameters_sha256"}
    assert block["inspection_parameters_sha256"] == parameters_digest()
    assert len(block["inspection_parameters_sha256"]) == 64
