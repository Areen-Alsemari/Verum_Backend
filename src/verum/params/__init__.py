"""Parameter model: values that carry status, evidence tag, unit and provenance.

The package exposes ``ParamValue`` and the ``UnresolvedParameter`` exception.
Source: ``revised/05_simulation_validation_dataset.md`` section 13.1.
"""

from verum.params.paramvalue import ParamValue, ParamValueError, UnresolvedParameter

__all__ = ["ParamValue", "ParamValueError", "UnresolvedParameter"]
