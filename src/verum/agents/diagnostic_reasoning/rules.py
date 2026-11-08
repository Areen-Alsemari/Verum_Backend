"""Explicit comparison rules between diagnostic candidates and upstream agent reports.

Upstream evidence is evaluated outside the learned observation model. Missing or failed reports
produce unknown checks, and correlated sensor reports never multiply candidate scores.
"""

from __future__ import annotations

from typing import Any, Final

from verum.agents.common import TAG_ORDER

UPSTREAM_FIELDS: Final[tuple[str, ...]] = (
    "forecast_report",
    "anomaly_report",
    "topology_report",
    "asset_report",
    "inspection_quality_report",
)

SUPPORTED_MECHANISMS: Final[tuple[str, ...]] = (
    "leak",
    "restriction_position_visible",
    "restriction_obstruction",
    "pump",
    "bias",
    "drift",
    "stuck",
    "misroute_a",
)

LOW_SUPPORT_MECHANISMS: Final[dict[str, str]] = {
    "leak": (
        "Low-confidence mechanism (leak): uncalibrated decision score has low test precision "
        "(0.0804 across 20 test episodes); do not interpret score as a probability."
    ),
    "restriction_obstruction": (
        "Low-support mechanism (restriction_obstruction): only 2 validation episodes exist and "
        "test precision is 0.1053; uncalibrated score is not a probability."
    ),
    "bias": (
        "Low-confidence mechanism (bias): uncalibrated decision score has 0.2571 test precision "
        "across 15 test episodes; do not interpret score as a probability."
    ),
    "stuck": (
        "Low-support mechanism (stuck): only 1 positive test episode exists (test F1 0.0000); "
        "uncalibrated score is not a probability."
    ),
    "misroute_a": (
        "Unevaluable mechanism (misroute_a): 0 positive test episodes exist in the held-out "
        "test split; candidate is not evaluable on held-out test data."
    ),
}

SENSOR_MECHANISMS: Final = frozenset({"bias", "drift", "stuck"})

KNOWN_ASSETS: Final[frozenset[str]] = frozenset(
    {
        "TK-101",
        "TK-102",
        "TK-103",
        "P-101A",
        "P-101B",
        "XV-PAI",
        "XV-PAO",
        "XV-PBI",
        "XV-PBO",
        "XV-R000",
        "XV-R101",
        "XV-R102",
        "XV-R103",
        "XV-S101",
        "XV-S102",
        "XV-S103",
        "E001",
        "E002",
        "E003",
        "E-R101a",
        "E-R101b",
        "E-S101a",
        "E-S101b",
        "E-R102a",
        "E-R102b",
        "E-S102a",
        "E-S102b",
        "E-R103a",
        "E-R103b",
        "E-S103a",
        "E-S103b",
        "E-SH",
        "E-PA0",
        "E-PA1",
        "E-PA2",
        "E-PA3",
        "E-PA4",
        "E-PB0",
        "E-PB1",
        "E-PB2",
        "E-PB3",
        "E-PB4",
        "E-D1",
        "E-D2",
        "PT-001",
        "PT-201",
        "PT-202A",
        "PT-202B",
        "PT-203",
    }
)

KNOWN_TAGS: Final[frozenset[str]] = frozenset(TAG_ORDER)

ASSET_PRIMARY_TAGS: Final[dict[str, tuple[str, ...]]] = {
    "TK-101": ("LT-101", "TT-101"),
    "TK-102": ("LT-102", "TT-102"),
    "TK-103": ("LT-103", "TT-103"),
    "P-101A": ("P-101A", "PT-202A", "FT-201", "PT-201"),
    "P-101B": ("P-101B", "PT-202B", "FT-201", "PT-201"),
    "XV-PAO": ("XV-PAO", "PT-202A", "FT-201", "PT-203"),
    "XV-PBO": ("XV-PBO", "PT-202B", "FT-201", "PT-203"),
    "XV-PAI": ("XV-PAI", "PT-201", "PT-202A"),
    "XV-PBI": ("XV-PBI", "PT-201", "PT-202B"),
    "XV-R000": ("XV-R000", "FT-001", "PT-001"),
    "XV-R101": ("XV-R101", "FT-001", "PT-001", "LT-101"),
    "XV-R102": ("XV-R102", "FT-001", "PT-001", "LT-102"),
    "XV-R103": ("XV-R103", "FT-001", "PT-001", "LT-103"),
    "XV-S101": ("XV-S101", "LT-101", "PT-201", "FT-201"),
    "XV-S102": ("XV-S102", "LT-102", "PT-201", "FT-201"),
    "XV-S103": ("XV-S103", "LT-103", "PT-201", "FT-201"),
    "E001": ("FT-001", "PT-001"),
    "E002": ("FT-001", "PT-001"),
    "E003": ("FT-001", "PT-001"),
    "E-D1": ("FT-201", "PT-203", "PT-202A", "PT-202B"),
    "E-D2": ("FT-201", "PT-203"),
}

