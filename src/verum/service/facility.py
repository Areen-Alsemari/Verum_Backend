"""The facility description a frontend needs to draw the terminal, from the repository config.

Inputs: the topology contract, the canonical sensor contract and the sensor specifications.
Outputs: one dictionary of nodes, edges, tanks, pumps, valves, assets and tags.
Assumptions: nothing is added to what the config declares; a tag is placed on the element its
measured-variable reference names, and no drawing coordinates are invented. Tags the contract
withholds are listed as withheld and carry no reading.
Source: the topology contract and the canonical sensor contract.
"""

from __future__ import annotations

import json
from typing import Any

from verum.contracts.paths import config_dir
from verum.inspection.assets import load_assets


def _read(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((config_dir() / name).read_text(encoding="utf-8"))
    return loaded


def _edges(topology: dict[str, Any]) -> list[dict[str, Any]]:
    keys = ("edge_id", "from_node", "to_node", "route_id", "length_m", "nominal_size",
            "inner_diameter_m", "z_from_m", "z_to_m")  # fmt: skip
    return [{key: edge[key] for key in keys} for edge in topology["edges"]]


def _value(spec: dict[str, Any] | None, key: str) -> Any:
    """A spec field, unwrapping the {value, unit, status} form; None when the spec lacks it."""
    found = None if spec is None else spec.get(key)
    return found["value"] if isinstance(found, dict) and "value" in found else found


def _tags(sensors: dict[str, Any], specs: dict[str, Any]) -> list[dict[str, Any]]:
    tags = []
    for tag_id, entry in sensors["sensors"].items():
        spec = specs["tags"].get(tag_id)
        reference = entry.get("measured_variable_ref") or {}
        tags.append({
            "tag_id": tag_id, "status": entry["status"],
            "element_id": reference.get("element_id"), "quantity": reference.get("field"),
            "unit": _value(spec, "unit"), "kind": _value(spec, "kind"),
            "range_lo": _value(spec, "range_lo"), "range_hi": _value(spec, "range_hi"),
            "sample_interval_s": _value(spec, "interval_s"),
        })
    return tags


def facility() -> dict[str, Any]:
    """Assets, tags and topology of the supported terminal, as declared in the config."""
    topology = _read("topology_contract.json")
    edges = _edges(topology)
    nodes = sorted({e[end] for e in edges for end in ("from_node", "to_node")})
    return {
        "source": "repository config: topology contract and canonical sensor contract",
        "nodes": nodes, "edges": edges, "routes": topology["route_lengths_m"],
        "tanks": topology["tanks"], "pumps": topology["pumps"],
        "valves": [n for n in nodes if n.startswith("XV-")],
        "assets": load_assets().listing(),
        "tags": _tags(_read("canonical_sensor_contract.json"), _read("sensor_specs.json")),
        "excluded_nonbaseline_assets": topology["excluded_nonbaseline_assets"],
    }
