"""Hidden truth store: sinks for the evaluator-only datasets of an episode.

Nothing in this package is reachable from ``verum.api`` or an observation package.
Source: ``revised/05_simulation_validation_dataset.md`` section 7.2;
``docs/design_decisions.md`` D20.
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
