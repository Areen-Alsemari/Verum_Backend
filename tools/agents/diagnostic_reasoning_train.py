"""Train and evaluate the Diagnostic Reasoning observation models on the reference dataset.

Compares computed baselines, one-vs-rest LogisticRegression, and HistGradientBoostingClassifier
across all eight supported mechanisms and candidate (mechanism, asset) pairs. Evaluates existing
artifacts without retraining when --eval-only is passed, refusing to write into the package folder
by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import joblib  # type: ignore[import-untyped]
import numpy as np
import sklearn  # type: ignore[import-untyped]
from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.metrics import f1_score, precision_score, recall_score  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

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
from verum.agents.diagnostic_reasoning.model import (
    MODEL_METHOD_ID,
    DiagnosticModel,
    default_artifact_path,
)
from verum.agents.diagnostic_reasoning.rules import KNOWN_ASSETS, SUPPORTED_MECHANISMS
from verum.contracts.agent_interfaces import contract_directory
from verum.contracts.paths import repo_root

ROLE = "diagnostic_reasoning"
DEFAULT_RELEASE = Path("data/reference_release_v2/verum_reference_v2")
NAMED_SEED = 20261108


def _load_split(
    release: Path, split: str
) -> tuple[
    np.ndarray,
    dict[str, np.ndarray],
    dict[str, np.ndarray],
    list[str],
    list[dict[str, Any]],
    list[dict[str, Any]],
    np.ndarray,
]:
    """Load eligible vectors, mechanism/component labels, episodes, summaries and masked rows."""
    ep_map = episode_lookup(release, split)
    x_rows: list[np.ndarray] = []
    mech_lists: dict[str, list[int]] = {m: [] for m in SUPPORTED_MECHANISMS}
    comp_sets: list[set[str]] = []
    episodes: list[str] = []
    raw_summaries: list[dict[str, Any]] = []
    ineligible_summaries: list[dict[str, Any]] = []
    ineligible_leak_flags: list[int] = []

    for rec in iter_role_records(release, ROLE, split):
        raw_obs = rec.input["observations"]
        obs = raw_obs if "representation" in raw_obs else summary_representation(raw_obs, [])
        target = rec.target
        comps = target.get("injected_components") or []
        present_mechs = {c["mechanism"] for c in comps if c["mechanism"] in SUPPORTED_MECHANISMS}
        if not target.get("supervised_loss_mask"):
            ineligible_summaries.append(obs)
            ineligible_leak_flags.append(1 if "leak" in present_mechs else 0)
            continue
        x_rows.append(extract_observation_vector(obs))
        raw_summaries.append(obs)
        for m in SUPPORTED_MECHANISMS:
            mech_lists[m].append(1 if m in present_mechs else 0)
        comp_sets.append(
            {
                f"{c['mechanism']}::{c['asset_id']}"
                for c in comps
                if c.get("mechanism") in SUPPORTED_MECHANISMS and c.get("asset_id") in KNOWN_ASSETS
            }
        )
        ep_ref = ep_map.get(rec.example_id)
        episodes.append(ep_ref.episode_id if ep_ref else rec.example_id)

    x_mat = np.vstack(x_rows) if x_rows else np.empty((0, len(feature_names())))
    y_mech = {m: np.asarray(vals, dtype=np.int32) for m, vals in mech_lists.items()}
    all_keys = sorted({k for s in comp_sets for k in s})
    y_comp = {
        k: np.asarray([1 if k in s else 0 for s in comp_sets], dtype=np.int32) for k in all_keys
    }
    inelig_leak = np.asarray(ineligible_leak_flags, dtype=np.int32)
    return x_mat, y_mech, y_comp, episodes, raw_summaries, ineligible_summaries, inelig_leak


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


def _metrics(y_true: np.ndarray, y_pred: np.ndarray, episodes: list[str]) -> dict[str, Any]:
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


def _compute_calibration_check(
    y_true_by_mech: dict[str, np.ndarray],
    probs_by_mech: dict[str, np.ndarray],
    all_leak_y: np.ndarray | None = None,
    all_leak_ge_09: np.ndarray | None = None,
) -> dict[str, Any]:
    """Audit empirical precision across high-score bins to show scores are not probabilities."""
    audit: dict[str, Any] = {}
    for mech, y_true in y_true_by_mech.items():
        probs = probs_by_mech.get(mech)
        if probs is None or int(y_true.sum()) == 0:
            audit[mech] = {"status": "not_evaluable", "bins": []}
            continue
        bins = []
        for lo, hi in ((0.2, 0.5), (0.5, 0.8), (0.8, 0.9), (0.9, 1.01)):
            mask = (probs >= lo) & (probs < hi)
            cnt = int(mask.sum())
            pos = int(y_true[mask].sum()) if cnt > 0 else 0
            emp = round(pos / cnt, 4) if cnt > 0 else None
            bins.append(
                {
                    "score_range": f"[{lo:.1f}, {min(hi, 1.0):.1f}]",
                    "count": cnt,
                    "true_positives": pos,
                    "empirical_positive_rate": emp,
                }
            )
        hi_mask = probs >= 0.9
        hi_cnt = int(hi_mask.sum())
        hi_pos = int(y_true[hi_mask].sum()) if hi_cnt > 0 else 0
        entry: dict[str, Any] = {
            "status": "uncalibrated_decision_score",
            "score_ge_0_9_count": hi_cnt,
            "score_ge_0_9_true_positives": hi_pos,
            "score_ge_0_9_empirical_precision": round(hi_pos / hi_cnt, 4) if hi_cnt > 0 else None,
            "bins": bins,
        }
        if mech == "leak" and all_leak_y is not None and all_leak_ge_09 is not None:
            all_cnt = int(all_leak_ge_09.sum())
            all_pos = int((all_leak_ge_09 & all_leak_y).sum()) if all_cnt > 0 else 0
            entry["all_records_score_ge_0_9_count"] = all_cnt
            entry["all_records_score_ge_0_9_true_positives"] = all_pos
            entry["population_note"] = (
                f"{hi_pos} of {hi_cnt} on eligible windows, "
                f"{all_pos} of {all_cnt} across all records"
            )
        audit[mech] = entry
    return audit


def _evaluate_heuristic_and_localisation(
    model: DiagnosticModel,
    x_te_s: np.ndarray,
    yc_tr: dict[str, np.ndarray],
    yc_te: dict[str, np.ndarray],
    te_summaries: list[dict[str, Any]],
    ym_te: dict[str, np.ndarray],
    ineligible_te: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Evaluate the heuristic fallback, asset localisation, and ineligible trigger rate."""
    heur_stuck = np.zeros(len(te_summaries), dtype=np.int32)
    heur_drift = np.zeros(len(te_summaries), dtype=np.int32)
    for i, obs in enumerate(te_summaries):
        preds = model._predict_heuristic(obs)
        mechs = {p.mechanism for p in preds}
        if "stuck" in mechs:
            heur_stuck[i] = 1
        if "drift" in mechs:
            heur_drift[i] = 1
    heuristic_eval = {
        "constants": {
            "STUCK_MIN_SAMPLES": 50,
            "STUCK_MIN_ACTIVE_MEAN": 1.0,
            "STUCK_DECISION_SCORE": 0.75,
            "DRIFT_IDLE_FLOW_MAX_M3H": 5.0,
            "DRIFT_MIN_LEVEL_SLOPE_MS": 0.0005,
            "DRIFT_DECISION_SCORE": 0.70,
        },
        "stuck_rule_test": {
            "predicted_positives": int(heur_stuck.sum()),
            "true_positives": int((heur_stuck & ym_te["stuck"]).sum()),
            "precision": round(
                float(precision_score(ym_te["stuck"], heur_stuck, zero_division=0)), 4
            ),
            "recall": round(float(recall_score(ym_te["stuck"], heur_stuck, zero_division=0)), 4),
            "f1": round(float(f1_score(ym_te["stuck"], heur_stuck, zero_division=0)), 4),
        },
        "drift_rule_test": {
            "predicted_positives": int(heur_drift.sum()),
            "true_positives": int((heur_drift & ym_te["drift"]).sum()),
            "precision": round(
                float(precision_score(ym_te["drift"], heur_drift, zero_division=0)), 4
            ),
            "recall": round(float(recall_score(ym_te["drift"], heur_drift, zero_division=0)), 4),
            "f1": round(float(f1_score(ym_te["drift"], heur_drift, zero_division=0)), 4),
        },
    }

    seen_train_assets = {k.split("::", 1)[1] for k, v in yc_tr.items() if int(v.sum()) > 0} & set(
        KNOWN_ASSETS
    )
    unseen_assets = sorted(KNOWN_ASSETS - seen_train_assets)
    comp_models = (model.artifact or {}).get("component_models", {})
    comp_thresholds = (model.artifact or {}).get("component_thresholds", {})
    loc_y_true = []
    loc_y_pred = []
    per_pair: dict[str, Any] = {}
    for key, clf in sorted(comp_models.items()):
        y_t = yc_te.get(key, np.zeros(len(x_te_s), dtype=np.int32))
        probs = clf.predict_proba(x_te_s)[:, 1]
        y_p = (probs >= float(comp_thresholds.get(key, 0.45))).astype(np.int32)
        loc_y_true.append(y_t)
        loc_y_pred.append(y_p)
        if int(y_t.sum()) > 0:
            per_pair[key] = {
                "test_positives": int(y_t.sum()),
                "precision": round(float(precision_score(y_t, y_p, zero_division=0)), 4),
                "recall": round(float(recall_score(y_t, y_p, zero_division=0)), 4),
                "f1": round(float(f1_score(y_t, y_p, zero_division=0)), 4),
            }
    loc_yt_mat = np.column_stack(loc_y_true) if loc_y_true else np.zeros((len(x_te_s), 1))
    loc_yp_mat = np.column_stack(loc_y_pred) if loc_y_pred else np.zeros((len(x_te_s), 1))
    localisation_eval = {
        "total_known_assets": len(KNOWN_ASSETS),
        "assets_seen_in_train_positives": len(seen_train_assets),
        "assets_never_in_train_count": len(unseen_assets),
        "assets_never_in_train_ids": unseen_assets,
        "trained_component_classifiers_count": len(comp_models),
        "test_localisation_micro_f1": round(
            float(f1_score(loc_yt_mat, loc_yp_mat, average="micro", zero_division=0)), 4
        ),
        "test_localisation_macro_f1": round(
            float(f1_score(loc_yt_mat, loc_yp_mat, average="macro", zero_division=0)), 4
        ),
        "test_localisation_exact_set_accuracy": round(
            float(np.mean(np.all(loc_yt_mat == loc_yp_mat, axis=1))), 4
        ),
        "evaluable_component_pairs": per_pair,
    }

    triggered_ineligible = 0
    for obs in ineligible_te:
        if model.predict_candidates(obs):
            triggered_ineligible += 1
    ineligible_rate = round(triggered_ineligible / len(ineligible_te), 4) if ineligible_te else 0.0
    ineligible_audit = {
        "ineligible_test_windows": len(ineligible_te),
        "windows_with_hypotheses": triggered_ineligible,
        "hypothesis_trigger_rate": ineligible_rate,
    }
    return heuristic_eval, localisation_eval, ineligible_audit


