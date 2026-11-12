"""Estimate the likelihood ratios of the Agent 2 residual states for each Agent 5 family.

Inputs: the diagnostic reasoning role view of the train split. Output: a small JSON file of
ratios P(state | family fault) / P(state | fault-free) for the expected residuals of each family,
with add-one smoothing, a floor and a cap, the counts behind them, and the sha256 of the train
file. Residual states come from models that did not see the window (grouped out-of-fold) and
the pinned residual thresholds. Only train windows are read; the audit hook records every open.
A family with two expected residuals uses their product unless they are strongly correlated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
DETECTOR = Path(__file__).resolve().parents[1] / "detector"
sys.path.insert(0, str(DETECTOR))

import conditions  # noqa: E402
import fit_topology_residual as topology_fit  # noqa: E402
import guard  # noqa: E402
from windows import Windows, load_split  # noqa: E402

from verum.agents.anomaly_detection.parameters import load_parameters  # noqa: E402
from verum.agents.common import iter_role_records  # noqa: E402
from verum.agents.diagnostic_reasoning import mechanism  # noqa: E402

METHOD_ID = "a2_evidence_ratios_v1"
FORMAT = 1
FLOOR, CAP = 0.05, 20.0
MIN_WINDOWS = 10
MAX_PHI = 0.5
UNKNOWN, WITHIN, EXCEEDED = 0, 1, 2
KEYS = ("R1", "R2", "R3", "R4")
SENSORS = ("bias", "drift", "stuck")


def states_of(parts: np.ndarray[Any, Any], thresholds: dict[str, float]) -> np.ndarray[Any, Any]:
    """State code of each residual of each window: unknown, within normal or exceeded."""
    out = np.full(parts.shape, UNKNOWN, dtype=np.intp)
    for j, key in enumerate(KEYS):
        z = parts[:, j]
        known = np.isfinite(z)
        out[known, j] = np.where(z[known] > thresholds[key], EXCEEDED, WITHIN)
    return out


def window_families(rel: Path, ids: list[str]) -> list[str | None]:
    """Family name of each window with one injected component; None if it has none or many."""
    wanted = {name: i for i, name in enumerate(ids)}
    found: list[str | None] = [None] * len(ids)
    kind: list[int] = [0] * len(ids)
    for rec in iter_role_records(rel, "diagnostic_reasoning", "train"):
        if rec.example_id not in wanted:
            continue
        i, comps = wanted[rec.example_id], rec.target["injected_components"] or []
        kind[i] = len(comps)
        if len(comps) == 1:
            c = comps[0]
            tag = c["asset_id"] if c["mechanism"] in SENSORS else None
            hypo = {"components": [{"mechanism": c["mechanism"], "asset_id": c["asset_id"],
                                    "tag_id": tag}]}  # fmt: skip
            family = mechanism.family_of(hypo)
            found[i] = family.name if family else None
    return [None if k > 1 else f for f, k in zip(found, kind, strict=True)]


def smoothed(count: int, total: int) -> float:
    """Add-one smoothed share."""
    return (count + 1) / (total + 2)


def ratio_table(
    code: np.ndarray[Any, Any], rows: np.ndarray[Any, Any], free: np.ndarray[Any, Any], j: int
) -> dict[str, Any]:
    """Ratios of one residual for the windows of one family against the fault-free windows."""
    fam, base = code[rows, j], code[free, j]
    n_fam, n_base = int((fam != UNKNOWN).sum()), int((base != UNKNOWN).sum())
    out: dict[str, Any] = {"family_windows": n_fam, "fault_free_windows": n_base}
    for name, state in (("exceeded", EXCEEDED), ("within_normal", WITHIN)):
        k_fam, k_base = int((fam == state).sum()), int((base == state).sum())
        raw = smoothed(k_fam, n_fam) / smoothed(k_base, n_base)
        use = 1.0 if n_fam < MIN_WINDOWS else float(min(CAP, max(FLOOR, raw)))
        out[name] = {"count": k_fam, "fault_free_count": k_base, "ratio": use}
    return out


def phi(a: np.ndarray[Any, Any], b: np.ndarray[Any, Any]) -> float:
    """Phi coefficient of two boolean indicators; 0 when either is constant."""
    if len(a) == 0 or a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a.astype(float), b.astype(float))[0, 1])


def correlation(code: np.ndarray[Any, Any], rows: np.ndarray[Any, Any], js: list[int]) -> float:
    """Phi between the exceeded indicators of two residuals where both are computed."""
    both = (code[rows, js[0]] != UNKNOWN) & (code[rows, js[1]] != UNKNOWN)
    a = code[rows, js[0]][both] == EXCEEDED
    b = code[rows, js[1]][both] == EXCEEDED
    return phi(a, b)


def family_entry(
    family: mechanism.Family,
    code: np.ndarray[Any, Any],
    rows: np.ndarray[Any, Any],
    free: np.ndarray[Any, Any],
) -> dict[str, Any]:
    """The ratios of a family and how its residuals are combined."""
    js = [KEYS.index(k) for k in family.expected]
    entry: dict[str, Any] = {
        "expected": list(family.expected),
        "windows": int(rows.sum()),
        "ratios": {
            k: ratio_table(code, rows, free, j)
            for k, j in zip(family.expected, js, strict=True)
        },
        "combine": "single",
    }  # fmt: skip
    if len(js) == 2:
        in_family, in_free = correlation(code, rows, js), correlation(code, free, js)
        entry["phi_family"], entry["phi_fault_free"] = in_family, in_free
        strong = max(abs(in_family), abs(in_free)) > MAX_PHI
        entry["combine"] = "largest" if strong else "product"
    return entry


def build_document(train: Windows, rel: Path, source: Path) -> dict[str, Any]:
    """Estimate the ratios for every family from out-of-fold residual states."""
    _, parts = topology_fit.out_of_fold(train)
    params = load_parameters()
    code = states_of(parts, params.residual_thresholds)
    names = np.asarray(window_families(rel, train.ids), dtype=object)
    free = np.asarray(train.faulty == 0)
    families = {}
    for family in mechanism.ALL_FAMILIES:
        if family.expected:
            rows = np.asarray([n == family.name for n in names])
            families[family.name] = family_entry(family, code, rows, free)
    path = rel / topology_fit.TRAIN_VIEW
    return {
        "method_id": METHOD_ID, "format": FORMAT,
        "provenance": {
            "train_file": str(topology_fit.TRAIN_VIEW), "splits_used": ["train"],
            "train_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "windows": len(train.ids), "fault_free_windows": int(free.sum()),
            "fit_script": source.name, "parameters_sha256": params.sha256,
        },
        "rule": {"smoothing": "add-one", "floor": FLOOR, "cap": CAP,
                 "minimum_family_windows": MIN_WINDOWS, "maximum_phi": MAX_PHI},  # fmt: skip
        "families": families,
    }  # fmt: skip


def main() -> None:
    """Estimate and write the ratio file; print its sha256."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--release", type=Path, default=topology_fit.RELEASE_DEFAULT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    guard.install()
    train = load_split(args.release, "train")
    guard.ALLOWED_EPISODES.update(train.episodes)
    train = conditions.apply(train, conditions.read_conditions(args.release, train.episodes))
    doc = build_document(train, args.release, Path(__file__))
    text = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    args.out.write_text(text, encoding="utf-8")
    print(hashlib.sha256(text.encode()).hexdigest(), args.out)
    print("opened:", guard.summary())


if __name__ == "__main__":
    main()
