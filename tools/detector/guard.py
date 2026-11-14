"""Audit hook that keeps the experiment away from the test split.

Every file opened under the release folder is classified. Train and validation role views and
examples, the raw rows and the label file of train and validation episodes, the public reference
and the manifest that lists hashes are allowed. Anything else raises before the file is opened.
"""

from __future__ import annotations

import re
import sys
from typing import Any

RELEASE = "reference_release_v2/verum_reference_v2/"
MANIFEST_FILES = {"role_views_manifest.json"}
KEPT_SPLITS = ("train", "validation")
ALLOWED_EPISODES: set[str] = set()
SEEN: dict[str, int] = {}
REJECTED: list[str] = []


def classify(path: str, episodes: set[str]) -> str:
    """Return 'outside', 'allowed' or 'rejected' for one path."""
    path = path.replace("\\", "/")
    if RELEASE not in path:
        return "outside"
    rel = path.split(RELEASE, 1)[1]
    parts = rel.split("/")
    if parts[0] == "knowledge" or rel in MANIFEST_FILES:
        return "allowed"
    if parts[0] == "role_views" and len(parts) == 3:
        return "allowed" if re.fullmatch(r"(train|validation)\.jsonl\.gz", parts[2]) else "rejected"
    if parts[0] == "examples" and len(parts) >= 2:
        return "allowed" if parts[1] in KEPT_SPLITS else "rejected"
    if parts[0] == "observations" and len(parts) == 3:
        return "allowed" if parts[1] in episodes else "rejected"
    if parts[:2] == ["evaluator", "source_episodes"] and len(parts) == 4:
        return "allowed" if parts[3] == "labels.json" and parts[2] in episodes else "rejected"
    return "rejected"


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if event != "open" or not args or not isinstance(args[0], (str, bytes)):
        return
    path = (args[0].decode() if isinstance(args[0], bytes) else args[0]).replace("\\", "/")
    verdict = classify(path, ALLOWED_EPISODES)
    if verdict == "allowed":
        kind = path.split(RELEASE, 1)[1].split("/")[0]
        SEEN[kind] = SEEN.get(kind, 0) + 1
    elif verdict == "rejected":
        REJECTED.append(path)
        raise PermissionError(f"the experiment may not open {path}")


def install() -> None:
    """Install the hook for the rest of the process."""
    sys.addaudithook(_hook)


def summary() -> dict[str, Any]:
    """Counts of allowed opens by folder and the list of rejected attempts."""
    return {"allowed_opens_by_folder": dict(sorted(SEEN.items())), "rejected": list(REJECTED)}
