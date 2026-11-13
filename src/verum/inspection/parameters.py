"""What identifies the inspection parameters of a checkout.

The inspection catalog is outside the configuration hash, so an episode record does not say which
parameters the inspection service will use. This module gives two values that an episode directory
records next to its git commit: the catalog file's version and a digest of every parameter that
sets an inspection outcome, a delay, a rejection or a history record (the whole catalog file and
the named constants of the outcome models, the workflow and the history generator). They describe
the checkout that wrote the episode and enter no episode identifier and no other file. See D108.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from verum.contracts.paths import config_dir
from verum.inspection import history, models, workflow
from verum.inspection.catalog import FILE, load_catalog
from verum.provenance import canonical_json


def code_constants() -> dict[str, Any]:
    """The parameters that are named constants of the code and not entries of the catalog file."""
    return {
        "agreement_band": models.AGREEMENT,
        "calibration_valid_days": list(workflow.CALIBRATION_VALID_DAYS),
        "history_prior_inspections": list(history.PRIOR_INSPECTIONS),
        "history_prior_calibrations": list(history.PRIOR_CALIBRATIONS),
        "history_prior_work_orders": list(history.PRIOR_WORK_ORDERS),
    }


def parameters_digest(directory: Path | None = None) -> str:
    """SHA-256 of the catalog file as values and of the named constants of the code."""
    path = (directory or config_dir()) / FILE
    document = {
        "catalog": json.loads(path.read_text(encoding="utf-8")),
        "constants": code_constants(),
    }
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def provenance_block(directory: Path | None = None) -> dict[str, str]:
    """The inspection fields of the provenance record of an episode directory."""
    return {
        "inspection_catalog_version": load_catalog(directory).version,
        "inspection_parameters_sha256": parameters_digest(directory),
    }
