"""Generate the reduced mechanical and monthly vapour reference extension.

The output is a new dataset directory with a manifest and parent-linked split membership.
This command creates no diagnostic system and does not modify the source campaign.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from verum.vapour.campaign import generate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--legacy-sim-research", action="store_true",
                        help="Accept historical SIM laws for research; never training-ready")
    args = parser.parse_args()
    result = generate(args.base, args.output, args.n,
                      allow_legacy_simulation=args.legacy_sim_research)
    print(f"Generated {len(result['episodes'])} extension episodes")


if __name__ == "__main__":
    main()
