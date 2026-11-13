"""Where the windows of a run come from: stored bundles of the sample, or the live runner.

Inputs: a folder of stored bundles for replay, or a release folder for live runs. Outputs: for one
episode, its windows in time order as records (context, requests, reports, issues, notes), the
verified bundle that the final report is built from, and the simulation truth of the window.
Assumptions: the truth is returned separately and is read from the stored window or the role
view; it never enters a record. A live run is made through the real runner with its own
assessment log, on a validation episode, with the audit hook installed. Replay reads no data.
Source: the runner run script that stored the sample, and the runner package.
"""

from __future__ import annotations

import gzip
import json
import threading
from collections import defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verum.agents.common import episode_lookup, file_sha256, iter_role_records
from verum.agents.runner import AssessmentLog, Snapshot, run_analysis, verify_bundle
from verum.agents.runner.bundle import VerifiedBundle
from verum.contracts.agent_interfaces import Agent
from verum.service import guard

WINDOW_STEP_S = 300.0  # the observation window of the sample, which is also its cadence
ROLE = "diagnostic_reasoning"
VALIDATION, TRAIN = "validation", "train"


class UnknownEpisode(ValueError):
    """The requested episode is not in the stored sample or the validation split."""


@dataclass
class WindowData:
    """One analysed window: its record, the verified bundle for the report, and the truth."""

    position: int
    as_of_s: float
    record: dict[str, Any]
    verified: VerifiedBundle | None
    truth: dict[str, Any] | None


def truth_of_labels(
    fault: bool, assets: list[str], types: list[str], mechs: list[str]
) -> dict[str, Any]:
    """The simulation truth of a window in the one shape the truth endpoint returns."""
    return {"fault": fault, "asset_ids": sorted(assets), "fault_types": sorted(types),
            "mechanisms": sorted(mechs)}  # fmt: skip


