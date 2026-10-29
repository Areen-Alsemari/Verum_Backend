"""Apply recorded corrections to a reference contract.

Inputs: a decoded reference contract and a patch file of the form
``{"file": <name>, "entries": [{"path", "old", "new", "reason"}, ...]}``.
Outputs: a corrected copy of the contract; the reference is never modified.
Key assumptions:
    * ``path`` is a JSON Pointer (RFC 6901) to an existing key or list index.
    * Every entry states the value it expects to replace. A mismatch is an
      error, so a patch cannot be applied to the wrong version of a contract.
    * Every entry carries a non-empty reason; a correction without a stated
      reason is rejected.
    * Adding and removing a key use two markers instead of extra fields: an
      ``old`` of ``{"$absent": true}`` requires the key to be missing (the entry
      adds it), and a ``new`` of ``{"$remove": true}`` deletes the key.

Source: ``CONTRIBUTING.md`` (inputs and configuration);
``VERUM_INTEGRATION_README.md`` section D (binding clarification of the
machine-readable contracts).
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir

_ENTRY_KEYS = frozenset({"path", "old", "new", "reason"})
ABSENT = {"$absent": True}
REMOVE = {"$remove": True}


@dataclass(frozen=True)
class PatchEntry:
    """One corrected field."""

    path: str
    old: Any
    new: Any
    reason: str


@dataclass(frozen=True)
class PatchFile:
    """The corrections for one contract file."""

    file: str
    entries: tuple[PatchEntry, ...]


def parse_patch_file(raw: dict[str, Any]) -> PatchFile:
    """Validate a decoded patch file."""
    if not isinstance(raw.get("file"), str) or not isinstance(raw.get("entries"), list):
        raise ContractError("patch file needs a 'file' name and an 'entries' list")
    entries: list[PatchEntry] = []
    for item in raw["entries"]:
        if set(item) != _ENTRY_KEYS:
            raise ContractError(f"patch entry must have exactly {sorted(_ENTRY_KEYS)}: {item}")
        if not isinstance(item["reason"], str) or not item["reason"].strip():
            raise ContractError(f"patch entry {item['path']} has no reason")
        entries.append(PatchEntry(**item))
    return PatchFile(file=raw["file"], entries=tuple(entries))


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _parent_and_key(document: Any, pointer: str, adding: bool) -> tuple[Any, str | int]:
    if not pointer.startswith("/"):
        raise ContractError(f"patch path {pointer!r} is not a JSON Pointer")
    tokens = [_unescape(t) for t in pointer[1:].split("/")]
    node = document
    for token in tokens[:-1]:
        node = node[_key(node, token, pointer)]
    last = tokens[-1]
    if adding:
        if not isinstance(node, dict) or last in node:
            raise ContractError(f"patch path {pointer!r}: the key must be absent in an object")
        return node, last
    return node, _key(node, last, pointer)


def _key(node: Any, token: str, pointer: str) -> str | int:
    if isinstance(node, list):
        if not token.isdigit() or int(token) >= len(node):
            raise ContractError(f"patch path {pointer!r}: bad list index {token!r}")
        return int(token)
    if not isinstance(node, dict) or token not in node:
        raise ContractError(f"patch path {pointer!r}: no key {token!r}")
    return token


def apply_patches(document: dict[str, Any], patch: PatchFile) -> dict[str, Any]:
    """Return a corrected deep copy of ``document``."""
    result = copy.deepcopy(document)
    for entry in patch.entries:
        adding = entry.old == ABSENT
        parent, key = _parent_and_key(result, entry.path, adding)
        if not adding and parent[key] != entry.old:
            raise ContractError(
                f"patch {entry.path}: expected {entry.old!r}, found {parent[key]!r}"
            )
        if entry.new == REMOVE:
            if adding:
                raise ContractError(f"patch {entry.path}: cannot add and remove in one entry")
            del parent[key]
        else:
            parent[key] = copy.deepcopy(entry.new)
    return result


def render_like(reference: bytes, document: dict[str, Any]) -> bytes:
    """Serialise ``document`` with the layout of ``reference`` (indent 2, same final newline)."""
    text = json.dumps(document, indent=2)
    return (text + ("\n" if reference.endswith(b"\n") else "")).encode("utf-8")


def load_patch_file(name: str, directory: Path | None = None) -> PatchFile:
    """Load ``config/patches/<name>`` (for example ``canonical_sensor_contract.json``)."""
    path = (directory or config_dir()) / "patches" / name
    try:
        return parse_patch_file(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
