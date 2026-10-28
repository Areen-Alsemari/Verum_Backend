"""Release and eligibility gates.

Source: ``dataset_release_policy.json``;
``revised/02_hydraulic_model.md`` section 8 (dataset eligibility rules).
"""

from verum.gates.release import ReleaseNotAllowed, ReleaseTier, assert_release_allowed

__all__ = ["ReleaseNotAllowed", "ReleaseTier", "assert_release_allowed"]
