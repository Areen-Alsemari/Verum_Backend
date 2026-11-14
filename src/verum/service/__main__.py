"""Start the run service: python -m verum.service with a replay folder, a release, or both.

Inputs: the command line. Outputs: a server on a local port that prints its address.
Assumptions: it binds to the loopback address unless told otherwise; the live mode installs the
audit hook that confines the process to the validation split of the release.
Source: the service API document.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from verum.service.app import DEFAULT_ORIGINS, ServiceConfig, make_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verum.service", description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--replay-dir", type=Path, help="folder with the stored sample bundles")
    parser.add_argument("--release", type=Path, help="release folder for live runs (validation)")
    parser.add_argument("--origin", action="append", help="allowed browser origin (repeatable)")
    args = parser.parse_args(argv)
    config = ServiceConfig(args.replay_dir, args.release, tuple(args.origin or DEFAULT_ORIGINS))
    server = make_server(config, args.host, args.port)
    host, port = server.server_address[0], server.server_address[1]
    print(f"verum service listening on http://{host!s}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
