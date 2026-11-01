"""Read-only gateway: what an agent may see of an episode at a given time.

A query returns the observations that are available at the requested time and nothing later, with
the assets and the inspection catalog, each checked against a closed schema and an allowlist that
rejects hidden keys and strings. With an inspection service attached, the gateway submits requests
and returns requests, results and the history for a given time. The service is a protocol, so the
gateway holds no truth.
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any, Protocol

import jsonschema

from verum.contracts import validate, validator
from verum.inspection.assets import load_assets
from verum.inspection.catalog import load_catalog

ASSET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["asset_id", "kind"],
    "properties": {
        "asset_id": {"type": "string", "minLength": 1},
        "kind": {"enum": ["tank", "pump", "isolation_valve", "pipe", "pressure_transmitter"]},
    },
}
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "unit", "modelled", "uncertainty_k2"],
    "properties": {
        "name": {"type": "string"},
        "unit": {"type": "string"},
        "modelled": {"type": "boolean"},
        "uncertainty_k2": {"type": ["number", "null"]},
    },
}
CATALOG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "action_id", "name", "target_kind", "targets", "preconditions", "cost_usd", "duration_min",
        "outputs",
    ],
    "properties": {
        "action_id": {"type": "string", "pattern": "^ACT-INSP-0[1-7]$"},
        "name": {"type": "string"},
        "target_kind": {"type": "string"},
        "targets": {"type": "string"},
        "preconditions": {"type": "array", "items": {"type": "string"}},
        "cost_usd": {"type": "number", "minimum": 0},
        "duration_min": {"type": "number", "exclusiveMinimum": 0},
        "outputs": {"type": "array", "items": OUTPUT_SCHEMA},
    },
}  # fmt: skip
PAYLOAD_KEYS = frozenset(
    {
        "episode_id", "as_of_s", "observations", "assets", "inspection_catalog",
        "inspection_requests", "inspection_results", "history",
    }
)  # fmt: skip
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
    return load_assets().listing()


class InspectionBackend(Protocol):
    """What the gateway needs of an inspection service; it returns only agent-visible rows."""

    def submit(self, request: dict[str, Any], as_of_s: float) -> dict[str, Any]: ...

    def requests(self, as_of_s: float) -> list[dict[str, Any]]: ...

    def results(self, as_of_s: float) -> list[dict[str, Any]]: ...

    def history(self, as_of_s: float) -> list[dict[str, Any]]: ...


class Gateway:
    def __init__(
        self, episode_directory: Path, inspection: InspectionBackend | None = None
    ) -> None:
        self.episode_id = episode_directory.name
        self._inspection = inspection
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
            "inspection_catalog": self._catalog(),
        }
        check_allowlist(payload)
        return payload

    # --- inspection ----------
    @staticmethod
    def _catalog() -> list[dict[str, Any]]:
        items = load_catalog().agent_view()
        for item in items:
            jsonschema.validate(item, CATALOG_SCHEMA)
        return items

    def _service(self) -> InspectionBackend:
        if self._inspection is None:
            raise GatewayViolation("no inspection service is attached to this gateway")
        return self._inspection

    def _rows(
        self, key: str, schema: str, rows: list[dict[str, Any]], as_of_s: float
    ) -> dict[str, Any]:
        for row in rows:
            validate(schema, row)
        payload: dict[str, Any] = {"episode_id": self.episode_id, "as_of_s": as_of_s, key: rows}
        check_allowlist(payload)
        return payload

    def catalog(self) -> dict[str, Any]:
        """The inspection catalog."""
        payload = {"episode_id": self.episode_id, "inspection_catalog": self._catalog()}
        check_allowlist(payload)
        return payload

    def submit_request(self, request: dict[str, Any], as_of_s: float) -> dict[str, Any]:
        """Submit a pending request; it is refused with ``RequestError`` if it breaks a rule."""
        view = self._service().submit(request, as_of_s)
        return self._rows("inspection_requests", "inspection_request", [view], as_of_s)

    def requests(self, as_of_s: float) -> dict[str, Any]:
        """The requests with the approval state they have at ``as_of_s``."""
        rows = self._service().requests(as_of_s)
        return self._rows("inspection_requests", "inspection_request", rows, as_of_s)

    def results(self, as_of_s: float) -> dict[str, Any]:
        """The results as visible at ``as_of_s``: findings only once a result is available."""
        rows = self._service().results(as_of_s)
        return self._rows("inspection_results", "inspection_result", rows, as_of_s)

    def history(self, as_of_s: float) -> dict[str, Any]:
        """The history records recorded up to ``as_of_s``."""
        rows = self._service().history(as_of_s)
        return self._rows("history", "inspection_history", rows, as_of_s)


def query(episode_directory: Path, as_of_s: float) -> dict[str, Any]:
    """Convenience form: ``query(episode, as_of_T)``."""
    return Gateway(episode_directory).query(as_of_s)
