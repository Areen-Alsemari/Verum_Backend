"""Checks that the split guards and the test-split report judge backslash paths like slash paths."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from verum.service import guard as service_guard

ROOT = Path(__file__).resolve().parents[2]
RELEASE = "C:\\data\\reference_release_v2\\verum_reference_v2"
TEST_FILE = f"{RELEASE}\\role_views\\diagnostic_reasoning\\test.jsonl.gz"
VALIDATION_FILE = f"{RELEASE}\\role_views\\diagnostic_reasoning\\validation.jsonl.gz"


def _load(name: str, relative: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_service_guard_reads_a_backslash_path_below_the_release() -> None:
    """A Windows path below the release folder is judged by its path relative to that folder.

    Independent: yes, because the expected relative paths are written out by hand.
    """
    roots = {RELEASE}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(service_guard, "ROOTS", roots)
        relative = service_guard._relative(TEST_FILE)
        allowed = service_guard._relative(VALIDATION_FILE)
    assert relative == "role_views/diagnostic_reasoning/test.jsonl.gz"
    assert service_guard.classify(relative) == "rejected"
    assert allowed is not None and service_guard.classify(allowed) == "allowed"


def test_the_detector_guard_rejects_a_backslash_test_file_and_allows_validation() -> None:
    """The experiment hook raises on a test-split file and not on a validation file, either way.

    Independent: yes, because the verdicts follow from the written rule for each path.
    """
    guard = _load("detector_guard_under_test", "tools/detector/guard.py")
    assert guard.classify(TEST_FILE, set()) == "rejected"
    assert guard.classify(TEST_FILE.replace("\\", "/"), set()) == "rejected"
    assert guard.classify(VALIDATION_FILE, set()) == "allowed"
    with pytest.raises(PermissionError):
        guard._hook("open", (TEST_FILE,))
    guard._hook("open", (VALIDATION_FILE,))
    assert guard.summary()["allowed_opens_by_folder"] == {"role_views": 1}


def test_the_test_split_report_flags_a_backslash_path() -> None:
    """The sample runner's list of touched test-split files includes a Windows path.

    Independent: yes, because the two paths are literals and only one belongs to the test split.
    """
    sample = _load("sample_runner_under_test", "tools/agents/run_runner_sample.py")
    sample.ACCESSED.update({TEST_FILE, VALIDATION_FILE})
    assert sample.touched_test_split() == [TEST_FILE]
