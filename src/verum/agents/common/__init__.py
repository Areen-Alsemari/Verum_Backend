"""Helpers shared by all agent roles: identifiers, envelopes, registries and data readers.

Role packages import these helpers and the contract package, and nothing else from the repository.
The helpers carry no role logic and no physical value.
"""

from verum.agents.common.context import file_sha256, make_context, make_context_from_reference
from verum.agents.common.envelope import (
    build_request,
    build_response,
    implementation_block,
    make_issue,
)
from verum.agents.common.ids import analysis_id, report_id
from verum.agents.common.loader import EpisodeRef, RoleRecord, episode_lookup, iter_role_records
from verum.agents.common.numbers import stable_hash, to_plain
from verum.agents.common.observations import TAG_ORDER, attach_summary, summary_representation
from verum.agents.common.registry import EvidenceRegistry
from verum.agents.common.roles import ROLES
from verum.agents.common.stub import StubAgent
from verum.agents.common.validation import check_request, check_response

__all__ = [
    "ROLES",
    "TAG_ORDER",
    "EpisodeRef",
    "EvidenceRegistry",
    "RoleRecord",
    "StubAgent",
    "analysis_id",
    "attach_summary",
    "build_request",
    "build_response",
    "check_request",
    "check_response",
    "episode_lookup",
    "file_sha256",
    "implementation_block",
    "iter_role_records",
    "make_context",
    "make_context_from_reference",
    "make_issue",
    "report_id",
    "stable_hash",
    "summary_representation",
    "to_plain",
]
