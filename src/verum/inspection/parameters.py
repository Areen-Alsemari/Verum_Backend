"""What identifies the inspection parameters of a checkout.

The inspection catalog is outside the configuration hash, so an episode record does not say which
catalog the inspection service will use. This module gives the values that an episode directory
records next to its git commit. They describe the checkout that wrote the episode and enter no
episode identifier and no other file.

See D108.
"""

from __future__ import annotations

from pathlib import Path

from verum.inspection.catalog import load_catalog


def provenance_block(directory: Path | None = None) -> dict[str, str]:
    """The inspection fields of the provenance record of an episode directory."""
    return {"inspection_catalog_version": load_catalog(directory).version}
