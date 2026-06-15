"""Pure sun-geometry helpers used for funnel checks and brightness fallback.

Kept dependency-free so the geometry can be unit-tested without Home Assistant.
"""

from __future__ import annotations

from math import radians, sin


def in_azimuth_funnel(azimuth: float, az_from: float, az_to: float) -> bool:
    """Return whether ``azimuth`` lies within the ``[az_from, az_to]`` arc.

    All angles are degrees in ``[0, 360)``. The arc is interpreted clockwise
    from ``az_from`` to ``az_to`` and correctly handles the 0/360 wraparound
    (e.g. a funnel from 350 to 20 spans north).
    """

    azimuth %= 360.0
    az_from %= 360.0
    az_to %= 360.0
    if az_from <= az_to:
        return az_from <= azimuth <= az_to
    # Wraps past 360.
    return azimuth >= az_from or azimuth <= az_to


def in_elevation_band(
    elevation: float,
    elev_min: float | None,
    elev_max: float | None,
) -> bool:
    """Return whether ``elevation`` lies within the optional band."""

    if elev_min is not None and elevation < elev_min:
        return False
    return not (elev_max is not None and elevation > elev_max)


def in_sun_funnel(
    azimuth: float,
    elevation: float,
    az_from: float | None,
    az_to: float | None,
    elev_min: float | None,
    elev_max: float | None,
) -> bool:
    """Return whether the sun is inside the area's horizontal+vertical funnel."""

    if az_from is not None and az_to is not None and not in_azimuth_funnel(azimuth, az_from, az_to):
        return False
    return in_elevation_band(elevation, elev_min, elev_max)


def estimate_brightness(elevation: float, cloud_coverage: float = 0.0) -> float:
    """Estimate illuminance (lux) from sun elevation and cloud coverage.

    Fallback used when an area has no lux sensor. This is a coarse model: clear
    sky illuminance scales with the sine of the elevation and is attenuated by
    cloud coverage. Below the horizon the result is zero.

    Args:
        elevation: Sun elevation in degrees.
        cloud_coverage: Cloud coverage as a fraction ``0.0..1.0``.
    """

    if elevation <= 0.0:
        return 0.0
    cloud_coverage = max(0.0, min(cloud_coverage, 1.0))
    # ~120 klx peak clear-sky illuminance at zenith.
    clear_sky = 120000.0 * sin(radians(elevation))
    # Heavy overcast roughly cuts illuminance to ~20% of clear sky.
    attenuation = 1.0 - 0.8 * cloud_coverage
    return max(0.0, clear_sky * attenuation)
