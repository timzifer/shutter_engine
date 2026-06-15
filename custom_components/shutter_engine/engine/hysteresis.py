"""Stateful hysteresis helpers used to prevent fluttering.

These helpers are intentionally tiny and pure: they own a single boolean state
and flip it only when a value crosses the relevant threshold. This keeps the
resolver deterministic and easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Hysteresis:
    """Two-threshold brightness hysteresis.

    The state turns *on* when the value reaches ``high`` and only turns *off*
    again once the value drops below ``low``. ``high`` must be ``>= low``.
    """

    high: float
    low: float
    active: bool = False

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError("high threshold must be >= low threshold")

    def update(self, value: float) -> bool:
        """Feed a new measurement and return the resulting state."""

        if self.active:
            if value < self.low:
                self.active = False
        elif value >= self.high:
            self.active = True
        return self.active


@dataclass
class TemperatureHysteresis:
    """Hysteresis around a temperature set point.

    ``active`` means "above the set point" (with hysteresis). It turns on once
    the temperature reaches ``set_point`` and turns off once it drops below
    ``set_point - hysteresis``. Used by eco and heat-protection modes to avoid
    constant movement at the temperature boundary.
    """

    set_point: float
    hysteresis: float
    active: bool = False

    def update(self, temperature: float) -> bool:
        """Feed a new temperature reading and return the resulting state."""

        if self.active:
            if temperature < self.set_point - self.hysteresis:
                self.active = False
        elif temperature >= self.set_point:
            self.active = True
        return self.active
