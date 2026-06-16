"""Dynamic venetian (Raffstore) slat-tracking geometry.

A venetian blind can hold a fixed shade *position* while continuously
re-angling its slats so that the direct beam stays blocked but as much diffuse
daylight as possible is let through. As the sun climbs, the slats may open up;
as it sinks toward the horizon they have to close down to keep cutting off the
beam.

The helpers here are pure (no Home Assistant dependency) so the geometry can be
unit-tested in isolation. The Home Assistant layer reads the sun elevation and
feeds the resulting tilt into the resolver.

Tilt convention follows Home Assistant covers: ``0`` = fully closed (slats
shut), ``100`` = fully open (slats horizontal).
"""

from __future__ import annotations

import math

#: Default elevation domain (degrees) the linear cut-off model spans when an
#: area declares no explicit elevation band.
DEFAULT_ELEVATION_LOW: float = 0.0
DEFAULT_ELEVATION_HIGH: float = 90.0

#: Default tilt band the elevation domain maps onto.
DEFAULT_TILT_LOW: int = 0
DEFAULT_TILT_HIGH: int = 100


def slat_tilt_for_elevation(
    elevation: float,
    *,
    elevation_low: float = DEFAULT_ELEVATION_LOW,
    elevation_high: float = DEFAULT_ELEVATION_HIGH,
    tilt_low: int = DEFAULT_TILT_LOW,
    tilt_high: int = DEFAULT_TILT_HIGH,
) -> int:
    """Return the cut-off slat tilt (0..100) for a given sun ``elevation``.

    A low sun arrives almost horizontally and is hard to block, so the slats
    have to close down (``tilt_low``). A high sun arrives steeply and is easy to
    cut off, so the slats may open up (``tilt_high``). Between the two elevation
    bounds the tilt is interpolated linearly; outside the band it is clamped.

    Args:
        elevation: Sun elevation in degrees.
        elevation_low: Elevation (deg) mapped to ``tilt_low``.
        elevation_high: Elevation (deg) mapped to ``tilt_high``.
        tilt_low: Tilt at (and below) ``elevation_low``.
        tilt_high: Tilt at (and above) ``elevation_high``.
    """

    if elevation_high <= elevation_low:
        # Degenerate band -> nothing to interpolate; keep the closed end.
        return tilt_low
    if elevation <= elevation_low:
        return tilt_low
    if elevation >= elevation_high:
        return tilt_high
    fraction = (elevation - elevation_low) / (elevation_high - elevation_low)
    return round(tilt_low + fraction * (tilt_high - tilt_low))


def slat_tilt_physical(
    elevation: float,
    *,
    slat_depth_mm: float,
    slat_distance_mm: float,
    tilt_low: int = DEFAULT_TILT_LOW,
    tilt_high: int = DEFAULT_TILT_HIGH,
) -> int:
    """Return the cut-off slat tilt using physical slat geometry.

    Computes the minimum tilt angle that blocks direct sunlight based on
    the slat depth (blade width) and the vertical distance between slats.
    """

    if slat_depth_mm <= 0 or slat_distance_mm <= 0:
        return tilt_low
    if elevation <= 0:
        return tilt_low
    if elevation >= 90:
        return tilt_high

    elevation_rad = math.radians(elevation)
    # Maximum critical angle at elevation 0: arctan(distance / depth).
    max_angle = math.atan(slat_distance_mm / slat_depth_mm)
    # Critical tilt decreases as the sun climbs.
    critical_angle = max_angle - elevation_rad
    if critical_angle <= 0:
        return tilt_high

    fraction = 1.0 - min(1.0, critical_angle / max_angle)
    return round(tilt_low + fraction * (tilt_high - tilt_low))


def apply_tilt_deadband(target: int, current: int | None, deadband: float) -> int:
    """Suppress micro-movements of the slats inside a dead band.

    Returns ``target`` when the cover has no known current tilt or when the
    change is large enough to be worth a motor move; otherwise it returns the
    ``current`` tilt unchanged so the resolver commands no new tilt.

    Args:
        target: Freshly computed tracking tilt.
        current: The cover's current tilt, if known.
        deadband: Minimum tilt change (percentage points) worth acting on.
    """

    if current is None or deadband <= 0:
        return target
    if abs(target - current) < deadband:
        return current
    return target
