"""Evaluation side: utilities that read hidden records next to the agent-visible data.

Nothing here is reachable from ``verum.api``; a static test checks that the gateway imports
nothing from this package.

Source: ``CONTRIBUTING.md`` (data exposure); ``docs/design_decisions.md`` D25.
"""

from verum.evaluation.windows import attach_window_ids, load_windows

__all__ = ["attach_window_ids", "load_windows"]
