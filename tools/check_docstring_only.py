"""Check that a change to Python files touched only docstrings.

For every changed Python file the committed version and the working version are parsed, the
docstrings are removed from both, and the two syntax trees must be identical. Comments and
formatting do not appear in the tree, so they may change freely. A mismatch is printed and the
exit status is 1, which blocks the commit.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

_DOCSTRING_HOSTS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _is_docstring(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def strip_docstrings(tree: ast.Module) -> ast.Module:
    """Remove every docstring in place; a body left empty gets a placeholder statement."""
    for node in ast.walk(tree):
        if isinstance(node, _DOCSTRING_HOSTS) and node.body and _is_docstring(node.body[0]):
            node.body = node.body[1:] or [ast.Pass()]
    return tree


def structure(source: str) -> str:
    """Dump the tree of a source text without its docstrings."""
    return ast.dump(strip_docstrings(ast.parse(source)))


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return done.stdout


def changed_files(root: Path, base: str) -> list[str]:
    """Python files that differ from the base revision, including untracked ones."""
    changed = _git(root, "diff", "--name-only", base, "--", "*.py").split()
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "--", "*.py").split()
    return sorted(set(changed) | set(untracked))


def _reference(root: Path, base: str, name: str, snapshot: Path | None) -> str | None:
    if snapshot is not None and (snapshot / name).is_file():
        return (snapshot / name).read_text(encoding="utf-8")
    try:
        return _git(root, "show", f"{base}:{name}")
    except subprocess.CalledProcessError:
        return None


def compare(root: Path, names: list[str], base: str, snapshot: Path | None) -> list[str]:
    """Return one message per file whose code differs; new files are reported, not failed."""
    problems: list[str] = []
    for name in names:
        reference = _reference(root, base, name, snapshot)
        if reference is None:
            print(f"new file, nothing to compare: {name}")
            continue
        current = (root / name).read_text(encoding="utf-8")
        if structure(reference) != structure(current):
            problems.append(f"code differs outside docstrings: {name}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="files to check; default is every changed file")
    parser.add_argument("--base", default="HEAD", help="revision holding the original code")
    parser.add_argument(
        "--snapshot", type=Path, help="directory with original copies of files outside git"
    )
    args = parser.parse_args(argv)
    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    names = args.files or changed_files(root, args.base)
    problems = compare(root, names, args.base, args.snapshot)
    for problem in problems:
        print(problem)
    print(f"checked {len(names)} files, {len(problems)} mismatches")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
