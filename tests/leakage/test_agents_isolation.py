"""Isolation of the agents package from the training and truth packages.

Agents are built from the message contract and the shared helpers only. Neither the training
package, which loads the truth store when imported, nor the truth package may be reached from any
agent module, directly or through another module. The checks combine a static scan of the imports
with an import of every agent module in a fresh interpreter.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

HIDDEN = ("verum.training", "verum.truth")
ALLOWED_FOR_ROLES = ("verum.contracts", "verum.agents.common")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found |= {f"{node.module}.{a.name}" for a in node.names}
    return found


def _hidden(names: set[str]) -> list[str]:
    return sorted(
        n for n in names if any(n == h or n.startswith(h + ".") for h in HIDDEN)
    )


def _agent_files(root: Path) -> list[Path]:
    return sorted((root / "src" / "verum" / "agents").rglob("*.py"))


def _other_verum(names: set[str], own: str) -> list[str]:
    allowed = (*ALLOWED_FOR_ROLES, own)
    return sorted(
        n for n in names
        if (n == "verum" or n.startswith("verum."))
        and not any(n == a or n.startswith(a + ".") for a in allowed)
        and n != "verum.agents"
    )


def test_no_agent_module_imports_training_or_truth(root: Path) -> None:
    """No module under the agents package names the training or truth packages in an import.

    Independent: yes, because the check scans the imports of the source tree.
    """
    files = _agent_files(root)
    assert len(files) >= 20
    assert {p: _hidden(_imports(p)) for p in files if _hidden(_imports(p))} == {}


def test_role_packages_import_only_contracts_and_shared_helpers(root: Path) -> None:
    """A role package imports from the contract package, the shared helpers and itself only.

    Independent: yes, because the check scans the imports of the source tree.
    """
    base = root / "src" / "verum" / "agents"
    skipped = {"common", "runner", "__pycache__"}
    roles = [p for p in sorted(base.iterdir()) if p.is_dir() and p.name not in skipped]
    assert len(roles) == 8
    for package in roles:
        own = f"verum.agents.{package.name}"
        for path in package.rglob("*.py"):
            assert _other_verum(_imports(path), own) == [], path.as_posix()


def test_the_runner_imports_only_contracts_and_shared_helpers(root: Path) -> None:
    """The runner finds role modules by name at run time and imports no role package itself.

    Independent: yes, because the check scans the imports of the source tree.
    """
    base = root / "src" / "verum" / "agents" / "runner"
    files = sorted(base.glob("*.py"))
    assert len(files) >= 5
    for path in files:
        assert _other_verum(_imports(path), "verum.agents.runner") == [], path.as_posix()


def _loaded_after_importing(statement: str) -> list[str]:
    code = textwrap.dedent(
        f"""
        import sys
        {statement}
        print("\\n".join(sorted(m for m in sys.modules if m.startswith("verum."))))
        """
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True
    )
    return done.stdout.split()


def test_importing_every_agent_module_loads_no_training_or_truth_module(root: Path) -> None:
    """Importing all agent modules in a fresh interpreter loads neither hidden package.

    Independent: yes, because the loaded modules are read from the interpreter, not from the code.
    """
    base = root / "src"
    modules = [
        ".".join(p.relative_to(base).with_suffix("").parts).removesuffix(".__init__")
        for p in _agent_files(root)
    ]
    loaded = _loaded_after_importing("; ".join(f"import {m}" for m in modules))
    assert any(m.startswith("verum.agents.common") for m in loaded)
    assert _hidden(set(loaded)) == []


def test_the_import_probe_detects_the_training_package() -> None:
    """The probe flags a package known to load the truth store, so a clean result means something.

    Independent: yes, because the offending import is written by the test.
    """
    loaded = _loaded_after_importing("import verum.training.dataset")
    assert "verum.truth" in loaded and "verum.training" in loaded


def test_the_scanner_flags_a_synthetic_offending_module(tmp_path: Path) -> None:
    """The static scan reports a module that imports the training package.

    Independent: yes, because the offending module is written by the test.
    """
    bad = tmp_path / "m.py"
    bad.write_text('"""x."""\nfrom verum.training.dataset import iter_role_examples\n')
    assert _hidden(_imports(bad)) == [
        "verum.training.dataset", "verum.training.dataset.iter_role_examples"
    ]
