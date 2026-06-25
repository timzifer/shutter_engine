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
4. **Lock** → hold the current position, automation suspended.
5. **Night / morning** → time-window gated brightness/relative trigger. The night
   phase is **latched and persisted**: once it fires it keeps the covers closed
   across the window end, midnight and restarts until the morning trigger releases
   it (so e.g. eco mode can't reopen them mid-night, and they still close in
   summer even when no dusk falls inside the window). Without a configured morning
   window there is no defined reopen point, so the latch is disabled and night
   stays momentary (the day mode reopens after the night window).
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

### Manual overrides

The engine only issues **momentary** commands and does not continuously track a
cover's physical position. Comfort drivers (night, morning, sun / eco / heat
protection) act **once when their decision changes** — if you move a cover by
hand afterwards, the automation does **not** drive it back; it only acts again
on the next decision change. Safety drivers (fire, storm) and the lock-out
constraints keep **enforcing** their target, so they self-correct a manual
change. Frost continues to block movement. Use the **lock / disable** controls
to suspend automation entirely.

## Data model (inheritance)

Configuration is layered `Hub → Ruleset → Controller → Window`. Every tunable
value may be set on any level; the **deepest set value wins**. The shade type
(`venetian` / `roller_shutter` / `standard`) seeds protection participation and
hardware capabilities, each individually overridable.

- **Ruleset** — a reusable behaviour bundle: target positions per day mode,
  brightness/temperature thresholds and the night/morning time windows. Several
  rulesets can exist side by side.
- **Controller** — bound to one Home Assistant area; references exactly **one**
  ruleset and adds the heating/temperature entities. Exposes the runtime
  controls (mode select, lock/night/morning/holiday switches, status sensor).
- **Window** — a controllable surface: picks its controller and **one or more**
  cover entities, then adds the sun funnel (azimuth/elevation), the escape-route
  flag and any per-window overrides. Grouping several covers (e.g. a window front
  in the same room) saves configuration; they share the surface configuration but
  are each resolved individually from their own position and runtime state.

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
wind, frost, fire and burglary sensors. They can be changed later from the
integration's **Configure** (options) dialog.

Everything else is added as individual **config subentries** from the
integration page — each with its own small form and its own device:

1. **Add ruleset** — define the behaviour (positions, thresholds, time windows).
2. **Add controller** — pick an area and the ruleset that drives it.
3. **Add window** — pick one or more covers, their controller, the sun funnel
   and the escape-route flag.

Each subentry can be reconfigured or deleted independently. See
[`examples/subentries.json`](examples/subentries.json) for the stored data
shape of each subentry type.

### Dynamic venetian slat tracking

Venetian blinds (Raffstore) can hold their shade position while continuously
re-angling their slats to track the sun: low sun closes the slats to cut off the
near-horizontal beam, high sun opens them to admit more diffuse daylight. A
configurable **dead band** (`sun_tracking_deadband`, degrees) suppresses
micro-movements so the slats only re-adjust when the change is worth a motor
move. Tracking is on by default for the `venetian` shade type and overridable
per cover; the statically configured tilt is used as a fallback when no sun data
is available.

### Entities exposed per controller

- `select.<controller>_mode` — off / sun protection / eco / heat protection
- `switch.<controller>_lock` — suspend automation
- `switch.<controller>_night` / `switch.<controller>_morning` — time functions
- `switch.<controller>_holiday` — presence simulation (randomized offsets)
- `sensor.<controller>_status` — per-cover diagnostic text (diagnostic category)
- `sensor.<controller>_debug` — diagnostic decision dump (disabled by default):
  per cover the winning rule (`selected_driver`), the final reason and the
  constraints that took effect

Both controller sensors live in the device's **Diagnostics** section. Each
**window** additionally exposes `sensor.<window>_status` (also diagnostic),
summarizing its covers with the resolved decision per cover entity.

Legacy devices left over from before the ruleset/controller/window split (shown
in Home Assistant as "devices not assigned to a subentry") are removed
automatically on setup.

## Development

```bash
pip install -r requirements_test.txt
pytest           # run the engine test suite
ruff check .     # lint
ruff format .    # format
```

The engine tests run without a Home Assistant installation. CI additionally runs
`hassfest` and HACS validation (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

### Visual behaviour examples

[`docs/example.md`](docs/example.md) documents how the controllers/drivers behave
over a full day with worked, "real" examples: time-series simulations of sun
position, indoor temperature, manual lock, fire and burglary, each rendered as a
chart of the inputs versus the resolved cover position. The charts are
(re)generated by `pytest tests/test_visual_scenarios.py` (requires `matplotlib`,
already in `requirements_test.txt`).

## Roadmap

- Phase-2 time-based position emulation for on/off-only actors.

## License

MIT
