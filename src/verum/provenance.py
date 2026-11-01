"""Configuration hash and episode provenance record.

The configuration hash is the SHA-256 of the canonical JSON of every resolved configuration file, so
it covers values and not formatting. Reference copies and patch files are left out because the
patched working files already contain their effect, and so is the inspection catalog, which fixes
no simulated or observed value. The git commit sits in a separate block so that
the episode record itself does not depend on it. If git is unavailable the commit is recorded as
unknown and is never invented.

See D41.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from verum.contracts.paths import config_dir, repo_root


def canonical_json(value: Any) -> str:
    """Canonical JSON text: sorted keys, no whitespace, non-ASCII kept."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


NOT_HASHED = ("inspection_catalog.json",)  # fixes no simulated or observed value (D108)


def _config_files(directory: Path) -> list[Path]:
    found = [*directory.glob("*.json"), *directory.glob("scenarios/*.json")]
    return sorted(p for p in found if p.name not in NOT_HASHED)


def config_hash(directory: Path | None = None) -> str:
    """SHA-256 of the canonical JSON of all resolved configuration files."""
    base = directory or config_dir()
    content = {
        p.relative_to(base).as_posix(): json.loads(p.read_text(encoding="utf-8"))
        for p in _config_files(base)
    }
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


def lockfile_hash(root: Path | None = None) -> str:
    """SHA-256 of ``uv.lock``."""
    return hashlib.sha256(((root or repo_root()) / "uv.lock").read_bytes()).hexdigest()


def git_state(root: Path | None = None) -> tuple[str, bool]:
    """(commit id, dirty flag); ``("unknown", True)`` if git cannot answer."""
    cwd = root or repo_root()
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True
    return commit, dirty


@dataclass(frozen=True)
class EpisodeRecord:
    """The deterministic part of an episode's provenance."""

    episode_id: str
    scenario_id: str
    seed: int
    config_hash: str
    lockfile_hash: str
    solver_version: str
    dataset_tier: str
    step_size_s: float
    tolerances: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def episode_id(seed: int, scenario_id: str, config: str) -> str:
    """Opaque episode identifier: no scenario name, fault or seed text appears in it."""
    digest = hashlib.sha256(canonical_json([seed, scenario_id, config]).encode("utf-8")).hexdigest()
    return f"EP-{digest[:12].upper()}"
