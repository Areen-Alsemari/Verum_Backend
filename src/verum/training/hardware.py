"""Hardware evidence requests and tamper-evident document intake.

The request preserves the team's representative design separately from missing engineering data.
File hashes and scope records establish what was submitted, without certifying the hardware.
Engineering review and the existing physical release gates remain necessary after document intake.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from verum.contracts.paths import config_dir


def hardware_request() -> dict[str, Any]:
    """Return the current evidence request and its exact template hash."""
    raw = (config_dir() / "extensions" / "hardware_handoff_v1.json").read_bytes()
    result: dict[str, Any] = json.loads(raw)
    result["template_sha256"] = hashlib.sha256(raw).hexdigest()
    return result


def response_template() -> dict[str, Any]:
    """Create empty submissions, without treating known design choices as validated hardware."""
    request = hardware_request()
    return {
        "schema_version": "1.0.0",
        "source_template_sha256": request["template_sha256"],
        "packages": {
            p["id"]: {"configuration_identity": None, "applicability": None, "artifacts": []}
            for p in request["requested_packages"]
        },
    }


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _artifact(artifact: dict[str, Any], root: Path) -> str | None:
    name, expected = artifact.get("file"), artifact.get("sha256")
    if (
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(expected, str)
        or not re.fullmatch("[0-9a-f]{64}", expected)
    ):
        return "MISSING_ARTIFACT_BINDING"
    if Path(name).is_absolute():
        return "ARTIFACT_OUTSIDE_EVIDENCE_ROOT"
    target = (root / name).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        return "INVALID_ARTIFACT_PATH"
    with target.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if actual != expected:
        return "ARTIFACT_HASH_MISMATCH"
    if not _nonempty(artifact.get("scope")) or not _nonempty(artifact.get("locator")):
        return "MISSING_ARTIFACT_SCOPE_OR_LOCATOR"
    return None


def audit_hardware_response(response: dict[str, Any], evidence_root: Path) -> dict[str, Any]:
    """Check identities, applicability and file bindings; never assert physical qualification."""
    request = hardware_request()
    if response.get("schema_version") != "1.0.0":
        raise ValueError("unsupported hardware response version")
    if response.get("source_template_sha256") != request["template_sha256"]:
        raise ValueError("hardware response does not match the current request")
    expected = {p["id"] for p in request["requested_packages"]}
    submissions = response.get("packages", {})
    if not isinstance(submissions, dict) or set(submissions) - expected:
        raise ValueError("unknown hardware package")
    findings = []
    bound = []
    for requirement in request["requested_packages"]:
        ident = requirement["id"]
        record = submissions.get(ident, {})
        if not isinstance(record, dict):
            raise ValueError(f"invalid hardware package: {ident}")
        problems = []
        if not _nonempty(record.get("configuration_identity")):
            problems.append("MISSING_CONFIGURATION_IDENTITY")
        if not _nonempty(record.get("applicability")):
            problems.append("MISSING_APPLICABILITY")
        artifacts = record.get("artifacts", [])
        if not isinstance(artifacts, list) or not artifacts:
            problems.append("MISSING_ARTIFACTS")
        else:
            for artifact in artifacts:
                issue = (
                    _artifact(artifact, evidence_root)
                    if isinstance(artifact, dict)
                    else "INVALID_ARTIFACT"
                )
                if issue:
                    problems.append(issue)
        if not problems:
            bound.append(ident)
        findings.append(
            {
                "package": ident,
                "problems": sorted(set(problems)),
                "engineering_content_status": "not_reviewed",
                "required_contents": requirement["required_contents"],
            }
        )
    return {
        "schema_version": "1.0.0",
        "request_sha256": request["template_sha256"],
        "document_bindings_complete": len(bound) == len(expected),
        "bound_packages": bound,
        "findings": findings,
        "hardware_qualified": False,
        "training_ready": False,
        "next_step": "engineering review of configuration match, content and model validation",
        "limits": [
            "file_hashes_do_not_validate_engineering",
            "no_parameters_auto_adopted",
            "no_generation_or_release_gate_changed",
        ],
    }
