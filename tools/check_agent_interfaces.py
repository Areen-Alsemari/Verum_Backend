"""Check the eight versioned interface contracts and their connection examples.

The check validates messages and request/response pairing without loading models or simulations.
"""

from __future__ import annotations

import json

from verum.contracts.agent_interfaces import (
    contract_directory,
    validate_request,
    validate_response,
    validators,
)


def main() -> None:
    base = contract_directory()
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    checks = validators(base)
    for role in manifest["agents"]:
        request = json.loads((base / role["request_fixture"]).read_text(encoding="utf-8"))
        response = json.loads((base / role["response_fixture"]).read_text(encoding="utf-8"))
        validate_request(request, checks)
        validate_response(request, response, checks)
    print(json.dumps({"interfaces": len(checks), "examples": 2 * len(checks), "passed": True}))


if __name__ == "__main__":
    main()
