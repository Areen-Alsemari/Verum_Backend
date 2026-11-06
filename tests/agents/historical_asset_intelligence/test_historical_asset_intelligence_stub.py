"""Placeholder checks for the historical asset intelligence agent.

The placeholder must accept the role's example request and return a response the contract accepts.
"""

from __future__ import annotations

from _agent_stubs import assert_stub_answers_example
from verum.agents.historical_asset_intelligence import HistoricalAssetIntelligenceAgent


def test_historical_asset_intelligence_stub_passes_the_contract_on_its_example() -> None:
    """The placeholder answers its example request with a valid response marked as a stub.

    Independent: yes, because the contract validators are separate from the placeholder.
    """
    assert_stub_answers_example(HistoricalAssetIntelligenceAgent(), "historical_asset_intelligence")