MECHANISM_FORECAST_TAGS: Final[dict[str, tuple[str, ...]]] = {
    "pump": ("PT-202A", "PT-202B", "FT-201", "PT-203"),
    "leak": ("FT-001", "FT-201", "PT-001", "PT-201", "PT-203", "LT-101", "LT-102", "LT-103"),
    "restriction_position_visible": ("FT-001", "FT-201", "PT-001", "PT-201", "PT-203"),
    "restriction_obstruction": ("FT-001", "FT-201", "PT-001", "PT-201", "PT-203"),
    "misroute_a": ("FT-001", "FT-201", "LT-101", "LT-102", "LT-103"),
    "bias": ("FT-001", "FT-201", "PT-001", "PT-201", "PT-202A", "PT-202B", "PT-203"),
    "drift": ("FT-001", "FT-201", "PT-001", "PT-201", "PT-202A", "PT-202B", "PT-203"),
    "stuck": ("FT-001", "FT-201", "PT-001", "PT-201", "PT-202A", "PT-202B", "PT-203"),
}


def valid_component(mechanism: str, asset_id: str | None, tag_id: str | None) -> dict[str, Any]:
    """Validate and normalize a candidate component against the known registry."""
    if mechanism not in SUPPORTED_MECHANISMS:
        raise ValueError(f"unsupported mechanism {mechanism!r}")
    clean_asset = asset_id if (asset_id in KNOWN_ASSETS) else None
    clean_tag = tag_id if (tag_id in KNOWN_TAGS) else None
    if mechanism in SENSOR_MECHANISMS and clean_tag is None and asset_id in KNOWN_TAGS:
        clean_tag = asset_id
    return {"mechanism": mechanism, "asset_id": clean_asset, "tag_id": clean_tag}


def _is_stub_or_failed(report: dict[str, Any] | None) -> bool:
    if report is None or report.get("result") is None:
        return True
    if report.get("status") in ("insufficient_evidence", "error"):
        return True
    issues = report.get("issues", [])
    return any(i.get("code") in ("STUB_NOT_IMPLEMENTED", "CONTRACT_EXAMPLE") for i in issues)


def _compare_tag_forecast(
    mech: str, tag_id: str, fc_row: dict[str, Any], sig: dict[str, Any] | None
) -> str:
    """Compare one tag's forecast value and direction against the candidate mechanism."""
    if fc_row.get("value") is None or sig is None or sig.get("mean") is None:
        return "unknown"
    fc_val = float(fc_row["value"])
    obs_mean = float(sig["mean"])
    obs_latest = float(sig["latest_value"]) if sig.get("latest_value") is not None else obs_mean
    obs_std = float(sig.get("standard_deviation") or 0.0)
    obs_slope = float(sig.get("slope_per_s") or 0.0)
    horizon = float(fc_row.get("horizon_s") or 300.0)
    tol = max(abs(obs_mean) * 0.01, obs_std, 0.02)
    fc_delta = fc_val - obs_mean
    obs_delta = obs_latest - obs_mean
    ref_delta = obs_slope * horizon if abs(obs_slope * horizon) >= abs(obs_delta) else obs_delta

    if mech == "stuck":
        return "support" if abs(fc_val - obs_latest) <= tol else "conflict"
    if mech in ("drift", "bias"):
        if abs(ref_delta) > 1e-5:
            if fc_delta * ref_delta > 0 and abs(fc_delta) >= 0.25 * min(abs(ref_delta), tol):
                return "support"
            if fc_delta * ref_delta < 0 and abs(fc_delta) > tol:
                return "conflict"
        return "support" if abs(fc_delta) > tol else "unknown"

    rises = (
        tag_id == "PT-001"
        and mech in ("restriction_position_visible", "restriction_obstruction", "misroute_a")
    ) or (tag_id == "PT-201" and mech == "pump")
    expected_sign = 1.0 if rises else -1.0
    if fc_delta * expected_sign > tol or (
        abs(ref_delta) > tol and fc_delta * ref_delta > 0 and abs(fc_delta) > 0.25 * tol
    ):
        return "support"
    if fc_delta * expected_sign < -tol or (
        abs(ref_delta) > tol and fc_delta * ref_delta < 0 and abs(fc_delta) > tol
    ):
        return "conflict"
    return "unknown"


