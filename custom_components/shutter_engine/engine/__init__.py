"""Home-Assistant-independent core engine for the shutter engine.

This subpackage deliberately has **no** dependency on Home Assistant so that
the decision logic (the resolver / state machine) and the configuration data
model can be unit-tested in isolation and reused outside of Home Assistant.

The Home Assistant integration layer (coordinator, entities, config flow)
lives in the parent package and feeds resolved inputs into :func:`resolve`.
"""

from .const import (
    ContactState,
    DayMode,
    DecisionReason,
    ShadeType,
)
from .hysteresis import Hysteresis, TemperatureHysteresis
from .models import (
    AreaConfig,
    CoverCapabilities,
    CoverConfig,
    HubConfig,
    ModePosition,
    ProtectionFlags,
    ResolvedCoverConfig,
    RoomConfig,
)
from .resolver import Decision, ResolverInput, resolve
from .sun import (
    estimate_brightness,
    in_azimuth_funnel,
    in_elevation_band,
    in_sun_funnel,
)
from .timewindow import TimeWindowResult, resolve_time_window

__all__ = [
    "AreaConfig",
    "ContactState",
    "CoverCapabilities",
    "CoverConfig",
    "DayMode",
    "Decision",
    "DecisionReason",
    "HubConfig",
    "Hysteresis",
    "estimate_brightness",
    "in_azimuth_funnel",
    "in_elevation_band",
    "in_sun_funnel",
    "ModePosition",
    "ProtectionFlags",
    "ResolvedCoverConfig",
    "ResolverInput",
    "RoomConfig",
    "ShadeType",
    "TemperatureHysteresis",
    "TimeWindowResult",
    "resolve",
    "resolve_time_window",
]