def _read_gz(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        loaded: dict[str, Any] = json.load(handle)
    return loaded


class ReplaySource:
    """The stored bundles of the sample, played back in the order of one episode."""

    mode = "replay"

    def __init__(self, directory: Path, episode_id: str | None = None) -> None:
        self.directory = directory
        entries = self.entries(directory)
        wanted = episode_id or self.default_episode(entries)
        self.rows = sorted(
            (e for e in entries if e["episode_id"] == wanted), key=lambda e: e["position"]
        )
        if not self.rows:
            raise UnknownEpisode(f"no stored episode {wanted!r}")
        self.episode_id = wanted
        self.split = self.rows[0]["split"]

    @staticmethod
    def entries(directory: Path) -> list[dict[str, Any]]:
        """The windows of the stored sample with the fields a replay may use, without labels."""
        sample = json.loads((directory / "sample.json").read_text(encoding="utf-8"))
        keys = ("window_id", "episode_id", "position", "cutoff_s")
        return [{**{k: row[k] for k in keys}, "split": split}
                for section, split in (("validation", VALIDATION), ("train_sanity", TRAIN))
                for row in sample.get(section, [])]  # fmt: skip

    @staticmethod
    def default_episode(entries: list[dict[str, Any]]) -> str:
        counts: dict[str, int] = defaultdict(int)
        for entry in entries:
            if entry["split"] == VALIDATION:
                counts[entry["episode_id"]] += 1
        return max(sorted(counts), key=lambda e: counts[e])

    @classmethod
    def episodes(cls, directory: Path) -> list[dict[str, Any]]:
        """Every stored episode with its split and number of windows."""
        found: dict[tuple[str, str], int] = defaultdict(int)
        for entry in cls.entries(directory):
            found[(entry["episode_id"], entry["split"])] += 1
        return [{"episode_id": e, "split": s, "windows": n} for (e, s), n in sorted(found.items())]

    def windows(self) -> Iterator[WindowData]:
        for row in self.rows:
            stored = _read_gz(self.directory / "bundles" / f"{row['window_id']}.json.gz")
            record = {k: stored[k] for k in ("context", "requests", "reports", "issues", "notes")}
            window = stored["window"]
            truth = truth_of_labels(window["fault"], window["assets"], window["fault_types"],
                                    window["mechanisms"])  # fmt: skip
            verified = VerifiedBundle(
                context=record["context"],
                responses={r: v for r, v in record["reports"].items() if v is not None},
                evidence=stored["evidence"], issues=tuple(record["issues"]),
            )
            yield WindowData(row["position"], float(row["cutoff_s"]), record, verified,
                             truth if self.split == VALIDATION else None)  # fmt: skip


@dataclass(frozen=True)
class LiveWindow:
    """What a live run needs of one validation window: its summary, never its label."""

    example_id: str
    position: int
    cutoff_s: float
    summary: dict[str, Any]


class LiveData:
    """The validation windows of a release, read once through the audit hook."""

    def __init__(self, release: Path) -> None:
        self.release = release
        self._lock = threading.Lock()
        self._episodes: dict[str, list[LiveWindow]] | None = None
        self._truth: dict[str, dict[str, Any]] = {}
        self.reference: dict[str, Any] = {}
        self.reference_sha = ""

    def load(self) -> dict[str, list[LiveWindow]]:
        with self._lock:
            if self._episodes is None:
                self._episodes = self._read()
            return self._episodes

    def _read(self) -> dict[str, list[LiveWindow]]:
        guard.confine(self.release)
        path = self.release / "knowledge" / "public_reference.json"
        self.reference = json.loads(path.read_text(encoding="utf-8"))
        self.reference_sha = file_sha256(path)
        lineage = episode_lookup(self.release, VALIDATION)
        episodes: dict[str, list[LiveWindow]] = defaultdict(list)
        for record in iter_role_records(self.release, ROLE, VALIDATION):
            if not record.target["supervised_loss_mask"]:
                continue  # windows the sample leaves out; the mask is read, never forwarded
            ref = lineage[record.example_id]
            position = int(round(ref.source_cutoff_s / WINDOW_STEP_S))
            episodes[ref.episode_id].append(LiveWindow(
                record.example_id, position, ref.source_cutoff_s, record.input["observations"]
            ))
            self._truth[record.example_id] = self._labels(record.target)
        return {e: sorted(w, key=lambda x: x.position) for e, w in episodes.items()}

    @staticmethod
    def _labels(target: dict[str, Any]) -> dict[str, Any]:
        parts = target["injected_components"] or []
        return truth_of_labels(
            bool(parts), [c["asset_id"] for c in parts], [c["fault_type"] for c in parts],
            [c["mechanism"] for c in parts],
        )

    def truth(self, example_id: str) -> dict[str, Any]:
        return self._truth[example_id]

    def episode_list(self) -> list[dict[str, Any]]:
        return [{"episode_id": e, "split": VALIDATION, "windows": len(w)}
                for e, w in sorted(self.load().items())]  # fmt: skip


class LiveSource:
    """Runs the real runner window by window on a validation episode, with its own state."""

    mode = "live"
    split = VALIDATION

    def __init__(
        self, data: LiveData, case_id: str, episode_id: str | None = None, *,
        agents: Mapping[str, Agent] | None = None, allow_placeholders: bool = False,
    ) -> None:
        self.agents, self.allow_placeholders = agents, allow_placeholders  # tests supply both
        episodes = data.load()
        wanted = episode_id or sorted(episodes, key=lambda e: (-len(episodes[e]), e))[0]
        if wanted not in episodes:
            raise UnknownEpisode(f"no validation episode {wanted!r}")
        self.data, self.case_id, self.episode_id = data, case_id, wanted
        self.rows = episodes[wanted]

    def windows(self) -> Iterator[WindowData]:
        log, last = AssessmentLog(), None  # the assessment log of this run alone
        for row in self.rows:
            log = self._pad(log, last, row.position)
            snapshot = Snapshot(
                case_id=self.case_id, revision=0, as_of_s=row.cutoff_s, summary=row.summary,
                reference=self.data.reference, reference_snapshot_sha256=self.data.reference_sha,
            )
            bundle = run_analysis(
                snapshot, "runtime", agents=self.agents, allow_placeholders=self.allow_placeholders,
                recent=log, episode_id=self.episode_id, window_index=row.position,
            )
            verified = verify_bundle(bundle, allow_placeholders=self.allow_placeholders)
            log, last = bundle.assessments, row.position
            record = {"context": bundle.context, "requests": bundle.requests,
                      "reports": bundle.reports, "issues": bundle.issues,
                      "notes": bundle.notes}  # fmt: skip
            yield WindowData(row.position, row.cutoff_s, record, verified,
                             self.data.truth(row.example_id))  # fmt: skip

    def _pad(self, log: AssessmentLog, last: int | None, position: int) -> AssessmentLog:
        """A window without an assessment for every skipped position, as the sample run does."""
        for skipped in range(position if last is None else last + 1, position):
            log = log.extended(self.case_id, skipped * WINDOW_STEP_S, None)
        return log
