"""Command line for the campaign generator: run a campaign, verify it, and print its counts.

Run it with `pilot` for the 200-episode pilot, `run` for a campaign of a given size, `verify` to
rebuild a sample of episodes from their seeds and compare the hashes, and `summary` for the counts.
Episodes are written outside the repository, under the folder given by `--root`.

See D83 to D88.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from verum.campaign import runner
from verum.campaign.plan import CampaignConfig, Shares

PILOT_SEED = 20261101
PILOT = CampaignConfig(PILOT_SEED, 200, Shares(0.5, 0.4, 0.1))


def config_of(args: argparse.Namespace) -> CampaignConfig:
    if args.command == "pilot":
        return PILOT
    return CampaignConfig(args.seed, args.n)


def verify(config: CampaignConfig, root: Path, count: int) -> int:
    layout = runner.Layout(root)
    records = [
        r for r in runner.load_records(layout, list(range(config.n))) if r["status"] == "completed"
    ]
    sample = random.Random(config.seed).sample(records, min(count, len(records)))
    bad = 0
    for r in sample:
        stored = r["files"][f"agent_visible/episodes/{r['episode_id']}/{runner.OBSERVATIONS}"]
        again = runner.regenerate(config, r, layout.work)
        bad += int(stored != again)
        print(r["episode_id"], "match" if stored == again else "DIFFERENT", flush=True)
    return bad


def summary(config: CampaignConfig, root: Path) -> None:
    records = runner.load_records(runner.Layout(root), list(range(config.n)))
    print("status", dict(Counter(r["status"] for r in records)))
    print("split", dict(Counter(r["split"] for r in records if r["status"] == "completed")))
    print("subtype", dict(Counter(s for r in records for s in r["subtypes"])))
    reasons = Counter(
        r["rejection"].get("gate", "?") if r["status"] == "rejected" else r.get("reason", "")
        for r in records
        if r["status"] != "completed"
    )
    print("not completed", dict(reasons))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["pilot", "run", "verify", "summary"])
    parser.add_argument("--root", type=Path, default=Path("data/campaign"))
    parser.add_argument("--seed", type=int, default=PILOT_SEED)
    parser.add_argument("--n", type=int, default=6000)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--sample", type=int, default=20)
    args = parser.parse_args()
    config = config_of(args)
    if args.command in ("pilot", "run"):
        manifest = runner.run_campaign(config, args.root, args.workers)
        print(json.dumps(runner.accounting(runner.Layout(args.root), list(range(config.n)))))
        print(len(manifest["episodes"]), "records")
    elif args.command == "verify":
        raise SystemExit(verify(config, args.root, args.sample))
    else:
        summary(config, args.root)


if __name__ == "__main__":
    main()