def evaluate_existing_artifact(
    release: Path,
    artifact_path: Path,
    *,
    report_out: Path | None = None,
    allow_package_write: bool = False,
) -> dict[str, Any]:
    """Evaluate an already-saved model artifact on the dataset without re-serializing it."""
    pkg_dir = default_artifact_path().resolve().parent
    if (
        report_out is not None
        and report_out.resolve().parent == pkg_dir
        and not allow_package_write
    ):
        raise ValueError("--eval-only refuses to write into the package folder by default")

    t0 = time.time()
    x_tr, ym_tr, yc_tr, ep_tr, _, _, _ = _load_split(release, "train")
    x_va, ym_va, _, ep_va, _, _, _ = _load_split(release, "validation")
    x_te, ym_te, yc_te, ep_te, te_summaries, ineligible_te, inelig_leak = _load_split(
        release, "test"
    )

    sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    model = DiagnosticModel(artifact_path, expected_sha256=sha256)
    assert model.artifact is not None
    scaler = model.artifact["scaler"]
    x_tr_s = scaler.transform(x_tr)
    x_va_s = scaler.transform(x_va)
    x_te_s = scaler.transform(x_te)

    mech_models = model.artifact["mechanism_models"]
    mech_thresholds = model.artifact["mechanism_thresholds"]

    raw_val: dict[str, dict[str, Any]] = {}
    lr_wins: list[str] = []
    for idx, mech in enumerate(SUPPORTED_MECHANISMS):
        y_train, y_val = ym_tr[mech], ym_va[mech]
        zero_preds = np.zeros_like(y_val)
        one_preds = np.ones_like(y_val)
        c0_f1 = round(float(f1_score(y_val, zero_preds, zero_division=0)), 4)
        c1_f1 = round(float(f1_score(y_val, one_preds, zero_division=0)), 4)

        lr = LogisticRegression(
            max_iter=500, class_weight="balanced", random_state=NAMED_SEED + idx
        )
        lr.fit(x_tr_s, y_train)
        lr_probs = lr.predict_proba(x_va_s)[:, 1]
        lr_t = _best_threshold(y_val, lr_probs)
        lr_f1 = round(
            float(f1_score(y_val, (lr_probs >= lr_t).astype(np.int32), zero_division=0)), 4
        )

        clf = mech_models[mech]
        hgb_probs = clf.predict_proba(x_va_s)[:, 1]
        hgb_t = float(mech_thresholds[mech])
        hgb_f1 = round(
            float(f1_score(y_val, (hgb_probs >= hgb_t).astype(np.int32), zero_division=0)), 4
        )
        if lr_f1 > hgb_f1:
            lr_wins.append(mech)
        raw_val[mech] = {
            "constant_zero_val_f1": c0_f1,
            "constant_one_val_f1": c1_f1,
            "logistic_regression_val_f1": lr_f1,
            "hist_gradient_boosting_val_f1": hgb_f1,
            "selected_threshold": hgb_t,
            "shipped_family": "HistGradientBoostingClassifier",
        }

    rationale = (
        "HistGradientBoostingClassifier is kept across all mechanisms to avoid committing a "
        "second 21 MB binary artifact to git history; LogisticRegression achieved higher "
        f"validation F1 on {len(lr_wins)} mechanisms ({', '.join(lr_wins)})."
    )
    val_comparison = {
        mech: {**entry, "selection_rationale": rationale} for mech, entry in raw_val.items()
    }

    test_per_label: dict[str, Any] = {}
    probs_te_by_mech: dict[str, np.ndarray] = {}
    y_te_mat = []
    y_pred_mat = []
    for mech in SUPPORTED_MECHANISMS:
        y_true = ym_te[mech]
        clf = mech_models.get(mech)
        if clf is None:
            probs = np.zeros(len(y_true), dtype=np.float64)
            preds = np.zeros_like(y_true)
        else:
            probs = clf.predict_proba(x_te_s)[:, 1]
            preds = (probs >= mech_thresholds[mech]).astype(np.int32)
        probs_te_by_mech[mech] = probs
        test_per_label[mech] = _metrics(y_true, preds, ep_te)
        if int(y_true.sum()) > 0:
            y_te_mat.append(y_true)
            y_pred_mat.append(preds)

    all_summaries = te_summaries + ineligible_te
    all_leak_y = (
        np.concatenate([ym_te["leak"], inelig_leak]) if len(inelig_leak) > 0 else ym_te["leak"]
    )
    all_leak_ge_09 = np.asarray(
        [
            1
            if any(p.mechanism == "leak" and p.score >= 0.9 for p in model.predict_candidates(o))
            else 0
            for o in all_summaries
        ],
        dtype=np.int32,
    )

    y_te_all = np.column_stack(y_te_mat)
    y_pr_all = np.column_stack(y_pred_mat)
    zero_te_all = np.zeros_like(y_te_all)

    baseline_no_fault = {
        "micro_f1": round(
            float(f1_score(y_te_all, zero_te_all, average="micro", zero_division=0)), 4
        ),
        "macro_f1_evaluable": round(
            float(f1_score(y_te_all, zero_te_all, average="macro", zero_division=0)), 4
        ),
        "exact_set_accuracy": round(float(np.mean(np.all(y_te_all == zero_te_all, axis=1))), 4),
    }

    exact_set = round(float(np.mean(np.all(y_te_all == y_pr_all, axis=1))), 4)
    micro_f1 = round(float(f1_score(y_te_all, y_pr_all, average="micro", zero_division=0)), 4)
    macro_f1 = round(float(f1_score(y_te_all, y_pr_all, average="macro", zero_division=0)), 4)

    calibration_check = _compute_calibration_check(
        ym_te, probs_te_by_mech, all_leak_y=all_leak_y, all_leak_ge_09=all_leak_ge_09
    )
    heur_eval, loc_eval, inelig_audit = _evaluate_heuristic_and_localisation(
        model, x_te_s, yc_tr, yc_te, te_summaries, ym_te, ineligible_te
    )
    cal_leak = calibration_check["leak"]
    elig_pos = cal_leak["score_ge_0_9_true_positives"]
    elig_cnt = cal_leak["score_ge_0_9_count"]
    all_pos = cal_leak["all_records_score_ge_0_9_true_positives"]
    all_cnt = cal_leak["all_records_score_ge_0_9_count"]
    inelig_pct = round(inelig_audit["hypothesis_trigger_rate"] * 100)

    summary_report = {
        "role": ROLE,
        "artifact_path": artifact_path.name,
        "artifact_sha256": sha256,
        "library_versions": {
            "scikit_learn": sklearn.__version__,
            "numpy": np.__version__,
            "joblib": joblib.__version__,
        },
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
        "test_baseline_always_negative": baseline_no_fault,
        "test_overall": {
            "micro_f1": micro_f1,
            "macro_f1_evaluable": macro_f1,
            "exact_set_accuracy": exact_set,
            "headline_comparison": (
                f"Model improves micro-F1 from {baseline_no_fault['micro_f1']:.4f} "
                f"(always-negative baseline) to {micro_f1:.4f} (+{micro_f1:.4f}), while "
                f"exact-set is {exact_set:.4f} vs {baseline_no_fault['exact_set_accuracy']:.4f} "
                "for predicting no fault due to false positives on low-support mechanisms."
            ),
        },
        "validation_model_comparison": val_comparison,
        "test_per_mechanism": test_per_label,
        "calibration_check": calibration_check,
        "heuristic_fallback_evaluation": heur_eval,
        "localisation_evaluation": loc_eval,
        "ineligible_window_audit": inelig_audit,
        "limitations": [
            "Simulation evaluation only; does not establish real terminal diagnostic accuracy.",
            f"Predicting no fault achieves {baseline_no_fault['exact_set_accuracy']:.4f} "
            f"exact-set accuracy on the test split (above the model {exact_set:.4f}), so "
            f"micro-F1 ({micro_f1:.4f} vs {baseline_no_fault['micro_f1']:.4f} baseline) is "
            "the primary metric.",
            f"Scores are uncalibrated decision scores, not probabilities: leak scores >= 0.90 "
            f"were true leaks in {elig_pos} of {elig_cnt} eligible windows and {all_pos} of "
            f"{all_cnt} across all records, and restriction_obstruction has low empirical "
            "precision.",
            "misroute_a has 0 test positive episodes and is reported as not_evaluable.",
            "restriction_obstruction (2 val) and stuck (1 test) have very low episode support.",
            f"{loc_eval['assets_never_in_train_count']} of {loc_eval['total_known_assets']} "
            f"declared assets ({loc_eval['assets_seen_in_train_positives']} seen in training) "
            "never appear in positive training examples and cannot be localized by learned "
            "component models.",
            f"Approximately {inelig_pct}% of masked/ineligible test windows still trigger "
            "hypotheses.",
            "Roof failure, vapour damage and mechanical cascades are outside supported scope.",
        ],
    }
    if report_out is not None:
        report_out.write_text(json.dumps(summary_report, indent=2) + "\n", encoding="utf-8")
    return summary_report


