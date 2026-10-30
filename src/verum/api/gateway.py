"""Read-only gateway: what an agent may see of an episode at a given time.

Only the observation file of an episode is read. A query returns the observations that are available
at the requested time and nothing later, together with the assets and the inspection catalog, each
checked against a closed schema. The payload also passes an allowlist that rejects keys outside the
schemas and strings that name a scenario, a validity window, a tier or a truth dataset.

The inspection catalog is empty because no catalog is available in the audited input; it is a
missing input, not an invented one.
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any

import jsonschema

from verum.contracts import load_topology, validate, validator

ASSET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["asset_id", "kind"],
    "properties": {
        "asset_id": {"type": "string", "minLength": 1},
        "kind": {"enum": ["tank", "pump", "isolation_valve"]},
    },
}
PAYLOAD_KEYS = frozenset({"episode_id", "as_of_s", "observations", "assets", "inspection_catalog"})
FORBIDDEN_TEXT = re.compile(
    r"(?i)(S0u?-[A-Z0-9]|REJ-\d|\bVW-\d|analytic_verification|restricted_benchmark"
    r"|production_candidate|ground_truth|hydraulic_state|fault_truth|solver_diagnostics"
    r"|mass_ledger|observation_audit|simulation_rejected|validity_window|boundary_state)"
)
OBSERVATION_FILE = "observations.jsonl.gz"


class GatewayViolation(Exception):
    """A payload carried something an agent may not see."""


def check_allowlist(payload: dict[str, Any]) -> None:
    """Raise unless every key is allowed and no string names hidden material."""
    extra = set(payload) - PAYLOAD_KEYS
    if extra:
        raise GatewayViolation(f"keys outside the interface: {sorted(extra)}")

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if FORBIDDEN_TEXT.search(str(key)):
                    raise GatewayViolation(f"hidden key {key!r} at {path}")
                walk(value, f"{path}.{key}")
        elif isinstance(node, (list, tuple)):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
        elif isinstance(node, str) and FORBIDDEN_TEXT.search(node):
            raise GatewayViolation(f"hidden text {node!r} at {path}")

    walk(payload, "payload")


def _assets() -> list[dict[str, str]]:
    topology = load_topology()
    valves = sorted(n for n in topology.nodes if n.startswith("XV-"))
    items = [{"asset_id": t, "kind": "tank"} for t in topology.tank_ids]
    items += [{"asset_id": p, "kind": "pump"} for p in topology.pumps]
    items += [{"asset_id": v, "kind": "isolation_valve"} for v in valves]
    return items


class Gateway:
    def __init__(self, episode_directory: Path) -> None:
        self.episode_id = episode_directory.name
        with gzip.open(episode_directory / OBSERVATION_FILE, "rt", encoding="utf-8") as handle:
            self._observations = [json.loads(line) for line in handle]
        self._observations.sort(key=lambda r: (r["t_available_s"], r["tag_id"]))
        self._checked = 0  # rows before this index have been validated
        self._valid = validator("observation").is_valid

    def query(self, as_of_s: float) -> dict[str, Any]:
        """Everything visible at ``as_of_s``; later observations are not returned."""
        visible = [r for r in self._observations if r["t_available_s"] <= as_of_s]
        for row in self._observations[self._checked : len(visible)]:
            if not self._valid(row):
                validate("observation", row)  # raises with the violation
        self._checked = max(self._checked, len(visible))
        assets = _assets()
        for asset in assets:
            jsonschema.validate(asset, ASSET_SCHEMA)
        payload: dict[str, Any] = {
            "episode_id": self.episode_id,
            "as_of_s": as_of_s,
            "observations": visible,
            "assets": assets,
            "inspection_catalog": [],
        }
        check_allowlist(payload)
        return payload


def query(episode_directory: Path, as_of_s: float) -> dict[str, Any]:
    """Convenience form: ``query(episode, as_of_T)``."""
    return Gateway(episode_directory).query(as_of_s)
