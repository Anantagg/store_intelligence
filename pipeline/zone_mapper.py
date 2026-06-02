"""Zone mapper using Shapely polygon containment checks.

Maps detected person centroids to named store zones defined as polygons
in the zone configuration.
"""

import logging
from shapely.geometry import Point, Polygon

logger = logging.getLogger(__name__)


class ZoneMapper:
    """Maps (cx, cy) centroids to named zone polygons using Shapely."""

    def __init__(self, zones: dict):
        """
        Build Shapely Polygon objects for each named zone.

        Args:
            zones: Mapping of zone_name → list of [x, y] polygon vertices.
                   Example: {"entrance": [[0,0],[1920,0],[1920,216],[0,216]]}
        """
        self.zone_polygons: dict[str, Polygon] = {}
        for zone_name, coords in zones.items():
            poly = Polygon(coords)
            if not poly.is_valid:
                logger.warning("Zone '%s' has an invalid polygon — attempting buffer fix.", zone_name)
                poly = poly.buffer(0)
            self.zone_polygons[zone_name] = poly

        logger.info("ZoneMapper initialized with %d zones: %s",
                     len(self.zone_polygons), list(self.zone_polygons.keys()))

    def get_zone(self, centroid: list[float]) -> str | None:
        """
        Return the name of the first zone that contains the centroid.

        Args:
            centroid: [cx, cy] point coordinates.

        Returns:
            Zone name string, or None if the centroid is outside all zones.
        """
        point = Point(centroid[0], centroid[1])
        for zone_name, polygon in self.zone_polygons.items():
            if point.within(polygon) or polygon.touches(point):
                return zone_name
        return None

    def get_all_zones(self, centroid: list[float]) -> list[str]:
        """
        Return all zone names that contain the centroid.

        Args:
            centroid: [cx, cy] point coordinates.

        Returns:
            List of zone name strings (may be empty).
        """
        point = Point(centroid[0], centroid[1])
        matched = []
        for zone_name, polygon in self.zone_polygons.items():
            if point.within(polygon) or polygon.touches(point):
                matched.append(zone_name)
        return matched