def train_and_evaluate(release: Path, output_artifact: Path) -> dict[str, Any]:
    """Fit models on train, select thresholds on validation, save artifact and evaluate."""
    x_tr, ym_tr, yc_tr, _, _, _, _ = _load_split(release, "train")
    x_va, ym_va, yc_va, _, _, _, _ = _load_split(release, "validation")
    scaler = StandardScaler()
    x_tr_s = scaler.fit_transform(x_tr)
    x_va_s = scaler.transform(x_va)

    hgb_models: dict[str, Any] = {}
    mech_thresholds: dict[str, float] = {}
    for idx, mech in enumerate(SUPPORTED_MECHANISMS):
        y_train, y_val = ym_tr[mech], ym_va[mech]
        if int(y_train.sum()) < 2:
            hgb_models[mech] = None
            mech_thresholds[mech] = 0.99
            continue
        hgb = HistGradientBoostingClassifier(
            max_iter=120,
            max_depth=6,
            learning_rate=0.08,
            class_weight="balanced",
            random_state=NAMED_SEED + 100 + idx,
        )
        hgb.fit(x_tr_s, y_train)
        hgb_probs = hgb.predict_proba(x_va_s)[:, 1]
        hgb_models[mech] = hgb
        mech_thresholds[mech] = _best_threshold(y_val, hgb_probs)

    comp_models: dict[str, Any] = {}
    comp_thresholds: dict[str, float] = {}
    for idx, (key, y_train) in enumerate(sorted(yc_tr.items())):
        if int(y_train.sum()) < 8:
            continue
        clf = HistGradientBoostingClassifier(
            max_iter=100,
            max_depth=5,
            learning_rate=0.08,
            class_weight="balanced",
            random_state=NAMED_SEED + 500 + idx,
        )
        clf.fit(x_tr_s, y_train)
        y_val = yc_va.get(key, np.zeros(len(x_va), dtype=np.int32))
        comp_models[key] = clf
        comp_thresholds[key] = _best_threshold(y_val, clf.predict_proba(x_va_s)[:, 1])

    artifact = {
        "role": ROLE,
        "method_id": MODEL_METHOD_ID,
        "feature_profile_id": FEATURE_PROFILE_ID,
        "feature_names": feature_names(),
        "supported_mechanisms": list(SUPPORTED_MECHANISMS),
        "named_seed": NAMED_SEED,
        "library_versions": {
            "scikit_learn": sklearn.__version__,
            "numpy": np.__version__,
            "joblib": joblib.__version__,
        },
        "scaler": scaler,
        "mechanism_models": hgb_models,
        "mechanism_thresholds": mech_thresholds,
        "component_models": comp_models,
        "component_thresholds": comp_thresholds,
    }
    output_artifact.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output_artifact)
    return evaluate_existing_artifact(
        release,
        output_artifact,
        report_out=output_artifact.with_name("evaluation_report.json"),
        allow_package_write=True,
    )


