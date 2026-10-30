"""Repository conventions that can be checked mechanically.

Every Python file under the source and test trees starts with a module docstring. The length and
content rules for docstrings are checked in the documentation style test.
"""

from __future__ import annotations

import ast
from pathlib import Path


def _python_files(root: Path) -> list[Path]:
    return sorted(p for top in ("src", "tests") for p in (root / top).rglob("*.py"))


def test_files_were_found(root: Path) -> None:
    """The source and test trees contain at least 20 Python files. Independent: yes, because the
    count is a lower bound written in the test.
    """
    assert len(_python_files(root)) >= 20


def test_every_module_has_a_docstring(root: Path) -> None:
    """Every Python file under the source and test trees has a module docstring. Independent: yes,
    because the check parses the files.
    """
    missing: list[str] = []
    for path in _python_files(root):
        if not ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))):
            missing.append(path.relative_to(root).as_posix())
    assert missing == []
