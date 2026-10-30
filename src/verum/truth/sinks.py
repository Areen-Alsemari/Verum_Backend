"""Where truth rows go: memory, or a directory of gzip JSON Lines files.

Rows are written exactly as given, with nothing added or filtered. Files carry no timestamp in the
gzip header, so identical rows give identical bytes, and numbers use the shortest round-trip form
with NaN and infinity refused. The manifest lists the SHA-256 of every file except itself. A
rejected episode keeps only its record files. This is evaluator data and is never imported by the
observation or api packages.

See D20.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

DATASETS = (
    "hydraulic_state",
    "solver_diagnostics",
    "mass_ledger",
    "events",
    "boundary_state",
    "validity_windows",
    "fault_truth",
)
MANIFEST = "MANIFEST.sha256"


class TruthSink(Protocol):
    def write(self, dataset: str, row: dict[str, Any]) -> None: ...


class NullSink:
    """Discards rows (accuracy studies that only need the final state)."""

    discards = True

    def write(self, dataset: str, row: dict[str, Any]) -> None:
        return None


class ListSink:
    """Collects rows in memory (tests and restart comparisons)."""

    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {d: [] for d in DATASETS}

    def write(self, dataset: str, row: dict[str, Any]) -> None:
        self.rows[dataset].append(row)


def dumps(row: dict[str, Any]) -> bytes:
    return (json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


class DirectorySink:
    """One directory per episode with one gzip JSON Lines file per dataset."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self._files: dict[str, Any] = {}
        self._raw: dict[str, Any] = {}
        for dataset in DATASETS:  # every dataset file exists, even if it stays empty
            self._open(dataset)

    def _open(self, dataset: str) -> Any:
        if dataset not in self._files:
            raw = (self.directory / f"{dataset}.jsonl.gz").open("wb")
            self._raw[dataset] = raw
            self._files[dataset] = gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0
            )
        return self._files[dataset]

    def write(self, dataset: str, row: dict[str, Any]) -> None:
        self._open(dataset).write(dumps(row))

    def write_json(self, name: str, document: dict[str, Any]) -> None:
        (self.directory / name).write_text(
            json.dumps(document, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )

    def close(self) -> None:
        for dataset, handle in self._files.items():
            handle.close()
            self._raw[dataset].close()
        self._files, self._raw = {}, {}

    def discard_data(self) -> None:
        """Remove the data files (a rejected episode keeps only its records)."""
        self.close()
        for dataset in DATASETS:
            (self.directory / f"{dataset}.jsonl.gz").unlink(missing_ok=True)

    def finalize(self) -> dict[str, str]:
        """Close the files and write the manifest; returns name -> SHA-256."""
        self.close()
        hashes = file_hashes(self.directory)
        lines = [f"{digest}  {name}" for name, digest in hashes.items()]
        (self.directory / MANIFEST).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return hashes


def file_hashes(directory: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir())
        if p.is_file() and p.name != MANIFEST
    }


def read_rows(directory: Path, dataset: str) -> list[dict[str, Any]]:
    with gzip.open(directory / f"{dataset}.jsonl.gz", "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]
