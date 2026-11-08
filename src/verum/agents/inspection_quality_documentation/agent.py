"""Rule-based inspection quality and documentation agent."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from verum.agents.common import (
    build_response,
    check_request,
    check_response,
    implementation_block,
    make_issue,
)

ROLE = "inspection_quality_documentation"


class InspectionQualityDocumentationAgent:
    """Assess inspection records without confirming equipment condition."""

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Validate inspection records and return evidence-bound quality checks."""
        check_request(request)

        if request["agent"] != ROLE:
            raise ValueError("Request is addressed to a different agent")

        inputs = request["input"]
        results = inputs["inspection_results"]

        requests = {row["request_id"]: row for row in inputs["inspection_requests"]}
        catalog = {row["action_id"]: row for row in inputs["catalog"]}

        registered_ids = self._registered_evidence_ids(request)
        result_evidence_ids = set(inputs["result_evidence_ids"])
        catalog_evidence_ids = set(inputs["catalog_evidence_ids"])

        record_checks: list[dict[str, Any]] = []
        retest_result_ids: list[str] = []
        issues: list[dict[str, Any]] = []
        limitations: list[str] = []
        consumed_ids: set[str] = set()

        for record in results:
            result_id = record["result_id"]
            inspection_request = requests.get(record["request_id"])
            action = catalog.get(record["action_id"])

            checks: list[dict[str, Any]] = []

            def add_check(
                check_id: str,
                description: str,
                outcome: str,
                evidence_ids: list[str] | None = None,
                checks: list[dict[str, Any]] = checks,
            ) -> None:
                """Append an evidence-bound inspection quality check."""
                checks.append(
                    {
                        "check_id": check_id,
                        "description": description,
                        "outcome": outcome,
                        "evidence_ids": evidence_ids or [],
                    }
                )

            linked = (
                inspection_request is not None
                and inspection_request["action_id"] == record["action_id"]
            )

            request_ids = (
                sorted(
                    {
                        entry["evidence_id"]
                        for entry in request["evidence"]
                        if isinstance(entry, dict)
                        and entry.get("kind") == "inspection_request"
                        and entry.get("source_ref") == f"inspection_request:{record['request_id']}"
                        and entry.get("evidence_id") in registered_ids
                    }
                )
                if inspection_request is not None
                else []
            )
            consumed_ids.update(request_ids)

            add_check(
                "request_link",
                "Inspection result matches its originating request and action.",
                "pass" if linked else "unknown" if inspection_request is None else "fail",
                request_ids,
            )

            performed = record["workflow_status"] == "performed"

            add_check(
                "performed_status",
                "Inspection was recorded as performed.",
                "pass" if performed else "fail",
            )

            evidence_status = record.get("evidence_status")

            add_check(
                "evidence_availability",
                "Inspection evidence is available and marked valid.",
                (
                    "pass"
                    if evidence_status == "valid"
                    else "unknown"
                    if evidence_status is None
                    else "fail"
                ),
            )

            valid_until = record.get("calibration_valid_until")
            as_of_utc = request["context"].get("as_of_utc")
            calibration_outcome = "unknown"
            if valid_until is not None and as_of_utc is not None:
                calibration_outcome = (
                    "pass"
                    if date.fromisoformat(valid_until)
                    >= datetime.fromisoformat(as_of_utc.replace("Z", "+00:00")).date()
                    else "fail"
                )
            add_check(
                "calibration_validity",
                "Tool calibration remains valid at the assessment date.",
                calibration_outcome,
            )

            source_ids = self._source_evidence_ids(
                record,
                request,
                result_evidence_ids,
                registered_ids,
            )

            add_check(
                "source_provenance",
                "Registered evidence is explicitly linked to this result.",
                "pass" if source_ids else "unknown",
                source_ids,
            )

            findings = record.get("findings")
            metric = findings.get("primary_metric") if isinstance(findings, dict) else None

            required_fields_present = (
                self._nonempty(record.get("technician_id"))
                and self._nonempty(record.get("validation_status"))
                and isinstance(findings, dict)
                and self._nonempty(findings.get("outcome_category"))
                and isinstance(metric, dict)
                and self._nonempty(metric.get("name"))
                and self._nonempty(metric.get("unit"))
                and self._finite(metric.get("value"))
                and self._nonnegative_finite(metric.get("uncertainty_k2"))
            )

            add_check(
                "required_fields",
                "Required inspection and measurement fields are complete.",
                "pass" if required_fields_present else "fail",
            )

            chronological = False

            if linked and inspection_request is not None:
                performed_at = record.get("performed_at_t_sim_s")
                requested_at = inspection_request.get("t_requested_sim_s")

                chronological = (
                    self._nonnegative_finite(performed_at)
                    and self._nonnegative_finite(requested_at)
                    and performed_at >= requested_at
                )

            add_check(
                "chronology",
                "Inspection was performed no earlier than its request.",
                (
                    "pass"
                    if chronological
                    else "fail"
                    if inspection_request is not None
                    else "unknown"
                ),
                request_ids,
            )

            approval = (
                inspection_request.get("human_approval", {})
                if inspection_request is not None
                else {}
            )
            approval_status = approval.get("status")

            add_check(
                "human_approval",
                "The originating inspection request was approved.",
                (
                    "pass"
                    if approval_status == "APPROVED"
                    else "fail"
                    if approval_status == "REJECTED"
                    else "unknown"
                ),
                request_ids,
            )

            metric_name = metric.get("name") if isinstance(metric, dict) else None
            metric_unit = metric.get("unit") if isinstance(metric, dict) else None

            expected_outputs = action.get("outputs", []) if action is not None else []

            matching_outputs = [
                output for output in expected_outputs if output.get("name") == metric_name
            ]

            if action is None or not self._nonempty(metric_name):
                unit_outcome = "unknown"
            elif not matching_outputs:
                unit_outcome = "fail"
            elif not self._nonempty(metric_unit):
                unit_outcome = "fail"
            elif any(output.get("unit") == metric_unit for output in matching_outputs):
                unit_outcome = "pass"
            else:
                unit_outcome = "fail"

            catalog_ids = sorted(catalog_evidence_ids.intersection(registered_ids))

            if unit_outcome == "pass" and not catalog_ids:
                unit_outcome = "unknown"

            add_check(
                "measurement_unit",
                "Measurement name and unit match the supplied action catalog.",
                unit_outcome,
                catalog_ids,
            )

            uncertainty_outcome = "unknown"

            if isinstance(metric, dict):
                uncertainty_outcome = (
                    "pass" if self._nonnegative_finite(metric.get("uncertainty_k2")) else "fail"
                )

            add_check(
                "measurement_uncertainty",
                "Measurement uncertainty is finite and nonnegative.",
                uncertainty_outcome,
            )

            coverage_outcome, coverage_ids = self._coverage_outcome(
                inputs["process_coverage"],
                record,
                registered_ids,
                inspection_request,
            )

            add_check(
                "process_coverage",
                "The supplied process coverage supports this inspection.",
                coverage_outcome,
                coverage_ids,
            )

            validation_status = record.get("validation_status")

            add_check(
                "validation_status",
                "Inspection passed its recorded quality assurance.",
                (
                    "pass"
                    if validation_status == "PASSED_QA"
                    else "fail"
                    if validation_status in {"FLAGGED_INCONSISTENT", "RETEST_REQUIRED"}
                    else "unknown"
                ),
            )

            source_quality = (
                "pass"
                if evidence_status == "valid" and source_ids
                else "fail"
                if evidence_status in {"missing", "contradictory", "low_confidence"}
                else "unknown"
            )

            add_check(
                "source_quality",
                "Inspection source quality is supported by registered evidence.",
                source_quality,
                source_ids,
            )

            scope_supported = self._scope_supported(
                action,
                metric,
                unit_outcome,
                coverage_outcome,
            )

            outcomes = [check["outcome"] for check in checks]

            if scope_supported is False or "fail" in outcomes:
                measurement_usable: bool | None = False
            elif scope_supported is True and all(outcome == "pass" for outcome in outcomes):
                measurement_usable = True
            else:
                measurement_usable = None

            record_checks.append(
                {
                    "result_id": result_id,
                    "checks": checks,
                    "measurement_usable": measurement_usable,
                    "scope_supported": scope_supported,
                    "equipment_condition_confirmed": False,
                    "evidence_ids": source_ids,
                }
            )

            consumed_ids.update(source_ids)
            consumed_ids.update(coverage_ids)

            if unit_outcome != "unknown":
                consumed_ids.update(catalog_ids)

            if measurement_usable is False or validation_status == "RETEST_REQUIRED":
                retest_result_ids.append(result_id)

            if measurement_usable is not True:
                issues.append(
                    make_issue(
                        "INSPECTION_QUALITY_UNRESOLVED",
                        f"Inspection {result_id} is not confirmed usable.",
                        source_ids,
                    )
                )

        observed_quality = self._observed_quality(
            inputs.get("observations"),
            registered_ids,
        )

        for row in observed_quality:
            consumed_ids.update(row["evidence_ids"])

        if not results:
            issues.append(
                make_issue(
                    "NO_INSPECTION_RESULTS",
                    "No performed inspection results were supplied.",
                )
            )
            limitations.append("Inspection quality cannot be established without results.")

        if any(row["measurement_usable"] is not True for row in record_checks):
            limitations.append("One or more inspection measurements remain unusable or unknown.")

        limitations.append("Inspection quality does not confirm physical equipment condition.")

        result: dict[str, Any] = {
            "record_checks": record_checks,
            "observed_quality": observed_quality,
            "retest_result_ids": sorted(set(retest_result_ids)),
        }

        response = build_response(
            request,
            status="degraded" if issues else "complete",
            result=result,
            consumed_evidence_ids=sorted(consumed_ids),
            implementation=implementation_block(
                "inspection_quality_documentation",
                "1.0.0",
            ),
            issues=issues,
            limitations=limitations,
        )

        check_response(request, response)
        return response

    @staticmethod
    def _nonempty(value: Any) -> bool:
        """Return whether a value contains nonblank text."""
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _finite(value: Any) -> bool:
        """Return whether a value is a finite numeric measurement."""
        return (
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        )

    @classmethod
    def _nonnegative_finite(cls, value: Any) -> bool:
        """Return whether a numeric measurement is finite and nonnegative."""
        return cls._finite(value) and value >= 0

    @staticmethod
    def _registered_evidence_ids(
        request: dict[str, Any],
    ) -> set[str]:
        """Collect identifiers from the supplied evidence registry."""
        evidence = request["evidence"]

        if isinstance(evidence, list):
            return {
                row["evidence_id"]
                for row in evidence
                if isinstance(row, dict) and isinstance(row.get("evidence_id"), str)
            }

        if isinstance(evidence, dict):
            return {
                row["evidence_id"]
                for row in evidence.get("items", [])
                if isinstance(row, dict) and isinstance(row.get("evidence_id"), str)
            }

        return set()

    @staticmethod
    def _source_evidence_ids(
        record: dict[str, Any],
        request: dict[str, Any],
        allowed_ids: set[str],
        registered_ids: set[str],
    ) -> list[str]:
        """Find registered evidence explicitly associated with a result."""
        evidence = request["evidence"]

        if isinstance(evidence, dict):
            entries = evidence.get("items", [])
        elif isinstance(evidence, list):
            entries = evidence
        else:
            entries = []

        result_id = record["result_id"]
        expected_ref = f"inspection_result:{result_id}"
        matched: set[str] = set()

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            evidence_id = entry.get("evidence_id")

            if evidence_id not in allowed_ids or evidence_id not in registered_ids:
                continue

            if entry.get("kind") == "inspection_result" and entry.get("source_ref") == expected_ref:
                matched.add(evidence_id)

        return sorted(matched)

    @classmethod
    def _coverage_outcome(
        cls,
        coverage: list[dict[str, Any]],
        record: dict[str, Any],
        registered_ids: set[str],
        inspection_request: dict[str, Any] | None = None,
    ) -> tuple[str, list[str]]:
        """Check asset and time coverage backed by registered evidence."""
        target = (
            inspection_request.get("target_asset")
            if inspection_request is not None
            else record.get("target_asset")
        )
        performed_at = record.get("performed_at_t_sim_s")

        if not cls._nonempty(target) or not cls._nonnegative_finite(performed_at):
            return "unknown", []

        matching = [
            row
            for row in coverage
            if row.get("target_asset") == target
            and cls._nonnegative_finite(row.get("start_s"))
            and cls._nonnegative_finite(row.get("end_s"))
            and row["start_s"] <= performed_at <= row["end_s"]
        ]

        if not matching:
            return "unknown", []

        supported_ids = sorted(
            {
                evidence_id
                for row in matching
                for evidence_id in row.get("evidence_ids", [])
                if evidence_id in registered_ids
            }
        )

        return ("pass", supported_ids) if supported_ids else ("unknown", [])

    @classmethod
    def _scope_supported(
        cls,
        action: dict[str, Any] | None,
        metric: Any,
        unit_outcome: str,
        coverage_outcome: str,
    ) -> bool | None:
        """Determine measurement scope without accepting unknown coverage."""
        if action is None:
            return None

        if not isinstance(metric, dict):
            return False

        if unit_outcome == "fail" or coverage_outcome == "fail":
            return False

        if unit_outcome == "pass" and coverage_outcome == "pass":
            return True

        return None

    @classmethod
    def _observed_quality(
        cls,
        observations: Any,
        registered_ids: set[str],
    ) -> list[dict[str, Any]]:
        """Summarize signal quality from supplied observation evidence."""
        if not isinstance(observations, dict):
            return []

        summary = observations.get("summary")

        if observations.get("representation") != "summary_v1" or not isinstance(summary, dict):
            return []

        evidence_ids = sorted(set(observations.get("evidence_ids", [])) & registered_ids)

        observed_quality: list[dict[str, Any]] = []

        for signal in summary.get("signals", []):
            if not isinstance(signal, dict) or not cls._nonempty(signal.get("tag_id")):
                continue

            missing = signal.get("missing_samples")
            non_good = signal.get("bad_quality_samples")

            if not isinstance(missing, int) or isinstance(missing, bool) or missing < 0:
                continue

            if not isinstance(non_good, int) or isinstance(non_good, bool) or non_good < 0:
                continue

            availability = signal.get("latest_availability")

            observed_quality.append(
                {
                    "tag_id": signal["tag_id"],
                    "missing_samples": missing,
                    "non_good_samples": non_good,
                    "latest_reading_missing": availability != "measured",
                    "evidence_ids": evidence_ids,
                }
            )

        return observed_quality
