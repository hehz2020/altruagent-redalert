from altru_redalert.model import View
from altru_redalert.tactics import damage_rate, health, weapons
from redalert_bot_tests.test_controller import actor, state


def configured(damage=4000, reach=4.75, reload=2):
    return {"rules": {"units": {"2tnk": {"weapon": {
        "weapon": "90mm", "damage": damage, "range_cells": reach,
        "reload_seconds": reload}}}}}


def test_weapon_lookup_preserves_per_observation_config():
    tank = actor(1, "2tnk")
    target = actor(2, "3tnk")
    first = View(state(), configured())
    later = View(state(5), configured(damage=8000))
    original = damage_rate(first, tank, target)
    assert damage_rate(later, tank, target) == 2 * original
    assert damage_rate(first, tank, target) == original


def test_power_and_disable_state_override_known_weapon():
    view = View(state())
    turret = actor(1, "tsla")
    assert weapons(view, turret)
    assert weapons(view, {**turret, "powered": False}) == ()
    assert weapons(view, {**turret, "disabled": True}) == ()
    assert weapons(view, {**turret, "powered": True})


def test_runtime_weapon_revision_does_not_reuse_previous_rules():
    view = View(state(), configured())
    tank, target = actor(1, "2tnk"), actor(2, "3tnk")
    assert damage_rate(view, tank, target, at_distance=6) == 0
    view.catalog["2tnk"]["weapon"]["range_cells"] = 7
    assert damage_rate(view, tank, target, at_distance=6) > 0
    view.catalog["2tnk"]["weapon"]["damage"] = 0
    assert damage_rate(view, tank, target, at_distance=6) == 0


def test_health_and_range_are_evaluated_for_each_target():
    view = View(state(), configured())
    tank, target = actor(1, "2tnk"), actor(2, "3tnk")
    assert damage_rate(view, tank, target, at_distance=4) > 0
    assert damage_rate(view, tank, target, at_distance=6) == 0
    assert health(view, {**target, "hp": 25}) == health(view, target) / 4
