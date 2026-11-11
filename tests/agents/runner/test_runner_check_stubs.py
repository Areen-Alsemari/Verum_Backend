"""Check that the placeholder check script and the runner discover agents the same way."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import ModuleType

import pytest

from _runner_cases import placeholders, run
from verum.agents.common import StubAgent
from verum.contracts.paths import repo_root

ROLE = "topology_dependency"
MODULE = f"verum.agents.{ROLE}.agent"


def _script() -> ModuleType:
    path = Path(repo_root()) / "tools" / "agents" / "check_stubs.py"
    spec = importlib.util.spec_from_file_location("check_stubs_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module(*names: str) -> ModuleType:
    module = types.ModuleType(MODULE)
    for name in names:
        cls = type(name, (StubAgent,), {"__init__": lambda self: StubAgent.__init__(self, ROLE)})
        cls.__module__ = MODULE
        setattr(module, name, cls)
    return module


def test_the_script_no_longer_reads_the_package_export_list() -> None:
    """The script source calls the runner's discovery function and never reads the export list.

    Independent: yes, because the check reads the text of the script.
    """
    text = (Path(repo_root()) / "tools" / "agents" / "check_stubs.py").read_text(encoding="utf-8")
    assert "load_agent" in text and "__all__" not in text


def test_a_renamed_agent_class_passes_both_or_fails_both(monkeypatch: pytest.MonkeyPatch) -> None:
    """A renamed class is found by the script and by the runner, and two classes fail both.

    Independent: yes, because the replacement modules are written by the test.
    """
    script = _script()
    assert script.check_roles() == []
    agents = {r: a for r, a in placeholders().items() if r != ROLE}

    monkeypatch.setitem(sys.modules, MODULE, _module("RenamedModelAgent"))
    assert script.check_roles() == []
    bundle = run(agents=agents)
    assert bundle.reports[ROLE] is not None and bundle.issues == []

    monkeypatch.setitem(sys.modules, MODULE, _module("OneAgent", "TwoAgent"))
    failures = script.check_roles()
    assert [f.split(":")[0] for f in failures] == [ROLE]
    bundle = run(agents=agents)
    assert bundle.reports[ROLE] is None and bundle.issues[0]["role"] == ROLE
