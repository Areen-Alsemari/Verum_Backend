"""Training-data qualification and privileged truth readers.

Research verification alone never qualifies a dataset for diagnostic training.
"""

from verum.training.readiness import TrainingNotReady, assert_training_ready, audit_dataset
from verum.training.truth import load_episode_truth

__all__ = ["TrainingNotReady", "assert_training_ready", "audit_dataset", "load_episode_truth"]
