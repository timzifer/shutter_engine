"""Visual, time-series scenario tests.

Each scenario is simulated minute by minute (see :mod:`tests.visual.simulation`)
and checked for the expected resolver behaviour. As a side effect every test
regenerates the documentation chart under ``docs/images/scenarios/`` that
``docs/example.md`` embeds, so the docs always match the current engine
behaviour.

The whole module is skipped cleanly when matplotlib is unavailable, keeping the
core CI matrix green without the extra dependency.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("matplotlib")

from tests.visual.plotting import render_scenario  # noqa: E402
from tests.visual.scenarios import SCENARIOS  # noqa: E402
from tests.visual.simulation import Frame, Scenario, run_scenario  # noqa: E402

#: ``docs/images/scenarios/`` relative to the repository root.
_DOCS_IMAGE_DIR = Path(__file__).resolve().parents[1] / "docs" / "images" / "scenarios"


def _frame_at(frames: list[Frame], hour: float) -> Frame:
    """Return the frame at clock ``hour`` (e.g. ``13.0`` -> 13:00)."""

    minute = int(hour * 60)
    return next(f for f in frames if f.minute == minute)


@pytest.fixture(scope="module", params=SCENARIOS, ids=lambda s: s.name)
def simulated(request: pytest.FixtureRequest) -> tuple[Scenario, list[Frame]]:
    """Run a scenario once and render its documentation chart."""

    scenario: Scenario = request.param
    frames = run_scenario(scenario)
    render_scenario(frames, scenario, _DOCS_IMAGE_DIR / f"{scenario.name}.png")
    return scenario, frames


def test_chart_is_written(simulated: tuple[Scenario, list[Frame]]) -> None:
    scenario, _frames = simulated
    out = _DOCS_IMAGE_DIR / f"{scenario.name}.png"
    assert out.exists()
    assert out.stat().st_size > 1000  # a real PNG, not an empty stub


def test_positions_are_in_range(simulated: tuple[Scenario, list[Frame]]) -> None:
    _scenario, frames = simulated
    assert frames
    for frame in frames:
        assert 0 <= frame.position <= 100
        assert frame.tilt is None or 0 <= frame.tilt <= 100


def test_sun_protection_shades_at_midday() -> None:
    frames = run_scenario(_by_name("sun_protection_day"))
    midday = _frame_at(frames, 12.0)
    assert midday.sun_in_funnel and midday.bright_enough
    assert midday.reason == "sun_protection"
    assert midday.position == 80
    assert midday.tilt is not None  # slats track the sun
    # Before sunrise the cover is held open by the sun-protection driver.
    assert _frame_at(frames, 3.0).position == 100


def test_heat_protection_closes_when_over_max() -> None:
    frames = run_scenario(_by_name("heat_protection_hot_day"))
    assert max(f.room_temp for f in frames) > 24.0
    overheated = [f for f in frames if f.heat_over_max]
    assert overheated, "scenario should cross the max temperature"
    assert all(f.reason == "heat_protection" and f.position == 0 for f in overheated)


def test_manual_lock_holds_position() -> None:
    frames = run_scenario(_by_name("manual_lock"))
    locked = _frame_at(frames, 10.0)
    assert locked.locked
    assert locked.reason == "locked"
    assert locked.position == 100  # held at the pre-lock position, not shaded
    # Once the lock is released the automation shades normally.
    after = _frame_at(frames, 14.0)
    assert after.reason == "sun_protection"
    assert after.position == 80


def test_fire_opens_escape_route() -> None:
    frames = run_scenario(_by_name("fire_escape"))
    during = _frame_at(frames, 13.25)
    assert during.fire_active
    assert during.reason == "fire"
    assert during.position == 100
    # Shaded again once the alarm clears.
    assert _frame_at(frames, 14.0).reason == "sun_protection"


def test_burglary_drives_to_security_position() -> None:
    frames = run_scenario(_by_name("burglary"))
    during = _frame_at(frames, 22.0)
    assert during.burglary_active
    assert during.reason == "burglary"
    assert during.position == 0


def _by_name(name: str) -> Scenario:
    return next(s for s in SCENARIOS if s.name == name)
