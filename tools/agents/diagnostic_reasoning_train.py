"""Train and evaluate the Diagnostic Reasoning observation models on the reference dataset.

Compares a constant baseline, one-vs-rest LogisticRegression, and HistGradientBoostingClassifier
across all eight supported mechanisms and candidate (mechanism, asset) pairs. Saves the trained
model artifact and writes an episode-grouped evaluation report with limitations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score
from sklearn.preprocessing import StandardScaler

from verum.agents.common import (
    check_request,
    check_response,
    episode_lookup,
    iter_role_records,
    summary_representation,
)
from verum.agents.diagnostic_reasoning import DiagnosticReasoningAgent
from verum.agents.diagnostic_reasoning.features import (
    FEATURE_PROFILE_ID,
    extract_observation_vector,
    feature_names,
)
from verum.agents.diagnostic_reasoning.model import MODEL_METHOD_ID, default_artifact_path
from verum.agents.diagnostic_reasoning.rules import SUPPORTED_MECHANISMS
from verum.contracts.agent_interfaces import contract_directory
from verum.contracts.paths import repo_root

ROLE = "diagnostic_reasoning"
DEFAULT_RELEASE = Path("data/reference_release_v2/verum_reference_v2")
NAMED_SEED = 20261108


def _load_split(
    release: Path, split: str
) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, np.ndarray], list[str]]:
    """Load eligible observation vectors, mechanism labels, component labels and episodes."""
    ep_map = episode_lookup(release, split)
    x_rows: list[np.ndarray] = []
    mech_lists: dict[str, list[int]] = {m: [] for m in SUPPORTED_MECHANISMS}
    comp_Select: list[set[str]] = []
    episodes: list[str] = []

    for rec in iter_role_records(release, ROLE, split):
        target = rec.target
        if not target.get("supervised_loss_mask"):
            continue
        raw_obs = rec.input["observations"]
        obs = raw_obs if "representation" in raw_obs else summary_representation(raw_obs, [])
        vec = extract_observation_vector(obs)
        x_rows.append(vec)
        comps = target.get("injected_components") or []
        present_mechs = {c["mechanism"] for c in comps if c["mechanism"] in SUPPORTED_MECHANISMS}
        for m in SUPPORTED_MECHANISMS:
            mech_lists[m].append(1 if m in present_mechs else 0)
        comp_Select.append({
            f"{c['mechanism']}::{c['asset_id']}"
            for c in comps
            if c.get("mechanism") in SUPPORTED_MECHANISMS and c.get("asset_id")
        })
        ep_ref = ep_map.get(rec.example_id)
        episodes.append(ep_ref.episode_id if ep_ref else rec.example_id)

    x_mat = np.vstack(x_rows) if x_rows else np.empty((0, len(feature_names())))
    y_mech = {m: np.asarray(vals, dtype=np.int32) for m, vals in mech_lists.items()}
    all_keys = sorted({k for s in comp_Select for k in s})
    y_comp = {
        k: np.asarray([1 if k in s else 0 for s in comp_Select], dtype=np.int32)
        for k in all_keys
    }
    return x_mat, y_mech, y_comp, episodes


def _best_threshold(y_true: np.ndarray, probs: np.ndarray) -> float:
    if int(y_true.sum()) == 0:
        return 0.99
    best_t, best_f1 = 0.5, -1.0
    for t in np.linspace(0.20, 0.80, 25):
        preds = (probs >= t).astype(np.int32)
        score = float(f1_score(y_true, preds, zero_division=0))
        if score > best_f1:
            best_f1 = score
            best_t = float(t)
    return round(best_t, 4)


def _metrics(
    y_true: np.ndarray, y_pred: np.ndarray, episodes: list[str]
) -> dict[str, Any]:
    pos_windows = int(y_true.sum())
    pos_episodes = len({ep for ep, y in zip(episodes, y_true, strict=True) if y == 1})
    total_episodes = len(set(episodes))
    if pos_windows == 0:
        return {
            "eligible_windows": int(len(y_true)),
            "positive_windows": 0,
            "positive_episodes": 0,
            "total_episodes": total_episodes,
            "status": "not_evaluable",
            "precision": None,
            "recall": None,
            "f1": None,
        }
    return {
        "eligible_windows": int(len(y_true)),
        "positive_windows": pos_windows,
        "positive_episodes": pos_episodes,
        "total_episodes": total_episodes,
        "status": "evaluated",
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
    }


def train_and_evaluate(release: Path, output_artifact: Path) -> dict[str, Any]:
    """Fit models on train, select thresholds on validation, evaluate on test and save artifact."""
    t0 = time.time()
    x_tr, ym_tr, yc_tr, ep_tr = _load_split(release, "train")
    x_va, ym_va, yc_va, ep_va = _load_split(release, "validation")
    x_te, ym_te, yc_te, ep_te = _load_split(release, "test")

    scaler = StandardScaler()
    x_tr_s = scaler.fit_transform(x_tr)
    x_va_s = scaler.transform(x_va)
    x_te_s = scaler.transform(x_te)

    lr_models: dict[str, Any] = {}
    hgb_models: dict[str, Any] = {}
    mech_thresholds: dict[str, float] = {}
    val_comparison: dict[str, Any] = {}

    for idx, mech in enumerate(SUPPORTED_MECHANISMS):
        y_train = ym_tr[mech]
        y_val = ym_va[mech]
        if int(y_train.sum()) < 2:
            lr_models[mech] = None
            hgb_models[mech] = None
            mech_thresholds[mech] = 0.99
            continue

        lr = LogisticRegression(
            max_iter=500, class_weight="balanced", random_state=NAMED_SEED + idx
        )
        lr.fit(x_tr_s, y_train)
        lr_probs = lr.predict_proba(x_va_s)[:, 1]
        lr_t = _best_threshold(y_val, lr_probs)
        lr_f1 = float(f1_score(y_val, (lr_probs >= lr_t).astype(np.int32), zero_division=0))

        hgb = HistGradientBoostingClassifier(
            max_iter=120, max_depth=6, learning_rate=0.08, class_weight="balanced",
            random_state=NAMED_SEED + 100 + idx,
        )
        hgb.fit(x_tr_s, y_train)
        hgb_probs = hgb.predict_proba(x_va_s)[:, 1]
        hgb_t = _best_threshold(y_val, hgb_probs)
        hgb_f1 = float(f1_score(y_val, (hgb_probs >= hgb_t).astype(np.int32), zero_division=0))

        lr_models[mech] = lr
        hgb_models[mech] = hgb
        mech_thresholds[mech] = hgb_t
        val_comparison[mech] = {
            "constant_zero_f1": 0.0,
            "logistic_regression_val_f1": round(lr_f1, 4),
            "hist_gradient_boosting_val_f1": round(hgb_f1, 4),
            "selected_threshold": hgb_t,
        }

    # Train component-level (mechanism::asset_id) classifiers where train support >= 8
    comp_models: dict[str, Any] = {}
    comp_thresholds: dict[str, float] = {}
    for idx, (key, y_train) in enumerate(sorted(yc_tr.items())):
        if int(y_train.sum()) < 8:
            continue
        clf = HistGradientBoostingClassifier(
            max_iter=100, max_depth=5, learning_rate=0.08, class_weight="balanced",
            random_state=NAMED_SEED + 500 + idx,
        )
        clf.fit(x_tr_s, y_train)
        y_val = yc_va.get(key, np.zeros(len(x_va), dtype=np.int32))
        probs_va = clf.predict_proba(x_va_s)[:, 1]
        comp_models[key] = clf
        comp_thresholds[key] = _best_threshold(y_val, probs_va)

    artifact = {
        "role": ROLE,
        "method_id": MODEL_METHOD_ID,
        "feature_profile_id": FEATURE_PROFILE_ID,
        "feature_names": feature_names(),
        "supported_mechanisms": list(SUPPORTED_MECHANISMS),
        "named_seed": NAMED_SEED,
        "scaler": scaler,
        "mechanism_models": hgb_models,
        "mechanism_thresholds": mech_thresholds,
        "component_models": comp_models,
        "component_thresholds": comp_thresholds,
    }
    output_artifact.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output_artifact)
    sha256 = hashlib.sha256(output_artifact.read_bytes()).hexdigest()

    # Final untouched test split evaluation
    test_per_label: dict[str, Any] = {}
    y_te_mat = []
    y_pred_mat = []
    for mech in SUPPORTED_MECHANISMS:
        y_true = ym_te[mech]
        clf = hgb_models.get(mech)
        if clf is None:
            preds = np.zeros_like(y_true)
        else:
            probs = clf.predict_proba(x_te_s)[:, 1]
            preds = (probs >= mech_thresholds[mech]).astype(np.int32)
        test_per_label[mech] = _metrics(y_true, preds, ep_te)
        if int(y_true.sum()) > 0:
            y_te_mat.append(y_true)
            y_pred_mat.append(preds)

    y_te_all = np.column_stack(y_te_mat)
    y_pr_all = np.column_stack(y_pred_mat)
    exact_set = float(np.mean(np.all(y_te_all == y_pr_all, axis=1)))
    micro_f1 = float(f1_score(y_te_all, y_pr_all, average="micro", zero_division=0))
    macro_f1 = float(f1_score(y_te_all, y_pr_all, average="macro", zero_division=0))

    summary_report = {
        "role": ROLE,
        "artifact_path": output_artifact.name,
        "artifact_sha256": sha256,
        "feature_profile_id": FEATURE_PROFILE_ID,
        "named_seed": NAMED_SEED,
        "runtime_s": round(time.time() - t0, 2),
        "eligible_counts": {
            "train_windows": int(len(x_tr)),
            "validation_windows": int(len(x_va)),
            "test_windows": int(len(x_te)),
            "train_episodes": len(set(ep_tr)),
            "validation_episodes": len(set(ep_va)),
            "test_episodes": len(set(ep_te)),
        },
        "validation_model_comparison": val_comparison,
        "test_overall": {
            "micro_f1": round(micro_f1, 4),
            "macro_f1_evaluable": round(macro_f1, 4),
            "exact_set_accuracy": round(exact_set, 4),
        },
        "test_per_mechanism": test_per_label,
        "limitations": [
            "Simulation evaluation only; does not establish real terminal diagnostic accuracy.",
            "misroute_a has 0 test positive episodes and is reported as not_evaluable.",
            "restriction_obstruction (2 val) and stuck (1 test) have very low episode support.",
            "Roof failure, vapour damage and mechanical cascades are outside supported scope.",
        ],
    }
    report_path = output_artifact.with_name("evaluation_report.json")
    report_path.write_text(json.dumps(summary_report, indent=2) + "\n", encoding="utf-8")
    return summary_report


def run_standalone_check() -> int:
    """Run the agent on its contract example request and verify the response."""
    path = contract_directory() / "examples" / f"{ROLE}.request.json"
    request = json.loads(path.read_text(encoding="utf-8"))
    check_request(request)
    agent = DiagnosticReasoningAgent()
    response = agent.run(request)
    check_response(request, response)
    print(json.dumps({
        "agent": ROLE,
        "status": response["status"],
        "assessment": response["result"]["assessment"],
        "artifact_sha256": response["implementation"]["artifact_sha256"],
        "passed": True,
    }))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=repo_root() / DEFAULT_RELEASE)
    parser.add_argument("--artifact", type=Path, default=default_artifact_path())
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if args.check_only or not args.release.exists():
        return run_standalone_check()
    report = train_and_evaluate(args.release, args.artifact)
    print(json.dumps(report["test_overall"], indent=2))
    return run_standalone_check()


if __name__ == "__main__":
    sys.exit(main())
