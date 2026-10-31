"""The full-run command: progress file, stop, resume, extension, deadline and interrupt.

The runs use a stub slot that writes two small files, so they take seconds. The real episodes of the
report are in the campaign tests.

See D87 and D151.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from verum.campaign import runner
from verum.campaign.plan import Block, CampaignConfig
from verum.contracts.paths import repo_root

BLOCK = Block(
    size=40, healthy=8, single=22, pair=6, branched=4, latent=1, switch=3, stress=3, audit=4
)
CONFIG = CampaignConfig(13, 80, BLOCK)


def load_tool() -> ModuleType:
    path = repo_root() / "tools" / "campaign_run.py"
    spec = importlib.util.spec_from_file_location("campaign_run_tool", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stub(config: CampaignConfig, index: int, root: Path) -> dict[str, Any]:
    record = runner.slot_record(config, runner.context(config).plan[index])
    attempts = [
        {"attempt": 0, "episode_index": index * 5, "status": "rejected", "gate": "SAMPLING"}
    ]
    return {**record, "status": "gap", "attempts": attempts, "wall_s": 0.0}


def manifest_text(root: Path) -> str:
    return (runner.Layout(root).evaluator / "manifest.json").read_text(encoding="utf-8")


def test_the_progress_file_is_written_during_and_after_a_run(tmp_path: Path) -> None:
    """After a run of 80 slots the progress file holds the slots finished, the completed slots and
    gaps, the attempts, the rate and the estimate of the time left, and its log has one line for
    each update, every 20 slots and at the end.

    Independent: yes, because the counts are compared with the records on disk.
    """
    runner.run_campaign(CONFIG, tmp_path, workers=1, executor=stub)
    info = json.loads((tmp_path / runner.PROGRESS_FILE).read_text(encoding="utf-8"))
    records = runner.load_records(runner.Layout(tmp_path), list(range(80)))
    assert info["slots_finished"] == len(records) == 80 and info["target_slots"] == 80
    assert info["completed"] + info["gaps"] == 80 and info["attempts"] == 80
    assert {"elapsed_s", "rate_slots_per_hour", "estimated_remaining_s", "updated"} <= set(info)
    lines = (tmp_path / "progress.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 80 // runner.PROGRESS_EVERY + 1


def test_a_stopped_run_resumes_to_the_manifest_of_an_uninterrupted_run(tmp_path: Path) -> None:
    """A run told to stop once 30 records exist ends with fewer than 80 slots, writes its manifest,
    and the same command later finishes without redoing the first slots and gives the manifest of
    an uninterrupted run.

    Independent: yes, because the reference is a separate uninterrupted run.
    """
    whole, cut = tmp_path / "whole", tmp_path / "cut"
    runner.run_campaign(CONFIG, whole, workers=1, executor=stub)
    layout = runner.Layout(cut)

    def stop() -> bool:
        return len(list(layout.records.glob("*.json"))) >= 30

    partial = runner.run_campaign(CONFIG, cut, workers=1, executor=stub, stop=stop)
    assert 30 <= len(partial["episodes"]) < 80 and (layout.evaluator / "manifest.json").exists()
    stamp = (layout.records / "000010.json").stat().st_mtime_ns
    runner.run_campaign(CONFIG, cut, workers=1, executor=stub)
    assert (layout.records / "000010.json").stat().st_mtime_ns == stamp
    assert manifest_text(cut) == manifest_text(whole)


def test_a_stop_with_several_workers_lets_the_slots_in_flight_finish(tmp_path: Path) -> None:
    """With three workers and a stop after 20 records, every record on disk is complete and valid,
    and a later run reaches the manifest of an uninterrupted run.

    Independent: yes, because the reference is a separate uninterrupted run.
    """
    whole, cut = tmp_path / "whole", tmp_path / "cut"
    runner.run_campaign(CONFIG, whole, workers=1, executor=stub)
    layout = runner.Layout(cut)

    def stop() -> bool:
        return len(list(layout.records.glob("*.json"))) >= 20

    runner.run_campaign(CONFIG, cut, workers=3, executor=stub, stop=stop)
    files = sorted(layout.records.glob("*.json"))
    assert 20 <= len(files) < 80
    assert all(runner.record_valid(layout, int(p.stem)) for p in files)
    runner.run_campaign(CONFIG, cut, workers=3, executor=stub)
    assert manifest_text(cut) == manifest_text(whole)


def test_the_stopper_follows_the_deadline_and_the_interrupt() -> None:
    """A deadline of zero hours stops at once, none never stops, the first interrupt sets the flag
    and the second raises.

    Independent: yes, because each case is a direct reading of the rule.
    """
    tool = load_tool()
    assert tool.Stopper(0.0)() is True and tool.Stopper(None)() is False
    assert tool.Stopper(1.0)() is False
    stopper = tool.Stopper(None)
    stopper.handler(2, None)
    assert stopper() is True
    with pytest.raises(KeyboardInterrupt):
        stopper.handler(2, None)


def test_the_command_keeps_the_seed_of_a_started_campaign_and_extends_its_target(
    tmp_path: Path,
) -> None:
    """The configuration for a folder that holds a campaign keeps its seed and block and takes the
    new target; another seed is refused.

    Independent: yes, because the stored file and the new arguments are compared directly.
    """
    tool = load_tool()
    runner.run_campaign(CONFIG, tmp_path, workers=1, executor=stub)
    longer = tool.config_for(tmp_path, 13, 160)
    assert (longer.seed, longer.n, longer.block) == (13, 160, BLOCK)
    with pytest.raises(SystemExit):
        tool.config_for(tmp_path, 14, 160)
    assert tool.config_for(tmp_path / "new", 20261101, 3000) == CampaignConfig(20261101, 3000)
