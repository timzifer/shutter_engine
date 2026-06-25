"""Concrete visual scenarios over a synthetic day.

Each scenario shares the same one-minute sun arc and indoor-temperature curve
from :mod:`tests.visual.simulation` and injects the events the user asked to see
documented: sun position, indoor temperature, manual lock, fire and burglary.
"""

from __future__ import annotations

from custom_components.shutter_engine.engine import DayMode
from tests.visual.simulation import (
    ControllerParams,
    RawInput,
    Scenario,
    build_day,
)


def _h(hour: float) -> int:
    """Minutes since midnight for a clock hour (e.g. ``13.5`` -> 13:30)."""

    return int(hour * 60)


# ---------------------------------------------------------------------------
# 1. Sun protection over a clear day
# ---------------------------------------------------------------------------

SUN_PROTECTION_DAY = Scenario(
    name="sun_protection_day",
    title="Sonnenschutz an einem klaren Tag",
    description=(
        "Tagesmodus Sonnenschutz. Sobald die Sonne in den Funnel steigt und es "
        "hell genug ist, verschattet der Treiber auf 80 %; die Lamellen tracken "
        "die Sonnenelevation. Am Abend, wenn die Helligkeit unter die "
        "Hysterese-Schwelle fällt, öffnet die Behang wieder."
    ),
    controller=ControllerParams(day_mode=DayMode.SUN_PROTECTION),
    inputs=build_day(),
)


# ---------------------------------------------------------------------------
# 2. Heat protection on a hot day
# ---------------------------------------------------------------------------

HEAT_PROTECTION_HOT_DAY = Scenario(
    name="heat_protection_hot_day",
    title="Hitzeschutz an einem heißen Tag",
    description=(
        "Tagesmodus Hitzeschutz mit Maximaltemperatur 24 °C. Über den Tag "
        "klettert die Raumtemperatur; sobald sie 24 °C überschreitet (oder die "
        "Sonne direkt verschattet), schließt der Behang vollständig (0 %) zum "
        "aktiven Kühlen. Kühlt der Raum ab, öffnet er wieder."
    ),
    controller=ControllerParams(day_mode=DayMode.HEAT_PROTECTION, max_temp=24.0),
    inputs=build_day(base_temp=21.0, temp_swing=8.0),
)


# ---------------------------------------------------------------------------
# 3. Manual lock suppresses automation
# ---------------------------------------------------------------------------


def _lock_window(raw: RawInput) -> RawInput:
    # Lock from 07:30 to 13:00 — across the morning shading window.
    if _h(7.5) <= raw.minute < _h(13):
        raw.locked = True
    return raw


MANUAL_LOCK = Scenario(
    name="manual_lock",
    title="Manuelle Sperre hält die Position",
    description=(
        "Tagesmodus Sonnenschutz, aber von 07:30 bis 13:00 ist die manuelle "
        "Sperre aktiv. Obwohl Sonne und Helligkeit längst eine Verschattung "
        "auslösen würden, hält der Behang seine Position (Reason LOCKED). Erst "
        "nach Aufheben der Sperre um 13:00 verschattet die Automatik auf 80 %."
    ),
    controller=ControllerParams(day_mode=DayMode.SUN_PROTECTION),
    inputs=build_day(_lock_window),
)


# ---------------------------------------------------------------------------
# 4. Fire forces the escape route fully open
# ---------------------------------------------------------------------------


def _fire_window(raw: RawInput) -> RawInput:
    # Short fire/smoke alarm around 13:00.
    if _h(13) <= raw.minute < _h(13.5):
        raw.fire_active = True
    return raw


FIRE_ESCAPE = Scenario(
    name="fire_escape",
    title="Feuer öffnet den Fluchtweg",
    description=(
        "Tagesmodus Sonnenschutz, der Behang ist mittags verschattet. Ein kurzer "
        "Feueralarm (13:00–13:30) fährt den als Fluchtweg markierten Behang "
        "sofort vollständig auf (100 %, Reason FIRE) und bricht dabei sämtliche "
        "Constraints. Nach dem Alarm kehrt die Automatik in den Sonnenschutz "
        "zurück."
    ),
    controller=ControllerParams(day_mode=DayMode.SUN_PROTECTION),
    inputs=build_day(_fire_window),
)


# ---------------------------------------------------------------------------
# 5. Burglary drives to a fixed security position
# ---------------------------------------------------------------------------


def _burglary_window(raw: RawInput) -> RawInput:
    # Intrusion detected in the late evening (21:00–23:00).
    if _h(21) <= raw.minute < _h(23):
        raw.burglary_active = True
    return raw


BURGLARY = Scenario(
    name="burglary",
    title="Einbruch fährt in die Sicherheitsposition",
    description=(
        "Tagesmodus Sonnenschutz. Am Abend (21:00–23:00) meldet die "
        "Einbruchüberwachung einen Alarm; der Sicherheits-Treiber fährt den "
        "Behang in die konfigurierte Einbruchsposition (hier 0 %, vollständig "
        "geschlossen, Reason BURGLARY) und erzwingt sie. Nach dem Alarm "
        "übernimmt wieder die Tagesautomatik."
    ),
    controller=ControllerParams(day_mode=DayMode.SUN_PROTECTION, burglary_position=0),
    inputs=build_day(_burglary_window),
)


#: All scenarios, in documentation order.
SCENARIOS: tuple[Scenario, ...] = (
    SUN_PROTECTION_DAY,
    HEAT_PROTECTION_HOT_DAY,
    MANUAL_LOCK,
    FIRE_ESCAPE,
    BURGLARY,
)
