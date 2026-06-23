"""Enumerations and constants used by the shutter engine core."""

from __future__ import annotations

from enum import StrEnum


class DayMode(StrEnum):
    """Daytime automation mode selected per room.

    Mirrors ``select.<room>_modus`` exposed by the integration.
    """

    OFF = "off"
    SUN_PROTECTION = "sun_protection"
    ECO = "eco"
    HEAT_PROTECTION = "heat_protection"


class ShadeType(StrEnum):
    """Hardware preset of a cover ("Behang-Typ").

    The type seeds protection participation and capabilities; every flag stays
    individually overridable in the options flow.
    """

    VENETIAN = "venetian"  # Raffstore: wind + frost, position + tilt
    ROLLER_SHUTTER = "roller_shutter"  # Panzer: position only
    STANDARD = "standard"  # Generic / custom, everything configurable
    CUSTOM = "custom"


class DecisionReason(StrEnum):
    """Why the resolver picked the resulting target.

    The reason is surfaced through ``sensor.<room>_status`` for diagnostics.
    Driver reasons follow the priority ladder; constraint reasons describe a
    post-ladder modification or veto.
    """

    # Drivers (first match wins) -------------------------------------------
    FIRE = "fire"
    BURGLARY = "burglary"
    STORM = "storm"
    DISABLED = "disabled"
    LOCKED = "locked"
    NIGHT = "night"
    MORNING = "morning"
    SUN_PROTECTION = "sun_protection"
    ECO = "eco"
    HEAT_PROTECTION = "heat_protection"
    HOLD = "hold"

    # Constraints (applied after the ladder) -------------------------------
    FROST_BLOCK = "frost_block"
    LOCKOUT_OPEN = "lockout_open"
    LOCKOUT_VENTILATION = "lockout_ventilation"
    MIN_INTERVAL_BLOCK = "min_interval_block"


# Drivers whose target is continuously enforced against the cover's physical
# position (safety / hardware protection): they re-assert their position even
# after a manual change, so the cover self-corrects.
ENFORCED_DRIVER_REASONS = frozenset(
    {
        DecisionReason.FIRE,
        DecisionReason.BURGLARY,
        DecisionReason.STORM,
        DecisionReason.LOCKOUT_OPEN,
        DecisionReason.LOCKOUT_VENTILATION,
    }
)

# Comfort drivers that only act momentarily: they command once when the
# decision changes and never fight a subsequent manual override. Any reason
# that is neither enforced nor momentary (HOLD, DISABLED, LOCKED, blocked
# constraints) results in no movement at all.
MOMENTARY_DRIVER_REASONS = frozenset(
    {
        DecisionReason.NIGHT,
        DecisionReason.MORNING,
        DecisionReason.SUN_PROTECTION,
        DecisionReason.ECO,
        DecisionReason.HEAT_PROTECTION,
    }
)


class SlatMode(StrEnum):
    """Slat tilt calculation mode for venetian blinds."""

    LINEAR = "linear"
    PHYSICAL = "physical"


class ContactState(StrEnum):
    """State of a window contact sensor used for lock-out protection."""

    CLOSED = "closed"
    TILTED = "tilted"
    OPEN = "open"


# Cover position convention: 0 = fully closed, 100 = fully open.
POSITION_CLOSED: int = 0
POSITION_OPEN: int = 100
