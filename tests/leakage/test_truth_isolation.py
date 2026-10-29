"""Isolation of the hidden truth store and of the truth placeholder tag.

Inputs: the source tree and temporary modules written by the tests. Outputs: pass/fail.
Key assumptions:
    * Nothing outside the engine package may import the truth store, and the
      observation and api packages may import none of the truth, engine, hydraulics or
      ledger modules. The observation package does not exist yet; the test covers it as
      soon as it appears and today asserts the rule on the api package.
    * The tag ``truth_placeholder`` marks protection signals taken from the true level
      and flow. Any module outside ``verum.sim`` (and the schema files) that mentions
      the tag or imports the module that defines it fails the tripwire test. The scan
      itself is tested on a synthetic offending module.
    * The hidden-dataset schemas require the ``hidden`` marker and refuse unknown fields.

Source: ``CONTRIBUTING.md`` (data exposure); ``revised/05_simulation_validation_dataset.md``
sections 7.2 and 9.4.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from verum.contracts import PROPOSED_SCHEMA_NAMES, load_schema

FORBIDDEN_FOR_VISIBLE = (
    "verum.truth",
    "verum.sim",
    "verum.hydraulics",
    "verum.ledger",
    "verum.protection",
)
TAG = "truth_placeholder"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found |= {f"{node.module}.{a.name}" for a in node.names}
    return found


def _module_name(root: Path, path: Path) -> str:
    return ".".join(path.relative_to(root / "src").with_suffix("").parts).removesuffix(".__init__")


def importers_of(root: Path, prefix: str) -> set[str]:
    """Names of modules under ``root/src`` that import something starting with ``prefix``."""
    return {
        _module_name(root, p)
        for p in (root / "src").rglob("*.py")
        if any(i == prefix or i.startswith(prefix + ".") for i in _imports(p))
    }


def tag_users(root: Path) -> set[str]:
    """Modules under ``root/src`` that mention the placeholder tag or import its definition."""
    users = set()
    for p in (root / "src").rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        if (
            TAG in text
            or "SIGNAL_SOURCE" in text
            or any("verum.sim.rows" in i for i in _imports(p))
        ):
            users.add(_module_name(root, p))
    return users


def test_only_the_engine_imports_the_truth_store(root: Path) -> None:
    importers = importers_of(root, "verum.truth")
    assert importers
    assert all(m.startswith(("verum.sim", "verum.truth")) for m in importers), importers


def test_the_api_and_observation_packages_import_no_hidden_module(root: Path) -> None:
    for package in ("api", "observation"):
        base = root / "src" / "verum" / package
        if not base.exists():
            assert package == "observation"  # not written yet; the rule applies once it exists
            continue
        for path in base.rglob("*.py"):
            bad = [i for i in _imports(path) if i.startswith(FORBIDDEN_FOR_VISIBLE)]
            assert bad == [], (path.as_posix(), bad)


def test_no_module_outside_the_engine_consumes_the_placeholder_tag(root: Path) -> None:
    users = tag_users(root)
    assert users  # the engine does use it
    assert all(m.startswith("verum.sim") for m in users), users


def test_the_tripwire_fails_for_a_later_module_that_reads_the_tag(tmp_path: Path) -> None:
    src = tmp_path / "src" / "verum" / "observation"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text('"""x."""\n', encoding="utf-8")
    (src / "adapter.py").write_text(f'"""x."""\nSOURCE = "{TAG}"\n', encoding="utf-8")
    sim = tmp_path / "src" / "verum" / "sim"
    sim.mkdir(parents=True)
    (sim / "rows.py").write_text(f'"""x."""\nSIGNAL_SOURCE = "{TAG}"\n', encoding="utf-8")
    users = tag_users(tmp_path)
    assert users == {"verum.sim.rows", "verum.observation.adapter"}
    assert not all(m.startswith("verum.sim") for m in users)


def test_the_tripwire_fails_for_a_module_that_imports_the_tag_definition(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "verum" / "later"
    pkg.mkdir(parents=True)
    (pkg / "m.py").write_text(
        '"""x."""\nfrom verum.sim.rows import SIGNAL_SOURCE\n', encoding="utf-8"
    )
    assert tag_users(tmp_path) == {"verum.later.m"}


def test_the_import_scan_finds_a_truth_import_in_a_synthetic_observation_module(
    tmp_path: Path,
) -> None:
    pkg = tmp_path / "src" / "verum" / "observation"
    pkg.mkdir(parents=True)
    (pkg / "m.py").write_text('"""x."""\nimport verum.truth.sinks\n', encoding="utf-8")
    assert importers_of(tmp_path, "verum.truth") == {"verum.observation.m"}


@pytest.mark.parametrize("name", PROPOSED_SCHEMA_NAMES)
def test_hidden_dataset_schemas_require_the_marker_and_refuse_unknown_fields(name: str) -> None:
    schema = load_schema(name)
    assert schema["additionalProperties"] is False
    assert "hidden" in schema["required"] and schema["properties"]["hidden"] == {"const": True}
    assert schema["properties"]["dataset"] == {"const": name}


def test_the_top_level_package_imports_nothing(root: Path) -> None:
    assert _imports(root / "src" / "verum" / "__init__.py") == set()
