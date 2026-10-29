"""Sensor chain: from true quantities to agent-visible observations.

Inputs: an episode's truth (read only through ``verum.sensors.adapter``) and the sensor
configuration. Outputs: observation rows and hidden audit rows.
Key assumptions:
    * Only ``adapter`` imports from ``verum.truth``; the chain itself works on arrays (a
      static test enforces this).
    * The order of the chain is fixed (``chain.py``).

Source: ``docs/design_decisions.md`` D27 to D33; ``docs/observation_chain.md``.
"""

from verum.sensors.adapter import observe_episode
from verum.sensors.specs import SensorConfig, TagSpec, load_sensor_config

__all__ = ["SensorConfig", "TagSpec", "load_sensor_config", "observe_episode"]
