"""Shared fixtures: raw and parsed contracts loaded from the configuration.

Tests receive deep copies of the raw contracts so that a mutation in one test cannot leak into
another.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from _series import Series, load_series
from verum.contracts import (
    ReleasePolicy,
    SensorContract,
    Topology,
    load_policy,
    load_sensor_contract,
    load_topology,
)
from verum.contracts.paths import config_dir, repo_root
from verum.hydraulics import HydraulicModel
from verum.sim.episode import EpisodeResult, run_episode

Raw = dict[str, Any]


def _read(name: str) -> Raw:
    loaded: Raw = json.loads((config_dir() / name).read_text(encoding="utf-8"))
    return loaded


@pytest.fixture
def root() -> Path:
    return repo_root()


@pytest.fixture
def raw_topology() -> Raw:
    return copy.deepcopy(_read("topology_contract.json"))


@pytest.fixture
def raw_sensors() -> Raw:
    return copy.deepcopy(_read("canonical_sensor_contract.json"))


@pytest.fixture
def raw_policy() -> Raw:
    return copy.deepcopy(_read("dataset_release_policy.json"))


@pytest.fixture
def raw_fluid() -> Raw:
    return copy.deepcopy(_read("fluid_contract.json"))


@pytest.fixture(scope="session")
def topology() -> Topology:
    return load_topology()


@pytest.fixture(scope="session")
def sensors(topology: Topology) -> SensorContract:
    return load_sensor_contract(topology)


@pytest.fixture(scope="session")
def policy() -> ReleasePolicy:
    return load_policy()


@pytest.fixture(scope="session")
def model() -> HydraulicModel:
    return HydraulicModel.load()


COMPLETED = ["S0-A", "S0-B", "S0-C", "S0u-D", "S0u-E", "S0-F", "S0-G", "S0-A-inland"]
SCENARIOS = [*COMPLETED, "REJ-1", "REJ-2", "REJ-3"]


@pytest.fixture(scope="session")
def episodes(
    model: HydraulicModel, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, EpisodeResult]:
    """Every scenario run once into a temporary directory (shared by the engine tests)."""
    out = tmp_path_factory.mktemp("episodes")
    return {sid: run_episode(sid, out, model) for sid in SCENARIOS}


@pytest.fixture(scope="session")
def series(episodes: dict[str, EpisodeResult]) -> dict[str, Series]:
    """Compact, schema-validated series of the completed scenarios."""
    return {sid: load_series(episodes[sid].directory) for sid in COMPLETED}


SLOW_FIXTURES = {"episodes", "series", "halving"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Group the suite into slow tests, which use the shared episode runs or run the engine for more
    than a few seconds, and fast tests. Both groups run in the full run and nothing is deselected.
    """
    for item in items:
        fixtures = set(getattr(item, "fixturenames", ()))
        slow = item.get_closest_marker("slow") is not None or bool(fixtures & SLOW_FIXTURES)
        item.add_marker(pytest.mark.slow if slow else pytest.mark.fast)
