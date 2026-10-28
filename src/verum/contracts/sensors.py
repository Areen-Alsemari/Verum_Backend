"""Loader and validator for ``canonical_sensor_contract.json``.

Inputs: the sensor contract (36 declared tags) and the validated topology.

Outputs: an immutable ``SensorContract`` whose entries carry a typed
``MeasuredVariableRef`` and an emit/withheld status.
Key assumptions:
    * The contract maps a tag to a hidden-state quantity only. Instrument
      dynamics, noise and quantisation are separate models (a later phase).
    * Every reference is checked against a closed vocabulary of record types
      and fields. The vocabulary is the contract's own typed-state definition;
      unknown record types or fields are rejected rather than passed through.
    * Withheld tags carry a null reference and are never emitted: a declared tag
      is not permission to invent data, and a null reference leaves no field to
      convert from. An emitted tag must carry a reference.
    * Names that older documents used (``valve_state.position_frac``, a bare
      ``pressure`` field, a tank level behind a high-high switch) are absent
      from the vocabulary, so a reintroduced stale mapping fails to load.

Source: ``canonical_sensor_contract.json``;
``revised/05_simulation_validation_dataset.md`` section 7.4.8 and the typed
instrument input states appendix; ``VERUM_INTEGRATION_README.md`` section B.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir
from verum.contracts.topology import Topology

FILENAME: Final = "canonical_sensor_contract.json"
STATUS_EMIT: Final = "emit"
STATUS_WITHHELD: Final = "withheld"

ALLOWED_FIELDS: Final[dict[str, frozenset[str]]] = {
    "edge_state": frozenset({"flow_m3s", "fluid_temperature_K", "p_from_pa_abs", "p_to_pa_abs"}),
    "node_state": frozenset({"pressure_pa_abs"}),
    "tank_state": frozenset({"level_m", "temperature_K"}),
    "valve_contact_state": frozenset({"open_contact", "closed_contact"}),
    "protection_state": frozenset({"trip_latched"}),
    "pump_state": frozenset({"run_state"}),
}


@dataclass(frozen=True)
class MeasuredVariableRef:
    """Pointer from a tag to one field of one hidden-state element."""

    record_type: str
    element_id: str
    field: str


@dataclass(frozen=True)
class SensorEntry:
    """One declared tag."""

    tag: str
    status: str
    ref: MeasuredVariableRef | None
    adapter: str | None


@dataclass(frozen=True)
class SensorContract:
    """The validated sensor contract."""

    version: str
    sensors: dict[str, SensorEntry]
    nonbaseline_excluded: tuple[str, ...]

    @property
    def emitted_tags(self) -> tuple[str, ...]:
        return tuple(t for t, s in self.sensors.items() if s.status == STATUS_EMIT)

    @property
    def withheld_tags(self) -> tuple[str, ...]:
        return tuple(t for t, s in self.sensors.items() if s.status == STATUS_WITHHELD)


def _fail(message: str) -> ContractError:
    return ContractError(f"sensor contract: {message}")


def _element_ids(topology: Topology) -> dict[str, frozenset[str]]:
    """Element identifiers that may be referenced, by record type."""
    nodes = topology.nodes
    tanks = frozenset(topology.tank_ids)
    # Junction and boundary nodes are the unhyphenated names; valves, pumps and
    # tank nozzles carry a hyphen or colon and are referenced by other record types.
    return {
        "edge_state": frozenset(topology.edge_ids),
        "node_state": frozenset(n for n in nodes if ":" not in n and "-" not in n),
        "tank_state": tanks,
        "valve_contact_state": frozenset(n for n in nodes if n.startswith("XV-")),
        "protection_state": frozenset(f"LSHH-{t.split('-', 1)[1]}" for t in tanks),
        "pump_state": frozenset(topology.pumps),
    }


# Tag families whose reference is fixed by the audit: a valve tag reports a limit
# contact and a high-high switch reports its own protection state, in both cases
# of the element with the same name as the tag.
_TAG_RECORD_TYPE: Final = {"XV-": "valve_contact_state", "LSHH-": "protection_state"}


def _check_tag_family(tag: str, ref: MeasuredVariableRef) -> None:
    for prefix, record_type in _TAG_RECORD_TYPE.items():
        if tag.startswith(prefix) and (ref.record_type, ref.element_id) != (record_type, tag):
            raise _fail(
                f"{tag} must reference {record_type} {tag}, not {ref.record_type} {ref.element_id}"
            )


def _parse_ref(
    tag: str, raw: dict[str, Any], elements: dict[str, frozenset[str]]
) -> MeasuredVariableRef:
    if set(raw) != {"record_type", "element_id", "field"}:
        raise _fail(f"{tag} reference has unexpected keys {sorted(raw)}")
    ref = MeasuredVariableRef(**raw)
    if ref.record_type not in ALLOWED_FIELDS:
        raise _fail(f"{tag} uses unknown record_type {ref.record_type!r}")
    if ref.element_id not in elements[ref.record_type]:
        raise _fail(f"{tag} refers to {ref.element_id!r}, not a {ref.record_type} element")
    if ref.field not in ALLOWED_FIELDS[ref.record_type]:
        raise _fail(f"{tag} uses field {ref.field!r} not allowed for {ref.record_type}")
    return ref


def _parse_entry(tag: str, raw: dict[str, Any], elements: dict[str, frozenset[str]]) -> SensorEntry:
    status = raw.get("status")
    if status not in (STATUS_EMIT, STATUS_WITHHELD):
        raise _fail(f"{tag} has unknown status {status!r}")
    raw_ref = raw.get("measured_variable_ref", "<absent>")
    if status == STATUS_WITHHELD:
        if raw_ref is not None:
            raise _fail(f"{tag} is withheld and must have a null measured_variable_ref")
        return SensorEntry(tag=tag, status=status, ref=None, adapter=raw.get("adapter"))
    if not isinstance(raw_ref, dict):
        raise _fail(f"{tag} is emitted and needs a measured_variable_ref")
    ref = _parse_ref(tag, raw_ref, elements)
    _check_tag_family(tag, ref)
    return SensorEntry(tag=tag, status=status, ref=ref, adapter=raw.get("adapter"))


def parse_sensor_contract(contract: dict[str, Any], topology: Topology) -> SensorContract:
    """Validate a decoded sensor contract against the topology."""
    elements = _element_ids(topology)
    sensors = {
        tag: _parse_entry(tag, raw, elements) for tag, raw in contract.get("sensors", {}).items()
    }
    return SensorContract(
        version=str(contract.get("version", "")),
        sensors=sensors,
        nonbaseline_excluded=tuple(contract.get("nonbaseline_excluded", [])),
    )


def load_sensor_contract(topology: Topology, directory: Path | None = None) -> SensorContract:
    """Load and validate the sensor contract from ``config/``."""
    path = (directory or config_dir()) / FILENAME
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    return parse_sensor_contract(decoded, topology)
