"""Checks that the wall-clock cutoff reaches the request context and changes nothing else."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from _runner_cases import inspection_result, snapshot, summary
from verum.agents.runner import Bundle, next_revision, run_analysis

UTC = "2026-01-01T00:20:00Z"
# Report identifiers and hashes are derived from content that includes the context, so they move
# with the time; everything else must stay equal.
_DIGEST = re.compile(r"[0-9a-f]{64}|(?<=-)[0-9a-f]{8}(?=\")")


def _run(**changes: Any) -> Bundle:
    return run_analysis(snapshot(**changes), "runtime", allow_placeholders=True)


def _without_utc(parts: dict[str, Any]) -> str:
    plain = copy.deepcopy(parts)
    for message in plain.values():
        if message:
            message["context"].pop("as_of_utc")
            for upstream in _nested_contexts(message):
                upstream.pop("as_of_utc")
    text = json.dumps(plain, sort_keys=True, default=str)
    return _DIGEST.sub("H", text)


def _nested_contexts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "as_of_utc" in value and "case_id" in value:
            found.append(value)
        for child in value.values():
            found += _nested_contexts(child)
    elif isinstance(value, list):
        for child in value:
            found += _nested_contexts(child)
    return found


def test_the_default_leaves_the_context_time_unset() -> None:
    """Without a value every request and report carries a null wall-clock cutoff.

    Independent: yes, because the contexts are read from the messages.
    """
    bundle = _run()
    contexts = [m["context"] for m in (*bundle.requests.values(), *bundle.reports.values()) if m]
    assert contexts and all(c["as_of_utc"] is None for c in contexts)
    assert bundle.context["as_of_utc"] is None


def test_a_set_value_reaches_every_context_and_nothing_else_changes() -> None:
    """With the value set, only the context time differs from the default run.

    Independent: yes, because the two runs are compared after removing that one field.
    """
    default, timed = _run(), _run(as_of_utc=UTC)
    assert timed.context["as_of_utc"] == UTC
    assert all(m["context"]["as_of_utc"] == UTC for m in timed.requests.values())
    assert _without_utc(default.requests) == _without_utc(timed.requests)
    assert _without_utc({k: v for k, v in default.reports.items() if v}) == _without_utc(
        {k: v for k, v in timed.reports.items() if v}
    )
    assert default.issues == timed.issues and default.notes == timed.notes


def test_a_new_revision_does_not_inherit_the_earlier_time() -> None:
    """The next revision carries the time it is given, or none.

    Independent: yes, because the field is read from the snapshots.
    """
    first = snapshot(as_of_utc=UTC)
    kwargs: dict[str, Any] = {
        "as_of_s": 500.0, "inspection_results": (inspection_result(),),
    }
    unset = next_revision(first, summary=copy.deepcopy(summary()), **kwargs)
    later = next_revision(
        first, summary=copy.deepcopy(summary()), as_of_utc="2026-01-01T00:25:00Z", **kwargs
    )
    assert unset.as_of_utc is None and later.as_of_utc == "2026-01-01T00:25:00Z"
