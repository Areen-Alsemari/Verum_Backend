"""Run the placeholder agent of every role on its example request and validate the answer.

The script finds each agent with the same discovery function the runner uses, prints one summary
line and exits with status 1 if any role fails. It is a quick check that the role packages are wired
to the message contract.
"""

from __future__ import annotations

import json
import sys

from verum.agents.common import ROLES, check_request, check_response
from verum.agents.runner import load_agent
from verum.contracts.agent_interfaces import contract_directory


def check_roles() -> list[str]:
    """Run the discovered agent of every role on its example request; return the failures."""
    failures: list[str] = []
    for role in ROLES:
        path = contract_directory() / "examples" / f"{role}.request.json"
        request = json.loads(path.read_text(encoding="utf-8"))
        try:
            check_request(request)
            check_response(request, load_agent(role).run(request))
        except Exception as error:
            failures.append(f"{role}: {error}")
    return failures


def main() -> int:
    failures = check_roles()
    print(json.dumps({"roles": len(ROLES), "failures": failures, "passed": not failures}))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
