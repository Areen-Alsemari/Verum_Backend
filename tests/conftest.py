"""Shared fixtures: raw and parsed contracts loaded from ``config/``.

Inputs: the four contract files in ``config/``. Outputs: pytest fixtures.
Key assumption: tests receive deep copies of the raw contracts so that a
mutation in one test cannot leak into another.

Source: ``VERUM_INTEGRATION_README.md`` section G.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

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