def _check_forecast_report(
    inputs: dict[str, Any],
    components: list[dict[str, Any]],
    comp_tags: set[str],
    support: list[str],
    conflicts: list[str],
    questions: list[str],
) -> None:
    """Compare forecast direction and values on matching tags against the hypothesis."""
    fc = inputs.get("forecast_report")
    if _is_stub_or_failed(fc) or fc is None:
        questions.append("Near-term sensor forecast comparison is unavailable.")
        return
    obs = inputs.get("observations") or {}
    summary = obs.get("summary", obs)
    signals = {s["tag_id"]: s for s in summary.get("signals", [])}
    forecasts = {f["tag_id"]: f for f in fc["result"].get("forecasts", []) if "tag_id" in f}
    target_tags = {t for t in comp_tags if t in forecasts}
    if not target_tags:
        for comp in components:
            target_tags.update(
                t for t in MECHANISM_FORECAST_TAGS.get(comp["mechanism"], ()) if t in forecasts
            )
    outcomes = [
        _compare_tag_forecast(comp["mechanism"], tag, forecasts[tag], signals.get(tag))
        for comp in components
        for tag in sorted(target_tags)
    ]
    if "conflict" in outcomes:
        if fc["report_id"] not in conflicts:
            conflicts.append(fc["report_id"])
    elif "support" in outcomes:
        if fc["report_id"] not in support:
            support.append(fc["report_id"])
    else:
        questions.append(
            "Forecast values on matching tags do not show a directional departure "
            "confirming or contradicting the candidate."
        )


def _check_single_upstream(
    field: str, res: dict[str, Any], report_id: str, hypotheses: list[dict[str, Any]] | None
) -> str:
    """Determine pass, fail or unknown outcome for one usable upstream report result."""
    if field == "forecast_report":
        if not hypotheses:
            return "unknown"
        if any(report_id in h.get("conflict_evidence_ids", []) for h in hypotheses):
            return "fail"
        if any(report_id in h.get("support_evidence_ids", []) for h in hypotheses):
            return "pass"
        return "unknown"
    if field == "anomaly_report":
        if res.get("coverage") in ("assessed", "partial"):
            return "pass"
    elif field == "topology_report":
        if res.get("routing_assessment") == "declared_only" or res.get("direct_connections"):
            return "pass"
    elif field == "asset_report":
        if res.get("asset_records") or res.get("facts"):
            return "pass"
        if res.get("missing_asset_ids"):
            return "fail"
    elif field == "inspection_quality_report":
        r_checks = res.get("record_checks", [])
        if any(rc.get("measurement_usable") is True for rc in r_checks):
            return "pass"
        if any(rc.get("measurement_usable") is False for rc in r_checks):
            return "fail"
    return "unknown"


