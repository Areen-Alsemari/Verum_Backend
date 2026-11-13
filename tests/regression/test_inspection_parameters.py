"""What an episode directory records about the inspection parameters of its checkout."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from verum.inspection.catalog import load_catalog
from verum.inspection.parameters import provenance_block

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
    assert provenance_block(plain) == {"inspection_catalog_version": "1.0.0"}
    assert provenance_block(changed) == {"inspection_catalog_version": "9.8.7"}
    assert load_catalog(changed).version == "9.8.7"
