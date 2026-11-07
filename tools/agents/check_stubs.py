"""Run the placeholder agent of every role on its example request and validate the answer.

The script prints one summary line and exits with status 1 if any role fails. It is a quick check
that the role packages are wired to the message contract.
"""

from __future__ import annotations

import importlib
import json
import sys

from verum.agents.common import ROLES, check_request, check_response
from verum.contracts.agent_interfaces import contract_directory


def _agent_class(role: str) -> type:
    module = importlib.import_module(f"verum.agents.{role}")
    names = [name for name in module.__all__ if name.endswith("Agent")]
    cls: type = getattr(module, names[0])
    return cls


def main() -> int:
    failures: list[str] = []
    for role in ROLES:
        path = contract_directory() / "examples" / f"{role}.request.json"
        request = json.loads(path.read_text(encoding="utf-8"))
        try:
            check_request(request)
            check_response(request, _agent_class(role)().run(request))
        except Exception as error:
            failures.append(f"{role}: {error}")
    print(json.dumps({"roles": len(ROLES), "failures": failures, "passed": not failures}))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
