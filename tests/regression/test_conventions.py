"""Repository conventions that can be checked mechanically.

Inputs: the Python files under ``src/`` and ``tests/``.

Outputs: pass/fail.
Key assumptions: every module starts with a docstring that states its purpose
and names the source document it implements; the docstring is the first
statement, so it is found by parsing and not by text search.

Source: ``CONTRIBUTING.md`` (code conventions).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _python_files(root: Path) -> list[Path]:
    return sorted(p for top in ("src", "tests") for p in (root / top).rglob("*.py"))


def test_files_were_found(root: Path) -> None:
    assert len(_python_files(root)) >= 20


def test_every_module_has_a_docstring_naming_its_source(root: Path) -> None:
    missing: list[str] = []
    for path in _python_files(root):
        docstring = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
        if not docstring or "Source" not in docstring:
            missing.append(path.relative_to(root).as_posix())
    assert missing == []


@pytest.mark.parametrize("top", ["src", "tests"])
def test_modules_other_than_init_state_inputs_and_outputs(root: Path, top: str) -> None:
    lacking: list[str] = []
    for path in (root / top).rglob("*.py"):
        if path.name == "__init__.py" or path.name == "conftest.py":
            continue
        docstring = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
        if "Inputs" not in docstring or "Outputs" not in docstring:
            lacking.append(path.relative_to(root).as_posix())
    assert lacking == []
