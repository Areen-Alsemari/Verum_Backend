"""Audit hook that confines the live mode to the validation split of one release folder.

Inputs: the release folder. Outputs: a process-wide hook that raises on any open under that folder
other than the knowledge folder, the role-view inventory, and the validation role views and
example files. The test and train splits are refused.
Assumptions: the hook cannot be removed once installed, so it is installed only when the service
is started with a release folder, and it is inert for paths outside that folder.
Source: the standing rule that the test split stays unread.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

INVENTORY = "role_views_manifest.json"
VALIDATION_ROLE_FILE = re.compile(r"role_views/[a-z_0-9]+/validation\.jsonl\.gz")
ROOTS: set[str] = set()
REJECTED: list[str] = []
SEEN: dict[str, int] = {}
_installed = False


def classify(relative: str) -> str:
    """Return 'allowed' or 'rejected' for a path relative to the release folder."""
    parts = relative.split("/")
    if parts[0] == "knowledge" or relative == INVENTORY:
        return "allowed"
    if VALIDATION_ROLE_FILE.fullmatch(relative):
        return "allowed"
    if parts[0] == "examples" and len(parts) >= 2 and parts[1] == "validation":
        return "allowed"
    return "rejected"


def _relative(path: str) -> str | None:
    for root in ROOTS:
        if path == root or path.startswith(root + "/"):
            return path[len(root) :].lstrip("/")
    return None


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if event != "open" or not args or not isinstance(args[0], (str, bytes)):
        return
    path = args[0].decode() if isinstance(args[0], bytes) else args[0]
    relative = _relative(path)
    if relative is None or relative == "":
        return
    if classify(relative) == "allowed":
        SEEN[relative.split("/")[0]] = SEEN.get(relative.split("/")[0], 0) + 1
        return
    REJECTED.append(path)
    raise PermissionError(f"the service may not open {path}")


def confine(release: Path) -> None:
    """Confine opens under the release folder; the hook is installed once per process."""
    global _installed
    ROOTS.add(str(release.resolve()))
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True


def summary() -> dict[str, Any]:
    """Counts of allowed opens by folder and the list of rejected attempts."""
    return {"allowed_opens_by_folder": dict(sorted(SEEN.items())), "rejected": list(REJECTED)}
