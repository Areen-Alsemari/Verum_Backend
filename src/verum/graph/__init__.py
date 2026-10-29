"""Graph view of the terminal topology: connectivity, lineups and geometry.

Source: ``revised/05_simulation_validation_dataset.md`` section 13.3
(``graph/``: topology from the Member 1 table and its validators);
``revised/01_facility_tanks_topology.md`` sections 6.2 and 7.
"""

from verum.graph.geometry import (
    RouteGeometry,
    load_route_geometry,
    point_at,
    polyline_length,
)
from verum.graph.network import (
    DISTRIBUTION_BOUNDARY,
    RECEIPT_BOUNDARY,
    TANK_LINK,
    Lineup,
    Network,
)

__all__ = [
    "DISTRIBUTION_BOUNDARY",
    "RECEIPT_BOUNDARY",
    "TANK_LINK",
    "Lineup",
    "Network",
    "RouteGeometry",
    "load_route_geometry",
    "point_at",
    "polyline_length",
]
