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
    ControllerConfig,
    CoverCapabilities,
    HubConfig,
    ModePosition,
    ProtectionFlags,
    ResolvedCoverConfig,
    RulesetConfig,
    TimeFunction,
    WindowConfig,
)
from .resolver import Decision, ResolverInput, resolve
from .slat import apply_tilt_deadband, slat_tilt_for_elevation
from .sun import (
    estimate_brightness,
    in_azimuth_funnel,
    in_elevation_band,
    in_sun_funnel,
)
from .timewindow import TimeWindowResult, resolve_time_window

__all__ = [
    "ContactState",
    "ControllerConfig",
    "CoverCapabilities",
    "DayMode",
    "Decision",
    "DecisionReason",
    "HubConfig",
    "Hysteresis",
    "apply_tilt_deadband",
    "estimate_brightness",
    "in_azimuth_funnel",
    "in_elevation_band",
    "in_sun_funnel",
    "ModePosition",
    "slat_tilt_for_elevation",
    "ProtectionFlags",
    "ResolvedCoverConfig",
    "ResolverInput",
    "RulesetConfig",
    "ShadeType",
    "TemperatureHysteresis",
    "TimeFunction",
    "TimeWindowResult",
    "WindowConfig",
    "resolve",
    "resolve_time_window",
]
