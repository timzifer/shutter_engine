# Behaviour by example (visual test cases)

This page documents how the shutter engine's controllers/drivers behave over
"real" daily runs. Every chart is produced from a **time-series simulation**:
raw inputs (sun position, indoor temperature, event entities) are fed minute by
minute through the same logic as the real coordinator, and the resolver output
(cover position, slat tilt, decision reason) is recorded.

The charts are generated directly from the code and therefore always stay
consistent with the actual engine behaviour:

```bash
pip install -r requirements_test.txt
pytest tests/test_visual_scenarios.py
```

The scenarios live in [`tests/visual/`](../tests/visual/), and the associated
behavioural assertions in
[`tests/test_visual_scenarios.py`](../tests/test_visual_scenarios.py).

## How to read the charts

Each chart has three stacked panels sharing a common time axis (0–24 h):

1. **Environment** – sun elevation (left axis) and indoor temperature (right
   axis). The sun follows a synthetic daily arc (rise ~06:00, peak at noon,
   set ~20:00).
2. **States & events** – discrete entity/condition lanes (sun in funnel,
   "bright enough" after hysteresis, over max temperature, lock, fire,
   burglary). A lane is filled while its state is active; `(—)` marks lanes that
   never trigger in that particular scenario.
3. **Output** – the resulting **cover position** (0 % = open/up,
   100 % = closed/down) and the **slat tilt**. The coloured background shows the
   **decision reason** that won during that time window.

> Convention note: position `0` means open, `100` closed; for the tilt, `0`
> means "slats shut" and `100` means "slats horizontal/open".

---

## 1. Sun protection on a clear day

![Sun protection on a clear day](images/scenarios/sun_protection_day.png)

Day mode **sun protection**. As soon as the sun enters the funnel **and** it is
bright enough (brightness above the hysteresis threshold), the driver shades to
80 %. The slats **track** the sun elevation – a low sun closes the slats, a high
sun opens them. In the evening the brightness drops below the lower hysteresis
threshold and the cover opens again fully.

## 2. Heat protection on a hot day

![Heat protection on a hot day](images/scenarios/heat_protection_hot_day.png)

Day mode **heat protection** with a maximum temperature of 24 °C. The room
temperature follows the day with a lag and exceeds the limit in the afternoon.
As soon as `over max temp` becomes active (or the sun directly shades), the
cover closes fully (0 %) for active cooling. Once the room cools below the
hysteresis limit, the driver releases the cover again.

## 3. Manual lock holds the position

![Manual lock holds the position](images/scenarios/manual_lock.png)

Day mode sun protection, but the **manual lock** is active from **07:30 to
13:00**. Even though the sun and brightness would have long triggered shading,
the cover holds its position (reason **LOCKED**) – the lock sits above the
comfort drivers in the priority ladder. Only after the lock is released at 13:00
does the automation shade to 80 %.

## 4. Fire opens the escape route

![Fire opens the escape route](images/scenarios/fire_escape.png)

Day mode sun protection, the cover is shaded at midday. A short **fire alarm**
(13:00–13:30) immediately drives the cover marked as an escape route fully open
(100 %, reason **FIRE**), breaking all constraints (frost, minimum movement
interval) – life safety before motor protection. After the alarm the automation
returns to sun protection.

## 5. Burglary drives to the security position

![Burglary drives to the security position](images/scenarios/burglary.png)

Day mode sun protection. In the evening (**21:00–23:00**) the burglary
monitoring reports an alarm; the safety driver moves the cover to the configured
burglary position (here 0 %, fully closed, reason **BURGLARY**) and **enforces**
it actively. After the alarm the day automation takes over again. The target
position is configurable (`burglary_position`); without an explicit value the
driver holds the current position instead.
