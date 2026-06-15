# Shutter Engine

A Home Assistant **custom component (HACS)** that replaces scattered shutter
(Rollladen) automations with one central, room-based, resolver-driven state
machine.

Instead of a pile of YAML automations, all modes and functions are merely
*inputs*. A per-cover **resolver** (running inside a `DataUpdateCoordinator`)
derives exactly **one** target position for every cover on every relevant
trigger.

## Architecture

The core principle is a strict separation between:

- **Drivers** — propose a target position. An ordered priority ladder where the
  **first match wins**.
- **Constraints** — applied *afterwards*; they modify or veto the result
  (e.g. "do not move while frozen", "clamp to a ventilation slot").

The decision logic lives in [`custom_components/shutter_engine/engine`](custom_components/shutter_engine/engine),
which is **completely independent of Home Assistant** and fully unit-tested. The
Home Assistant layer (coordinator, entities, config flow) only feeds resolved
inputs into the engine.

### Priority ladder (drivers)

1. **Fire / smoke (escape route)** → open participating covers to 100 %.
   *Breaks the frost and minimum-interval constraints — life safety before motor
   protection.*
2. **Burglary / security** → default: no action; optional fixed position.
3. **Storm** → safe position (only for wind-protected covers).
4. **Lock / manual override** → hold the current position, automation suspended.
5. **Night / morning** → time-window gated brightness/relative trigger.
6. **Sun / eco / heat protection** → sun funnel + brightness (+ temperature).
7. **Default** → hold the last position.

### Constraints (applied after the ladder)

- **Frost** → block all movement (priority over storm). Only for frost-protected
  covers.
- **Lock-out protection** (window contact):
  - *open* → absolute lock, drive/stay fully open;
  - *tilted* → clamp "close" commands to a ventilation slot.
- **Minimum movement interval** → suppress command spam / relay wear.

> Deliberate trade-off: **frost beats storm.** A frozen shutter must not move,
> even in a storm, to protect the motor.

## Data model (inheritance)

Configuration is layered `Hub → Room → Area → Cover`. Every tunable value may be
set on any level; the **deepest set value wins**. The shade type
(`venetian` / `roller_shutter` / `standard`) seeds protection participation and
hardware capabilities, each individually overridable.

## Installation

### HACS (recommended)

1. Add this repository as a custom repository (category: *Integration*).
2. Install **Shutter Engine**.
3. Restart Home Assistant.
4. Add the integration via **Settings → Devices & Services → Add Integration**.

### Manual

Copy `custom_components/shutter_engine` into your Home Assistant
`config/custom_components` directory and restart.

## Configuration

The **config flow** sets up the global (hub) entities: sun, weather, workday,
wind, frost, fire and burglary sensors.

The room/area/cover tree is edited in the **options flow** as a validated JSON
document (a guided step-by-step editor is on the roadmap). See
[`examples/rooms.json`](examples/rooms.json) for a complete example.

### Entities exposed per room

- `select.<room>_mode` — off / sun protection / eco / heat protection
- `switch.<room>_lock` — suspend automation
- `switch.<room>_night` / `switch.<room>_morning` — time functions
- `switch.<room>_holiday` — presence simulation (randomized offsets)
- `sensor.<room>_status` — per-cover diagnostic text

## Development

```bash
pip install -r requirements_test.txt
pytest           # run the engine test suite
ruff check .     # lint
ruff format .    # format
```

The engine tests run without a Home Assistant installation. CI additionally runs
`hassfest` and HACS validation (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Roadmap

- Guided, step-by-step room/area/cover editor in the options flow.
- Dynamic venetian slat tracking with a configurable dead band.
- Phase-2 time-based position emulation for on/off-only actors.

## License

MIT
