"""Tests for :func:`plan_command` — momentary vs. enforced command gating."""

from __future__ import annotations

from custom_components.shutter_engine.engine import (
    Decision,
    DecisionReason,
    plan_command,
)


def _plan(decision: Decision, **kwargs):
    defaults = {
        "current_position": 50,
        "current_tilt": None,
        "last_target": None,
        "last_tilt": None,
        "can_tilt": False,
    }
    defaults.update(kwargs)
    return plan_command(decision, **defaults)


# -- momentary comfort drivers ---------------------------------------------


def test_momentary_skips_when_decision_unchanged() -> None:
    # Night already decided 0 last cycle; a manual change to 50 must be ignored.
    decision = Decision(position=0, tilt=None, reason=DecisionReason.NIGHT)
    plan = _plan(decision, current_position=50, last_target=0)
    assert plan.position is None
    assert not plan.moves


def test_momentary_commands_when_decision_changes() -> None:
    # Morning now wants open while the last decision was closed.
    decision = Decision(position=100, tilt=None, reason=DecisionReason.MORNING)
    plan = _plan(decision, current_position=0, last_target=0)
    assert plan.position == 100


def test_momentary_ignores_physical_position() -> None:
    # Sun protection target equals the last decision; the cover physically
    # sitting somewhere else (manual override) must not trigger a re-command.
    decision = Decision(position=80, tilt=None, reason=DecisionReason.SUN_PROTECTION)
    plan = _plan(decision, current_position=0, last_target=80)
    assert plan.position is None


# -- enforced safety drivers -----------------------------------------------


def test_enforced_corrects_physical_position() -> None:
    # Storm re-asserts the safe position even though the last decision matched.
    decision = Decision(position=0, tilt=None, reason=DecisionReason.STORM)
    plan = _plan(decision, current_position=60, last_target=0)
    assert plan.position == 0


def test_enforced_skips_when_already_at_target() -> None:
    decision = Decision(position=100, tilt=None, reason=DecisionReason.FIRE)
    plan = _plan(decision, current_position=100, last_target=0)
    assert plan.position is None


# -- holds and blocks -------------------------------------------------------


def test_blocked_never_moves() -> None:
    decision = Decision(
        position=0, tilt=None, reason=DecisionReason.FROST_BLOCK, blocked=True
    )
    plan = _plan(decision, current_position=100, last_target=0)
    assert not plan.moves


def test_hold_never_moves() -> None:
    for reason in (DecisionReason.HOLD, DecisionReason.LOCKED, DecisionReason.DISABLED):
        decision = Decision(position=50, tilt=None, reason=reason)
        plan = _plan(decision, current_position=0, last_target=100)
        assert not plan.moves, reason


# -- tilt -------------------------------------------------------------------


def test_momentary_tilt_edge_triggered() -> None:
    decision = Decision(position=80, tilt=45, reason=DecisionReason.SUN_PROTECTION)
    # Same target and tilt as last decision -> no movement at all.
    same = _plan(decision, current_position=80, last_target=80, last_tilt=45, can_tilt=True)
    assert not same.moves
    # Tilt changed since last decision -> only tilt is driven.
    changed = _plan(
        decision, current_position=80, last_target=80, last_tilt=10, can_tilt=True
    )
    assert changed.position is None
    assert changed.tilt == 45


def test_tilt_ignored_without_capability() -> None:
    decision = Decision(position=80, tilt=45, reason=DecisionReason.SUN_PROTECTION)
    plan = _plan(decision, current_position=80, last_target=80, last_tilt=10, can_tilt=False)
    assert plan.tilt is None
