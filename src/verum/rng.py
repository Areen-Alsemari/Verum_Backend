"""Named random streams that do not interfere with each other.

Inputs: a master seed and stream names. Outputs: ``numpy.random.Generator`` objects.
Key assumptions:
    * A stream is keyed by the SHA-256 digest of its name: the first 16 bytes of the
      digest become four 32-bit words of a ``SeedSequence`` spawn key. Creating or
      drawing from one stream therefore cannot change another stream.
    * There is no global seeding; the numpy global generator is never touched.
    * Asking twice for the same name returns the same generator (the draws continue);
      a new ``RandomStreams`` with the same master seed starts every stream afresh.
    * No random draw is made in the healthy episodes of Phase 3; the facility exists
      so that later phases cannot fall back on a global seed.

Source: ``revised/05_simulation_validation_dataset.md`` sections 6.10 and 13.1
(named streams, no global NumPy seed).
"""

from __future__ import annotations

import hashlib

import numpy as np


def stream_key(name: str) -> tuple[int, int, int, int]:
    """Spawn key derived from the SHA-256 of the stream name."""
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return tuple(int.from_bytes(digest[i : i + 4], "big") for i in (0, 4, 8, 12))  # type: ignore[return-value]


class RandomStreams:
    """A set of named, independent, reproducible random streams."""

    def __init__(self, master_seed: int) -> None:
        if master_seed < 0:
            raise ValueError("the master seed must not be negative")
        self.master_seed = master_seed
        self._streams: dict[str, np.random.Generator] = {}

    def stream(self, name: str) -> np.random.Generator:
        """The generator for ``name``, created on first use."""
        if not name:
            raise ValueError("a stream needs a name")
        if name not in self._streams:
            sequence = np.random.SeedSequence(entropy=self.master_seed, spawn_key=stream_key(name))
            self._streams[name] = np.random.Generator(np.random.PCG64(sequence))
        return self._streams[name]