def evaluate_upstream_checks(
    inputs: dict[str, Any], hypotheses: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Build the five required upstream_checks entries in canonical order."""
    checks: list[dict[str, Any]] = []
    for field in UPSTREAM_FIELDS:
        report = inputs.get(field)
        if _is_stub_or_failed(report) or report is None:
            ev_ids = [] if report is None else [report["report_id"]]
            checks.append(
                {
                    "check_id": field,
                    "description": f"Compare available {field}",
                    "outcome": "unknown",
                    "evidence_ids": ev_ids,
                }
            )
            continue
        outcome = _check_single_upstream(field, report["result"], report["report_id"], hypotheses)
        checks.append(
            {
                "check_id": field,
                "description": f"Compare available {field}",
                "outcome": outcome,
                "evidence_ids": [report["report_id"]],
            }
        )
    return checks


def _check_anomaly_and_forecast(
    inputs: dict[str, Any],
    components: list[dict[str, Any]],
    comp_assets: set[str],
    comp_tags: set[str],
    support: list[str],
    conflicts: list[str],
    questions: list[str],
) -> None:
    """Compare candidate assets and tags with anomaly and forecast reports."""
    anom = inputs.get("anomaly_report")
    if not _is_stub_or_failed(anom) and anom is not None:
        events = anom["result"].get("events", [])
        anom_assets = {a for ev in events for a in ev.get("asset_ids", [])}
        anom_tags = {t for ev in events for t in ev.get("tag_ids", [])}
        if (comp_assets & anom_assets) or (comp_tags & anom_tags):
            if anom["report_id"] not in support:
                support.append(anom["report_id"])
        elif events and anom["result"].get("coverage") == "assessed":
            if anom["report_id"] not in conflicts:
                conflicts.append(anom["report_id"])
    else:
        questions.append("Anomaly detection report is unavailable or inconclusive.")

    _check_forecast_report(inputs, components, comp_tags, support, conflicts, questions)


def _check_topology_asset_inspection(
    inputs: dict[str, Any],
    comp_assets: set[str],
    support: list[str],
    conflicts: list[str],
    questions: list[str],
) -> None:
    """Compare candidate assets with topology, asset intelligence and inspection quality."""
    topo = inputs.get("topology_report")
    if not _is_stub_or_failed(topo) and topo is not None:
        conns = topo["result"].get("direct_connections", [])
        reach = set(topo["result"].get("reachable_nodes", []))
        topo_ids = reach | {
            c[k].split(":")[0] for c in conns for k in ("edge_id", "from_node", "to_node")
        }
        if not comp_assets or (comp_assets & topo_ids):
            if topo["report_id"] not in support:
                support.append(topo["report_id"])
        elif conns and comp_assets and topo["report_id"] not in conflicts:
            conflicts.append(topo["report_id"])
    else:
        questions.append("Actual flow routing and valve positions remain unconfirmed.")

    asset_rep = inputs.get("asset_report")
    if not _is_stub_or_failed(asset_rep) and asset_rep is not None:
        known_rec = {a["asset_id"] for a in asset_rep["result"].get("asset_records", [])}
        missing_rec = set(asset_rep["result"].get("missing_asset_ids", []))
        if comp_assets & missing_rec and asset_rep["report_id"] not in conflicts:
            conflicts.append(asset_rep["report_id"])
        elif comp_assets & known_rec and asset_rep["report_id"] not in support:
            support.append(asset_rep["report_id"])

    insp = inputs.get("inspection_quality_report")
    if not _is_stub_or_failed(insp) and insp is not None:
        r_checks = insp["result"].get("record_checks", [])
        if any(rc.get("measurement_usable") is True for rc in r_checks):
            if insp["report_id"] not in support:
                support.append(insp["report_id"])
        elif any(rc.get("measurement_usable") is False for rc in r_checks):
            if insp["report_id"] not in conflicts:
                conflicts.append(insp["report_id"])
    else:
        questions.append("No verified physical field inspection has confirmed the candidate.")


def enrich_hypothesis_with_rules(
    hypothesis: dict[str, Any], inputs: dict[str, Any], obs_evidence_ids: list[str]
) -> dict[str, Any]:
    """Compare a candidate hypothesis against available upstream reports without score changes."""
    support = list(obs_evidence_ids)
    conflicts: list[str] = []
    questions: list[str] = list(hypothesis.get("unresolved_questions", []))

    components = hypothesis["components"]
    comp_assets = {c["asset_id"] for c in components if c.get("asset_id")}
    comp_tags = {c["tag_id"] for c in components if c.get("tag_id")}
    for asset in comp_assets:
        comp_tags.update(ASSET_PRIMARY_TAGS.get(asset, ()))

    for comp in components:
        mech = comp["mechanism"]
        if mech in LOW_SUPPORT_MECHANISMS and LOW_SUPPORT_MECHANISMS[mech] not in questions:
            questions.append(LOW_SUPPORT_MECHANISMS[mech])

    _check_anomaly_and_forecast(
        inputs, components, comp_assets, comp_tags, support, conflicts, questions
    )
    _check_topology_asset_inspection(inputs, comp_assets, support, conflicts, questions)

    return {
        **hypothesis,
        "support_evidence_ids": support,
        "conflict_evidence_ids": conflicts,
        "unresolved_questions": questions,
    }
