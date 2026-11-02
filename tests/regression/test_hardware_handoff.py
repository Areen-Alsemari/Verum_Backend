"""Hardware evidence bindings distinguish document intake from engineering qualification.

Tests use literal files and hashes and never certify synthetic or manufacturer hardware.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from verum.training.hardware import audit_hardware_response, hardware_request, response_template


def submitted(root: Path) -> dict[str, Any]:
    path = root / "evidence.txt"
    path.write_text("This is a test document, not engineering evidence.")
    response = response_template()
    for package in response["packages"].values():
        package.update(
            configuration_identity="literal-test-model",
            applicability="test only",
            artifacts=[
                {
                    "file": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "scope": "test only",
                    "locator": "line 1",
                }
            ],
        )
    return response


def test_empty_response_does_not_promote_team_design_to_qualified_hardware(tmp_path: Path) -> None:
    """Every initially empty package remains unresolved despite the existing M1 dimensions.

    Independent: yes, because an empty submission contains no engineering documents.
    """
    result = audit_hardware_response(response_template(), tmp_path)
    assert not result["document_bindings_complete"]
    assert len(result["findings"]) == len(hardware_request()["requested_packages"])
    assert not result["bound_packages"]
    assert not result["hardware_qualified"] and not result["training_ready"]


def test_binding_all_documents_still_requires_engineering_content_review(tmp_path: Path) -> None:
    """Hashes can bind a generic test file but cannot turn it into accepted hardware physics.

    Independent: yes, because the literal document explicitly contains no engineering evidence.
    """
    result = audit_hardware_response(submitted(tmp_path), tmp_path)
    assert result["document_bindings_complete"]
    assert not result["hardware_qualified"] and not result["training_ready"]
    assert all(r["engineering_content_status"] == "not_reviewed" for r in result["findings"])


@pytest.mark.parametrize("case", ["changed", "escape", "locator", "model", "scope"])
def test_tampered_or_unscoped_document_bindings_are_incomplete(tmp_path: Path, case: str) -> None:
    """A changed file, escaped path or missing evidence description leaves the package open.

    Independent: yes, because each fixture violates a file or metadata condition.
    """
    response = submitted(tmp_path)
    package = response["packages"]["venting"]
    artifact = package["artifacts"][0]
    if case == "changed":
        (tmp_path / "evidence.txt").write_text("changed")
    if case == "escape":
        artifact["file"] = "../evidence.txt"
    if case == "locator":
        artifact["locator"] = ""
    if case == "model":
        package["configuration_identity"] = None
    if case == "scope":
        package["applicability"] = None
    assert not audit_hardware_response(response, tmp_path)["document_bindings_complete"]


def test_wrong_request_and_unknown_packages_cannot_be_silently_adopted(tmp_path: Path) -> None:
    """An obsolete template hash and an unknown component package are refused.

    Independent: yes, because neither response names exactly the current evidence request.
    """
    response = response_template()
    response["source_template_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="current request"):
        audit_hardware_response(response, tmp_path)
    response = response_template()
    response["packages"]["unknown"] = {}
    with pytest.raises(ValueError, match="unknown hardware"):
        audit_hardware_response(response, tmp_path)
