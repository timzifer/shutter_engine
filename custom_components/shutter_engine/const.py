"""Constants for the Shutter Engine Home Assistant integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "shutter_engine"

# Storage --------------------------------------------------------------------
STORAGE_KEY: Final = f"{DOMAIN}.state"
STORAGE_VERSION: Final = 1

# Config entry data / options keys ------------------------------------------
CONF_HUB: Final = "hub"

# Subentry types -------------------------------------------------------------
SUBENTRY_RULESET: Final = "ruleset"
SUBENTRY_CONTROLLER: Final = "controller"
SUBENTRY_WINDOW: Final = "window"

CONF_SUN_ENTITY: Final = "sun_entity"
CONF_WEATHER_ENTITY: Final = "weather_entity"
CONF_WORKDAY_ENTITY: Final = "workday_entity"
CONF_WIND_ENTITY: Final = "wind_entity"
CONF_FROST_ENTITY: Final = "frost_entity"
CONF_FIRE_ENTITY: Final = "fire_entity"
CONF_BURGLARY_ENTITY: Final = "burglary_entity"

# Coordinator ---------------------------------------------------------------
# Periodic re-evaluation tick. The resolver also runs on every relevant state
# change; the tick covers time-based triggers (night/morning windows).
DEFAULT_SCAN_INTERVAL_SECONDS: Final = 60

PLATFORMS: Final = ["select", "switch", "sensor"]
