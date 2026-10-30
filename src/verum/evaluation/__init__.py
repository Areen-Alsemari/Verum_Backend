"""Evaluation side: utilities that read hidden records next to the agent-visible data.

Nothing here is reachable from the gateway, and a static test checks that the gateway imports
nothing from this package.

See D25.
"""

from verum.evaluation.windows import attach_window_ids, load_windows

__all__ = ["attach_window_ids", "load_windows"]
