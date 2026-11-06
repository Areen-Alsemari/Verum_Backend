"""Run the eight roles on one snapshot in manifest order, tolerating any agent failure.

A failing agent becomes a null report and a structured issue. Nothing is added to the evidence
registry for it, no result is invented, and the run continues with the next role.
"""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

import jsonschema

from verum.agents.common import build_request, check_request, check_response
from verum.agents.common.stub import STUB_CODE, StubAgent
from verum.agents.runner.builders import BUILDERS, Reports
from verum.agents.runner.bundle import (
    PLACEHOLDER_CODE,
    Bundle,
    BundleError,
    VerifiedBundle,
    check_exchange,
    check_placeholders,
    check_same_snapshot,
    verify_bundle,
)
from verum.agents.runner.discovery import load_agent
from verum.agents.runner.prepare import Prepared, prepare
from verum.agents.runner.snapshot import Snapshot
from verum.agents.runner.wiring import workflow_stages
from verum.contracts.agent_interfaces import Agent

SHORT = 300


def _issue(role: str, code: str, message: str) -> dict[str, str]:
    return {"role": role, "code": code, "message": message[:SHORT]}


def _call(agent: Agent, request: dict[str, Any], timeout_s: float | None) -> Any:
    if timeout_s is None:
        return agent.run(request)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(agent.run, request).result(timeout=timeout_s)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _answer(
    role: str, request: dict[str, Any], agents: Mapping[str, Agent], timeout_s: float | None
) -> tuple[dict[str, Any] | None, dict[str, str] | None, bool]:
    """Return the validated response or an issue, and whether a placeholder served the role."""
    placeholder = False
    try:
        agent = agents[role] if role in agents else load_agent(role)
        placeholder = isinstance(agent, StubAgent)
        response = _call(agent, request, timeout_s)
    except FutureTimeout:
        return None, _issue(role, "AGENT_TIMEOUT", f"no answer within {timeout_s} s"), placeholder
    except Exception as error:  # an agent may fail in any way; the run must go on
        return None, _issue(role, "AGENT_ERROR", f"{type(error).__name__}: {error}"), placeholder
    if not isinstance(response, dict):
        issue = _issue(role, "AGENT_INVALID_RESPONSE", "the response is not an object")
        return None, issue, placeholder
    try:
        check_response(request, response)
        check_same_snapshot(request["context"], response["context"], f"{role} response")
        check_exchange(request, response)
    except (ValueError, jsonschema.ValidationError) as error:
        return None, _issue(role, "AGENT_INVALID_RESPONSE", str(error)), placeholder
    marked = any(issue["code"] == STUB_CODE for issue in response["issues"])
    return response, None, placeholder or marked


def _run_role(
    role: str, prep: Prepared, bundle: Bundle, agents: Mapping[str, Agent], timeout_s: float | None
) -> None:
    reports: Reports = bundle.reports
    bundle.reports[role] = None
    try:
        inputs = BUILDERS[role](prep, {key: reports.get(key) for key in BUILDERS})
        request = build_request(
            role, f"{prep.context['analysis_id']}-{role}", prep.registry, inputs
        )
        check_request(request)
    except (ValueError, TypeError, jsonschema.ValidationError) as error:
        bundle.issues.append(_issue(role, "REQUEST_INVALID", str(error)))
        return
    bundle.requests[role] = request
    response, problem, placeholder = _answer(role, request, agents, timeout_s)
    if placeholder:
        bundle.notes.append({
            "role": role, "code": PLACEHOLDER_CODE,
            "message": "A placeholder agent served this role, so its report carries no role logic.",
        })
    if problem is not None or response is None:
        bundle.issues.append(problem or _issue(role, "AGENT_ERROR", "no response"))
        return
    bundle.reports[role] = prep.registry.add_report(response)


def run_analysis(
    snapshot: Snapshot,
    mode: str,
    *,
    agents: Mapping[str, Agent] | None = None,
    timeout_s: float | None = None,
    allow_placeholders: bool = True,
    previous: VerifiedBundle | None = None,
) -> Bundle:
    """Run all roles on a snapshot and return the bundle of requests, reports and issues.

    Agents are found by convention unless supplied. A previous verified bundle makes the run check
    that this one is a genuine new revision; earlier reports are never carried into this run. Each
    role served by a placeholder gets a note; with allow_placeholders false the run is rejected.
    """
    prep = prepare(snapshot, mode)
    bundle = Bundle(context=prep.context, registry=prep.registry, notes=prep.notes)
    for stage in workflow_stages():
        for role in stage:
            _run_role(role, prep, bundle, agents or {}, timeout_s)
    if not allow_placeholders:
        check_placeholders(bundle)
    if previous is not None:
        try:
            verify_bundle(bundle, previous)
        except BundleError as error:
            raise BundleError(f"not a valid next revision: {error}") from error
    return bundle
