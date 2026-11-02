"""Export the hardware request or check a supplier-response evidence folder.

The check binds documents to the current request without approving physics or changing data.
Missing identities, applicability, locators or source files remain explicit findings.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verum.training.hardware import audit_hardware_response, hardware_request, response_template


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--template", type=Path)
    parser.add_argument("--response", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    for path, value in ((args.request, hardware_request()), (args.template, response_template())):
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(value, indent=2, allow_nan=False) + "\n")
    if args.response:
        if args.evidence_root is None or args.report is None:
            parser.error("a response requires an evidence root and report path")
        result = audit_hardware_response(json.loads(args.response.read_text()), args.evidence_root)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
        print(
            "Document bindings complete."
            if result["document_bindings_complete"]
            else "Hardware evidence remains incomplete; see the report."
        )
        raise SystemExit(0 if result["document_bindings_complete"] else 2)
    if not (args.request or args.template):
        parser.error("choose request/template export or response audit")


if __name__ == "__main__":
    main()
