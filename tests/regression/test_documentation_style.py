"""Mechanical checks of the documentation rules in CONTRIBUTING.md.

Markdown paragraphs must not be hard-wrapped, docstrings must stay short and free of
repository paths, and every test must state whether it is independent of the code it checks.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

MARKDOWN_SENTENCE_END = ".!?:"
MODULE_DOCSTRING_LINES = 10
DEFINITION_DOCSTRING_LINES = 8
PATH_PATTERN = re.compile(r"\b(?:src|tests|config|tools|docs|vendor|local)/")
FILE_PATTERN = re.compile(r"[\w.-]+\.(?:py|json)\b")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
SKIPPED_PARTS = {"venv", "work", "__pycache__"}


def _markdown_files(root: Path) -> list[Path]:
    return [root / "README.md", root / "CONTRIBUTING.md", *sorted((root / "docs").glob("*.md"))]


def _python_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for top in ("src", "tools", "tests", "local/checks"):
        base = root / top
        if base.is_dir():
            found.extend(p for p in base.rglob("*.py") if not SKIPPED_PARTS & set(p.parts))
    return sorted(found)


def _is_plain_text(line: str) -> bool:
    """Whether a line is paragraph text, as opposed to a heading, list, table or quote."""
    if not line.strip() or line[0] in " \t":
        return False
    if line.startswith(("#", "|", ">", "<", "```")) or LIST_ITEM.match(line):
        return False
    return not re.fullmatch(r"[-=*_ ]{3,}", line)


def _ends_a_sentence(line: str) -> bool:
    return line.rstrip().rstrip(")\"'*_]").endswith(tuple(MARKDOWN_SENTENCE_END))


def wrapped_paragraph_lines(text: str) -> list[int]:
    """Return the 1-based numbers of lines that are cut in the middle of a sentence."""
    lines = text.splitlines()
    in_fence = False
    flagged: list[int] = []
    plain: list[bool] = []
    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
            plain.append(False)
        else:
            plain.append(not in_fence and _is_plain_text(line))
    for i in range(len(lines) - 1):
        if plain[i] and plain[i + 1] and not _ends_a_sentence(lines[i]):
            flagged.append(i + 1)
    return flagged


def markdown_wrap_violations(root: Path) -> list[str]:
    found: list[str] = []
    for path in _markdown_files(root):
        text = path.read_text(encoding="utf-8")
        found.extend(f"{path.relative_to(root)}:{n}" for n in wrapped_paragraph_lines(text))
    return found


def _definitions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    ]


def _line_count(docstring: str) -> int:
    return len(docstring.splitlines())


def docstring_violations(root: Path) -> dict[str, list[str]]:
    """Collect the docstring violations of every Python file, keyed by rule."""
    found: dict[str, list[str]] = {
        "module length": [],
        "definition length": [],
        "repository path": [],
        "test independence": [],
    }
    for path in _python_files(root):
        name = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstring = ast.get_docstring(tree)
        if docstring is not None and _line_count(docstring) > MODULE_DOCSTRING_LINES:
            found["module length"].append(name)
        _collect_path_rule(found, name, docstring)
        is_test_file = path.name.startswith("test_")
        for node in _definitions(tree):
            doc = ast.get_docstring(node)
            where = f"{name}:{node.lineno} {node.name}"
            if doc is not None and _line_count(doc) > DEFINITION_DOCSTRING_LINES:
                found["definition length"].append(where)
            _collect_path_rule(found, where, doc)
            is_test = is_test_file and node.name.startswith("test_")
            if is_test and not isinstance(node, ast.ClassDef) and "Independent" not in (doc or ""):
                found["test independence"].append(where)
    return found


def _collect_path_rule(found: dict[str, list[str]], where: str, docstring: str | None) -> None:
    if docstring and (PATH_PATTERN.search(docstring) or FILE_PATTERN.search(docstring)):
        found["repository path"].append(where)


def test_the_wrap_detector_flags_a_cut_sentence() -> None:
    """The detector flags a sentence cut across two lines and ignores lists and code.

    Independent: yes, because the inputs are literal strings with known answers.
    """
    cut = "A sentence that runs\non to a second line.\n"
    assert wrapped_paragraph_lines(cut) == [1]
    exempt = "- a list item that\n  continues here\n\n```\ncode without a stop\nmore code\n```\n"
    assert wrapped_paragraph_lines(exempt) == []
    assert wrapped_paragraph_lines("Intro line:\nnext line.\n") == []


def test_markdown_paragraphs_are_not_hard_wrapped(root: Path) -> None:
    """Each paragraph of the README, CONTRIBUTING and docs is a single line.

    Independent: yes, because the rule is applied to the text of the files alone.
    """
    assert markdown_wrap_violations(root) == []


@pytest.mark.parametrize(
    "rule", ["module length", "definition length", "repository path", "test independence"]
)
def test_docstring_rules(root: Path, rule: str) -> None:
    """Docstrings are short, name no repository paths, and tests state their independence.

    Independent: yes, because the rule is applied to the parsed source alone.
    """
    assert docstring_violations(root)[rule] == []
