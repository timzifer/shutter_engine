"""Home-Assistant-independent core engine for the shutter engine.

This subpackage deliberately has **no** dependency on Home Assistant so that
the decision logic (the resolver / state machine) and the configuration data
model can be unit-tested in isolation and reused outside of Home Assistant.

The Home Assistant integration layer (coordinator, entities, config flow)
lives in the parent package and feeds resolved inputs into :func:`resolve`.
"""

from .const import (
    ENFORCED_DRIVER_REASONS,
    MOMENTARY_DRIVER_REASONS,
    ContactState,
    DayMode,
    DecisionReason,
    ShadeType,
    SlatMode,
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
    ScheduleConfig,
    TimeFunction,
    WindowConfig,
)
from .resolver import (
    CommandPlan,
    ConstraintEval,
    Decision,
    DriverEval,
    ResolverInput,
    ResolverTrace,
    plan_command,
    resolve,
    resolve_trace,
)
from .slat import apply_tilt_deadband, slat_tilt_for_elevation, slat_tilt_physical
from .sun import (
    estimate_brightness,
    in_azimuth_funnel,
    in_elevation_band,
    in_sun_funnel,
)
from .timewindow import TimeWindowResult, latch_night, resolve_time_window

__all__ = [
    "CommandPlan",
    "ConstraintEval",
    "ContactState",
    "ControllerConfig",
    "CoverCapabilities",
    "DayMode",
    "Decision",
    "DecisionReason",
    "DriverEval",
    "ENFORCED_DRIVER_REASONS",
    "HubConfig",
    "MOMENTARY_DRIVER_REASONS",
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
    "ResolverTrace",
    "RulesetConfig",
    "ScheduleConfig",
    "ShadeType",
    "SlatMode",
    "slat_tilt_physical",
    "TemperatureHysteresis",
    "TimeFunction",
    "TimeWindowResult",
    "WindowConfig",
    "latch_night",
    "plan_command",
    "resolve",
    "resolve_time_window",
    "resolve_trace",
]
