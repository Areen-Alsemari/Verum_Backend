"""Command line for the campaign generator: run the pilot, verify a campaign, and print its counts.

Run it with `pilot` for the 60-slot pilot of the second round, `verify` to rebuild a sample of
episodes from their seeds and compare the hashes, and `summary` for the counts. Episodes are written
outside the repository, under the folder given by `--root`. The full campaign has its own command.

See D83 to D88 and D151.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from verum.campaign import runner
from verum.campaign.plan import Block, CampaignConfig

PILOT_SEED = 20261102
PILOT = CampaignConfig(
    PILOT_SEED, 60, Block(size=60, healthy=20, single=20, pair=10, branched=10, latent=1, switch=5,
                          stress=5, audit=6)
)  # fmt: skip


def config_of(args: argparse.Namespace) -> CampaignConfig:
    """The pilot, or the stored configuration of an existing campaign."""
    return PILOT if args.command == "pilot" else runner.load_config(args.root)


def verify(config: CampaignConfig, root: Path, count: int, workers: int | None) -> int:
    results = runner.verify_sample(config, root, count, workers)
    for episode, ok in results:
        print(episode, "match" if ok else "DIFFERENT")
    return sum(1 for _, ok in results if not ok)


def summary(config: CampaignConfig, root: Path) -> None:
    records = runner.load_records(runner.Layout(root), list(range(config.n)))
    print("status", dict(Counter(r["status"] for r in records)))
    print("split", dict(Counter(r["split"] for r in records if r["status"] == "completed")))
    print("subtype", dict(Counter(s for r in records for s in r["subtypes"])))
    attempts = [a for r in records for a in r["attempts"]]
    print("attempts", len(attempts), dict(Counter(a["status"] for a in attempts)))
    reasons = Counter(
        a.get("gate", a.get("reason", a["status"])) for a in attempts if a["status"] != "completed"
    )
    print("not completed", dict(reasons))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["pilot", "verify", "summary"])
    parser.add_argument("--root", type=Path, default=Path("data/pilot2"))
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--sample", type=int, default=20)
    args = parser.parse_args()
    config = config_of(args)
    if args.command == "pilot":
        manifest = runner.run_campaign(config, args.root, args.workers)
        print(json.dumps(runner.accounting(runner.Layout(args.root), list(range(config.n)))))
        print(len(manifest["episodes"]), "records")
    elif args.command == "verify":
        raise SystemExit(verify(config, args.root, args.sample, args.workers))
    else:
        summary(config, args.root)


if __name__ == "__main__":
    main()
