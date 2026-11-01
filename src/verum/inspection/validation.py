"""Checks that a request must pass before it enters the workflow.

The closed schema of the request is checked first, then the rules of the catalog: the asset exists,
the action is allowed for the kind of the asset, the reported information gain does not exceed the
base-2 logarithm of the number of distinct hypotheses, the request is not dated in the future, and
its identifier is new. An agent cannot set the approval: a request enters as pending.

See D100, D101 and D106.
"""

from __future__ import annotations

import math
from collections.abc import Collection
from typing import Any

from verum.contracts import ContractError, validate
from verum.inspection.assets import Assets
from verum.inspection.catalog import Catalog

TOLERANCE_BITS = 1e-9


class RequestError(ValueError):
    """A request that the interface refuses, with a plain code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def validate_request(
    request: dict[str, Any], catalog: Catalog, assets: Assets, known_ids: Collection[str],
    as_of_s: float,
) -> None:  # fmt: skip
    """Raise ``RequestError`` unless the request may enter the workflow."""
    try:
        validate("inspection_request", request)
    except ContractError as exc:
        raise RequestError("SCHEMA", str(exc)) from exc
    if request["human_approval"] != {"status": "PENDING"}:
        raise RequestError("APPROVAL_SET_BY_AGENT", "a request must enter as pending")
    if request["request_id"] in known_ids:
        raise RequestError("DUPLICATE_REQUEST_ID", request["request_id"])
    if request["t_requested_sim_s"] > as_of_s:
        raise RequestError("REQUEST_IN_THE_FUTURE", f"{request['t_requested_sim_s']} > {as_of_s}")
    kind = assets.kind(request["target_asset"])
    if kind is None:
        raise RequestError("UNKNOWN_ASSET", request["target_asset"])
    if catalog.action(request["action_id"]).target_kind != kind:
        raise RequestError("ACTION_NOT_ALLOWED_FOR_ASSET", f"{request['action_id']} on a {kind}")
    hypotheses = set(request["justification"]["competing_hypotheses"])
    if len(hypotheses) < 2:
        raise RequestError("TOO_FEW_DISTINCT_HYPOTHESES", "at least two distinct hypotheses")
    bound = math.log2(len(hypotheses))
    reported = request["justification"]["agent_reported_information_gain_bits"]
    if reported > bound + TOLERANCE_BITS:
        raise RequestError("INFORMATION_GAIN_EXCEEDS_BOUND", f"{reported} > {bound:.4f} bits")
