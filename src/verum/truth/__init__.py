"""Hidden truth store: sinks for the evaluator-only datasets of an episode.

Nothing in this package is reachable from the gateway or an observation package.

See D20.
"""

from verum.truth.sinks import (
    DATASETS,
    MANIFEST,
    DirectorySink,
    ListSink,
    NullSink,
    TruthSink,
    file_hashes,
    read_rows,
)

__all__ = [
    "DATASETS",
    "MANIFEST",
    "DirectorySink",
    "ListSink",
    "NullSink",
    "TruthSink",
    "file_hashes",
    "read_rows",
]
