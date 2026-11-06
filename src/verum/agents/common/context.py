"""Builders for the analysis context shared by every message of one snapshot.

A context binds a case, a revision, a cutoff and the reference snapshot. The snapshot identifier is
the byte hash of the published reference file, so it changes whenever that file changes.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any, Final

from verum.agents.common.ids import analysis_id
from verum.agents.common.numbers import normalise

DATA_RELEASE: Final = "verum_reference_v2"
SCOPE_ID: Final = "verum_supported_reference_v2"
EXECUTION_MODES: Final = ("runtime", "contract_fixture")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CHUNK_BYTES = 1 << 20


def file_sha256(path: Path) -> str:
    """Return the SHA-256 of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_context(
    *,
    case_id: str,
    revision: int,
    as_of_s: float,
    execution_mode: str,
    reference_snapshot_sha256: str,
    as_of_utc: str | None = None,
) -> dict[str, Any]:
    """Build a context; the analysis identifier follows from the case and the revision."""
    if execution_mode not in EXECUTION_MODES:
        raise ValueError(f"execution mode must be one of {EXECUTION_MODES}")
    if not _SHA256.fullmatch(reference_snapshot_sha256):
        raise ValueError("the reference snapshot is a lowercase SHA-256 digest")
    cutoff = normalise(float(as_of_s))
    if not math.isfinite(as_of_s) or as_of_s < 0:
        raise ValueError("the cutoff is a finite nonnegative time")
    return {
        "case_id": case_id,
        "analysis_id": analysis_id(case_id, revision),
        "revision": revision,
        "as_of_s": cutoff,
        "as_of_utc": as_of_utc,
        "data_release": DATA_RELEASE,
        "reference_snapshot_sha256": reference_snapshot_sha256,
        "scope_id": SCOPE_ID,
        "execution_mode": execution_mode,
    }


def make_context_from_reference(
    reference_file: Path, **fields: Any
) -> dict[str, Any]:
    """Build a context whose snapshot identifier is the byte hash of the reference file."""
    return make_context(reference_snapshot_sha256=file_sha256(reference_file), **fields)
