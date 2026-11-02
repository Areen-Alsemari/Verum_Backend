"""The supported project boundary for reference datasets and supervised targets.

Scope is a versioned contract rather than an inference from a visibility label or folder name.
Unknown mechanisms remain unknown; scope selection does not qualify physical field behaviour.
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from verum.contracts.paths import config_dir


@cache
def project_scope() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(
        (config_dir() / "extensions/project_scope_v1.json").read_text()
    )
    return value


def supported_fault(fault: dict[str, Any]) -> bool:
    scope = project_scope()
    return (
        fault["fault_type"] in scope["supported_fault_types"]
        and fault["subtype"] in scope["supported_mechanisms"]
    )