def run_standalone_check() -> int:
    """Run the agent on its contract example request and verify the response."""
    path = contract_directory() / "examples" / f"{ROLE}.request.json"
    request = json.loads(path.read_text(encoding="utf-8"))
    check_request(request)
    agent = DiagnosticReasoningAgent()
    response = agent.run(request)
    check_response(request, response)
    print(
        json.dumps(
            {
                "agent": ROLE,
                "status": response["status"],
                "assessment": response["result"]["assessment"],
                "artifact_sha256": response["implementation"]["artifact_sha256"],
                "passed": True,
            }
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=repo_root() / DEFAULT_RELEASE)
    parser.add_argument("--artifact", type=Path, default=default_artifact_path())
    parser.add_argument("--report-out", type=Path, default=None)
    parser.add_argument("--allow-package-write", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--eval-only", action="store_true")
    args = parser.parse_args()
    if args.check_only or not args.release.exists():
        return run_standalone_check()
    if args.eval_only and args.artifact.is_file():
        report = evaluate_existing_artifact(
            args.release,
            args.artifact,
            report_out=args.report_out,
            allow_package_write=args.allow_package_write,
        )
    else:
        report = train_and_evaluate(args.release, args.artifact)
    print(json.dumps(report["test_overall"], indent=2))
    return run_standalone_check()


if __name__ == "__main__":
    sys.exit(main())
