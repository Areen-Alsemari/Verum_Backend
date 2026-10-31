"""Command for the full campaign: run, resume, extend, stop cleanly and write the report.

The target is a number of slots, each ending in one completed episode or in a recorded gap. A run
continues from the records already in the folder, so the same command resumes an interrupted run,
and a larger target appends new slots without redoing the finished ones. A progress file is
updated every 20 slots. The run stops after the given number of hours, or on an interrupt after the
slots in flight have finished, and in every case writes the manifest and the report.

See D83, D87, D88 and D151.
"""

from __future__ import annotations

import argparse
import signal
import time
from pathlib import Path
from types import FrameType

from verum.campaign import report, runner
from verum.campaign.plan import CampaignConfig

SEED = 20261101
TARGET = 3000
REPORT = Path("local/campaign_report.md")


class Stopper:
    """A stop flag set by the first interrupt or by the deadline; a second interrupt aborts."""

    def __init__(self, hours: float | None) -> None:
        self.deadline = None if hours is None else time.monotonic() + 3600.0 * hours
        self.interrupted = False

    def __call__(self) -> bool:
        late = self.deadline is not None and time.monotonic() >= self.deadline
        return self.interrupted or late

    def handler(self, _signum: int, _frame: FrameType | None) -> None:
        if self.interrupted:
            raise KeyboardInterrupt
        self.interrupted = True
        print(
            "interrupt: no new slot starts; the slots in flight finish (interrupt again to abort)"
        )


def config_for(root: Path, seed: int, n: int) -> CampaignConfig:
    """The configuration of the folder with the new target; the seed of a started campaign stays."""
    if (root / runner.CONFIG_FILE).exists():
        stored = runner.load_config(root)
        if stored.seed != seed:
            raise SystemExit(f"{root} holds a campaign with seed {stored.seed}, not {seed}")
        return CampaignConfig(stored.seed, n, stored.block, stored.duration_s)
    return CampaignConfig(seed, n)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/campaign"))
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--n", type=int, default=TARGET, help="target number of slots")
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--stop-after-hours", type=float, default=None)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    config = config_for(args.root, args.seed, args.n)
    stop = Stopper(args.stop_after_hours)
    signal.signal(signal.SIGINT, stop.handler)
    manifest = runner.run_campaign(config, args.root, args.workers, stop=stop)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report.build(config, args.root), encoding="utf-8")
    done = sum(e["status"] == "completed" for e in manifest["episodes"])
    print(f"{len(manifest['episodes'])}/{config.n} slots finished, {done} completed")
    print(f"report: {args.report}")
    if stop():
        print("stopped before the target; run the same command to continue")


if __name__ == "__main__":
    main()
