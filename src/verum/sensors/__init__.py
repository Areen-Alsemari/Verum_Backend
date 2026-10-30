"""Sensor chain: from true quantities to agent-visible observations.

The chain turns an episode's truth into observation rows and hidden audit rows. Only the adapter
reads the truth package, and the chain itself works on arrays. A static test enforces this, and the
order of the chain is fixed.

See D27 to D33.
"""

from verum.sensors.adapter import observe_episode
from verum.sensors.specs import SensorConfig, TagSpec, load_sensor_config

__all__ = ["SensorConfig", "TagSpec", "load_sensor_config", "observe_episode"]
