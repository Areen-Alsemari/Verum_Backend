"""Isolation of the hidden truth store and the protection-signal tripwire.

Inputs: the source tree and temporary modules written by the tests. Outputs: pass/fail.
Key assumptions:
    * Nothing outside the engine package may import the truth store, and the
      observation and api packages may import none of the truth, engine, hydraulics or
      ledger modules. The observation package does not exist yet; the test covers it as
      soon as it appears and today asserts the rule on the api package.
    * The tag ``truth_placeholder`` no longer exists (decision D33): the independent level
      that the protection logic receives is the output of the engine's detector function,
      and a static scan fails if any call passes anything else as ``independent_level_m``.
      The scan itself is tested on a synthetic offending module.
    * Within ``verum.sensors`` only the adapter imports the truth store.
    * The hidden-dataset schemas require the ``hidden`` marker and refuse unknown fields.

Source: ``CONTRIBUTING.md`` (data exposure); ``revised/05_simulation_validation_dataset.md``
sections 7.2 and 9.4.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

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


def test_only_the_engine_and_one_adapter_import_the_truth_store(root: Path) -> None:
    importers = importers_of(root, "verum.truth")
    assert importers
    assert all(
        m.startswith(("verum.sim", "verum.truth")) or m == "verum.sensors.adapter"
        for m in importers
    ), importers
    assert "verum.sensors.adapter" in importers


def test_the_chain_and_the_specs_import_no_hidden_module(root: Path) -> None:
    """Only the adapter of verum.sensors may touch the truth; the rest works on arrays."""
    base = root / "src" / "verum" / "sensors"
    for path in base.glob("*.py"):
        if path.name == "adapter.py":
            continue
        bad = [i for i in _imports(path) if i.startswith(FORBIDDEN_FOR_VISIBLE)]
        assert bad == [], (path.name, bad)


def test_the_api_package_imports_no_hidden_module(root: Path) -> None:
    base = root / "src" / "verum" / "api"
    for path in base.rglob("*.py"):
        bad = [i for i in _imports(path) if i.startswith(FORBIDDEN_FOR_VISIBLE)]
        assert bad == [], (path.as_posix(), bad)
        assert "verum.sensors.adapter" not in _imports(path)


def independent_signal_sources(root: Path) -> list[tuple[str, str]]:
    """(module, source of the argument) of every ``independent_level_m=`` keyword in a call."""
    found = []
    for p in (root / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "independent_level_m":
                        found.append((_module_name(root, p), ast.unparse(kw.value)))
    return found


def test_protection_reads_the_detector_and_never_the_true_level(root: Path) -> None:
    """The tripwire of Phase 4 (decision D33): the independent level handed to the protection
    logic must come from the detector function, and the old tag must be gone."""
    sources = independent_signal_sources(root)
    assert sources
    assert all(src.startswith("self._detector_signal(") for _m, src in sources), sources
    for p in (root / "src").rglob("*.py"):
        assert TAG not in p.read_text(encoding="utf-8"), p.as_posix()
    assert TAG not in (root / "schemas" / "hydraulic_state.schema.json").read_text(encoding="utf-8")


def test_the_tripwire_fails_for_a_module_that_feeds_the_true_level_to_protection(
    tmp_path: Path,
) -> None:
    pkg = tmp_path / "src" / "verum" / "later"
    pkg.mkdir(parents=True)
    (pkg / "m.py").write_text(
        '"""x."""\nSignals(t_s=0.0, independent_level_m=level)\n', encoding="utf-8"
    )
    assert independent_signal_sources(tmp_path) == [("verum.later.m", "level")]
    assert not all(
        src.startswith("self._detector_signal(") for _m, src in independent_signal_sources(tmp_path)
    )


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


# --- names of an episode on disk (Phase 3b) ----------

EPISODE_FILES = {
    "hydraulic_state.jsonl.gz", "solver_diagnostics.jsonl.gz", "mass_ledger.jsonl.gz",
    "events.jsonl.gz", "boundary_state.jsonl.gz", "validity_windows.jsonl.gz",
    "fault_truth.jsonl.gz",
    "episode.json", "provenance.json", "MANIFEST.sha256", "simulation_rejected.json",
    "observations.jsonl.gz", "observation_audit.jsonl.gz",
}  # fmt: skip


def test_no_scenario_identifier_appears_in_any_directory_or_file_name(
    episodes: dict[str, Any],
) -> None:
    """Only the opaque episode id names an episode directory; file names come from a fixed set.

    Scenario identifiers (S0-A, S0u-E, REJ-1, ...) describe the injected situation and live
    only inside the hidden episode record.
    """
    import re

    ids = list(episodes)
    for sid, result in episodes.items():
        directory = result.directory
        assert re.fullmatch(r"EP-[0-9A-F]{12}", directory.name), directory.name
        assert directory.name == result.episode_id
        names = [directory.name, *[p.name for p in directory.rglob("*")]]
        for name in names:
            assert not any(other.lower() in name.lower() for other in ids), (sid, name)
            assert not re.search(r"(?i)S0u?-|REJ-", name), (sid, name)
        assert {p.name for p in directory.iterdir()} <= EPISODE_FILES
