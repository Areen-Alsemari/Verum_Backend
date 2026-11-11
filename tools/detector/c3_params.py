"""The fitted parameters C3 would ship, counted and compared with the declared tank geometry.

Fits the topology residuals on all fault-free train windows (no scoring) and reports how many
numbers the fit holds, how many belong to the set-condition regimes, the serialised size, and
the fitted tank areas against the area implied by the declared tank diameter.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import candidates
import conditions
import guard
from windows import load_split, subset


def declared_areas(rel: Path) -> dict[str, float]:
    """Cross-section area of each tank from its declared diameter."""
    ref = json.loads((rel / "knowledge" / "public_reference.json").read_text())
    out = {}
    for tank in ("TK-101", "TK-102", "TK-103"):
        diameter = ref["asset_facts"][tank]["declared_dimensions_m"]["diameter_m"]
        out[tank] = math.pi * (float(diameter) / 2.0) ** 2
    return out


def summarise(model: candidates.Residuals) -> dict[str, Any]:
    """Counts and size of the fitted residual model."""
    doc = {
        "mass": {"coef": model.mass.coef.tolist(), "sigma": model.mass.sigma},
        "fits": {"|".join(k): {"coef": f.coef.tolist(), "sigma": f.sigma}
                 for k, f in model.fits.items()},
    }  # fmt: skip
    kinds = Counter(k[0] for k in model.fits)
    return {
        "numbers": len(model.mass.coef) + 1 + sum(len(f.coef) + 1 for f in model.fits.values()),
        "fits": len(model.fits), "fits_by_residual": dict(kinds),
        "regime_specific_fits": sum(1 for k in model.fits if k[0] == "R4" and k[1] != "*"),
        "json_bytes": len(json.dumps(doc)),
        "tank_areas_fitted": [round(float(v), 2) for v in model.mass.coef[:3]],
    }  # fmt: skip


def run(rel: Path, out: Path) -> dict[str, Any]:
    """Fit on all fault-free train windows and write the summary."""
    guard.install()
    train = load_split(rel, "train")
    guard.ALLOWED_EPISODES.update(train.episodes)
    conds = conditions.read_conditions(rel, train.episodes)
    fit = subset(conditions.apply(train, conds), train.faulty == 0)
    res = summarise(candidates.Residuals(fit))
    res["tank_areas_declared"] = {k: round(v, 2) for k, v in declared_areas(rel).items()}
    out.write_text(json.dumps(res, indent=1))
    return res
