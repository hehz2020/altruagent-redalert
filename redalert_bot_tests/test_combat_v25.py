from copy import deepcopy

from altru_redalert.combat import Military
from altru_redalert.core import Controller
from altru_redalert.model import View, distance
from redalert_bot_tests.test_adversarial import actor, commands, snapshot
from redalert_bot_tests.test_v24_integration import accepted, apply_movement, legal_batch, mapped


def test_controller_defends_two_ore_zones_without_stopping_forward_army():
    bot, config = Controller(), mapped()
    army = [actor(10 + i, "2tnk", 55, 39 + i % 3) for i in range(8)]
    escorts = [actor(30, "apc", 26, 24), actor(31, "apc", 26, 64)]
    harvesters = [actor(40, "harv", 28, 20), actor(41, "harv", 28, 60)]
    enemies = [actor(100, "e1", 31, 20), actor(101, "e1", 31, 60)]
    for second in (400, 404, 408):
        raw = snapshot(second, units=deepcopy(army + escorts + harvesters),
                       buildings=[actor(1, "proc", 22, 20), actor(2, "proc", 22, 60)],
                       enemies=enemies, enemy_buildings=[actor(200, "weap", 80, 40)])
        result = commands(bot.decide(raw, config))
        legal_batch(raw, config, result)
        for uid, target, point in ((30, 100, (31, 20)), (31, 101, (31, 60))):
            response = [o for o in result if uid in o.get("units", [])]
            assert len(response) == 1
            assert (response[0].get("target") == target
                    or (response[0]["cmd"] == "attack_move"
                        and distance(response[0]["to"], point) < 3))
        assert any(o["cmd"] == "attack_move" and o["to"][0] > 55
                   and 10 in o["units"] for o in result)
        apply_movement(army + escorts, result)
        accepted(bot, result)


def test_sole_rifle_intercepts_capture_before_scouting():
    bot = Controller()
    unit = actor(10, "e1", 15, 12)
    for second, x in ((400, 17), (404, 16), (408, 15)):
        raw = snapshot(second, units=[unit], buildings=[actor(1, "fact", 12, 12)],
                       enemies=[actor(100, "e6", x, 12)])
        result = commands(bot.decide(raw))
        legal_batch(raw, {}, result)
        assert {"cmd": "attack", "units": [10], "target": 100} in result
        assert not any(o["cmd"] in {"move", "attack_move"} for o in result)
        assert bot.military.scout_id is None
        assert bot.military.scout_losses == 0
        accepted(bot, result)


def test_only_close_guard_intercepts_ore_raid_instead_of_leaving_to_scout():
    bot = Controller()
    for second in (400, 404, 408):
        raw = snapshot(second, units=[actor(10, "e1", 15, 12)],
                       buildings=[actor(1, "proc", 12, 12)],
                       enemies=[actor(100, "e1", 17, 12)])
        result = commands(bot.decide(raw))
        legal_batch(raw, {}, result)
        assert {"cmd": "attack", "units": [10], "target": 100} in result
        assert not any(o["cmd"] == "move" and 10 in o["units"] for o in result)
        assert bot.military.scout_id is None
        accepted(bot, result)


def test_capture_response_and_distant_ore_response_do_not_share_units():
    units = [actor(10, "e1", 15, 12), actor(11, "apc", 26, 64), actor(12, "harv", 28, 60)]
    raw = snapshot(400, units=units,
                   buildings=[actor(1, "fact", 12, 12), actor(2, "proc", 22, 60)],
                   enemies=[actor(100, "e6", 17, 12), actor(101, "e1", 31, 60)])
    result = commands(Controller().decide(raw, mapped()))
    legal_batch(raw, mapped(), result)
    assert {"cmd": "attack", "units": [10], "target": 100} in result
    assert any(11 in o.get("units", []) and o["cmd"] == "attack_move"
               and distance(o["to"], (31, 60)) < 3 for o in result)


def test_covered_first_ore_zone_does_not_hide_second_raid():
    army = [actor(10, "apc", 26, 64)]
    enemies = [actor(100, "e1", 29, 20), actor(101, "e1", 31, 60)]
    view = View(snapshot(400, units=army + [actor(30, "harv", 27, 20), actor(31, "harv", 28, 60)],
                         buildings=[actor(1, "proc", 22, 20), actor(2, "pbox", 26, 22),
                                    actor(3, "proc", 22, 60)], enemies=enemies))
    result, defenders = Military()._defense(view, army, enemies)
    assert defenders == {10}
    assert any(i.order.get("target") == 101 or i.order.get("to") == [31, 60] for i in result)


def test_duplicated_assets_at_same_raid_do_not_recall_extra_defenders():
    army = [actor(10, "apc", 27, 22)] + [actor(20 + i, "2tnk", 45, 30 + i) for i in range(8)]
    raw = snapshot(400, units=army + [actor(40 + i, "harv", 28, 20 + i) for i in range(4)],
                   buildings=[actor(1, "proc", 22, 20)], enemies=[actor(100, "e1", 31, 20)])
    view = View(raw)
    orders, defenders = Military()._defense(view, army, view.enemies)
    assert defenders == {10}
    assert len(orders) == 1


def test_covered_ore_zones_do_not_consume_mobile_response_slots():
    harvesters = [actor(30 + i, "harv", 28, y) for i, y in enumerate((20, 40, 60, 80))]
    towers = [actor(50 + i, "pbox", 27, y) for i, y in enumerate((20, 40, 60))]
    enemies = [actor(100 + i, "e1", 30, y) for i, y in enumerate((20, 40, 60, 80))]
    army = [actor(10, "apc", 26, 84)]
    view = View(snapshot(400, units=harvesters + army, buildings=towers, enemies=enemies))
    orders, defenders = Military()._defense(view, army, enemies)
    assert defenders == {10}
    assert any(i.order.get("target") == 103 or i.order.get("to") == [30, 80] for i in orders)


def test_ground_response_does_not_mark_untargetable_aircraft_handled():
    army = [actor(10, "apc", 27, 20)]
    enemies = [actor(100, "e1", 30, 20), actor(101, "yak", 30, 24)]
    asset = actor(30, "harv", 28, 20)
    view = View(snapshot(400, units=army + [asset], enemies=enemies))
    view.catalog["yak"] = {"queue": "Aircraft", "weapon": {"range_cells": 5, "damage": 1000}}
    _, _, covered = Military()._defend_zone(view, army, enemies, asset, enemies, False, set())
    assert covered == {100}


def test_multiple_engineers_get_distinct_interceptors():
    army = [actor(10, "e1", 15, 12), actor(11, "e1", 15, 14)]
    raw = snapshot(400, units=army, buildings=[actor(1, "fact", 12, 12)],
                   enemies=[actor(100, "e6", 17, 12), actor(101, "e6", 16, 14)])
    result = commands(Controller().decide(raw))
    legal_batch(raw, {}, result)
    assert {o.get("target") for o in result if o["cmd"] == "attack"} == {100, 101}
    assert {uid for o in result if o["cmd"] == "attack" for uid in o["units"]} == {10, 11}


def test_disconnected_nearest_escort_is_not_assigned_to_unreachable_raid():
    rows = ["." * 29 + "~" * 10 + "." * 57] * 96
    army = [actor(10, "apc", 44, 20), actor(11, "apc", 20, 22)]
    raw = snapshot(400, units=army + [actor(30, "harv", 29, 20)],
                   buildings=[actor(1, "proc", 24, 20)], enemies=[actor(100, "e1", 31, 20)])
    view = View(raw, mapped(rows))
    _, defenders = Military()._defense(view, army, view.enemies)
    assert defenders == {11}


def test_factory_goal_survives_nearby_low_value_silo_bait():
    bot, config = Controller(), mapped()
    army = [actor(10 + i, "2tnk", 20, 29 + i % 3) for i in range(8)]
    for step in range(3):
        raw = snapshot(400 + step * 4, units=deepcopy(army),
                       enemy_buildings=[actor(100, "silo", 20, 40), actor(101, "weap", 50, 30)])
        result = commands(bot.decide(raw, config))
        legal_batch(raw, config, result)
        assert bot.military.army_goal == (50, 30)
        assert not any(o.get("target") == 100 for o in result)
        assert any(o["cmd"] == "attack_move" and o["to"][0] > army[0]["x"] for o in result)
        apply_movement(army, result)
        accepted(bot, result)


def test_controller_changes_objective_when_factory_gets_overwhelming_garrison():
    bot, config = Controller(), mapped()
    army = [actor(10 + i, "2tnk", 20, 29 + i % 3) for i in range(6)]
    structures = [actor(100, "weap", 55, 30), actor(101, "proc", 50, 65)]
    first = commands(bot.decide(snapshot(400, units=army, enemy_buildings=structures), config))
    assert bot.military.army_goal == (55, 30)
    accepted(bot, first)
    towers = [actor(200 + i, "tsla", 50 + i % 3, 28 + i // 3) for i in range(8)]
    for second in (404, 408, 412):
        raw = snapshot(second, units=deepcopy(army), enemy_buildings=structures + towers)
        result = commands(bot.decide(raw, config))
        legal_batch(raw, config, result)
        assert bot.military.army_goal == (50, 65)
        assert any(o["cmd"] == "attack_move" and o["to"][1] > army[0]["y"] for o in result)
        apply_movement(army, result)
        accepted(bot, result)


def test_single_defender_does_not_divert_favorable_factory_assault():
    army = [actor(10 + i, "2tnk", 40, 29 + i % 3) for i in range(8)]
    raw = snapshot(400, units=army, enemy_buildings=[actor(100, "weap", 55, 30),
                   actor(101, "proc", 50, 60), actor(200, "gun", 52, 30)])
    bot = Controller()
    result = commands(bot.decide(raw, mapped()))
    assert bot.military.army_goal == (55, 30)
    assert bot.military.mode == "pressure"
    assert any(o["cmd"] == "attack_move" and o["to"][0] > 40 for o in result)


def test_remembered_factory_not_replaced_by_visible_scout_turret():
    military = Military()
    army = [actor(10 + i, "2tnk", 20, 29 + i % 3) for i in range(8)]
    first = View(snapshot(400, units=army, enemy_buildings=[actor(100, "weap", 50, 30)]))
    military._remember(first, army)
    current = View(snapshot(404, units=army, enemy_buildings=[actor(101, "pbox", 25, 40)]))
    military._remember(current, army)
    assert military._goal(current, (20, 30)) == (50, 30)
    stale = View(snapshot(521, units=army, enemy_buildings=[actor(101, "pbox", 25, 40)]))
    military._remember(stale, army)
    assert military._goal(stale, (20, 30)) == (25, 40)


def test_failed_order_forgets_only_matching_timestamp_and_signature():
    military = Military()
    old = {"cmd": "attack_move", "units": [10, 11], "to": [40, 30]}
    latest = {"cmd": "attack", "units": [11], "target": 100}
    military.mark_sent([old], 400)
    military.mark_sent([latest], 404)
    military.mark_failed(old, 400)
    assert 10 not in military.desired
    assert military.desired[11] == (("attack", 100), 404)
    military.mark_failed(latest, 400)
    assert 11 in military.desired
    military.mark_failed(latest, 404)
    assert not military.desired


def test_obstructed_scout_sweep_preserves_nearest_cell_ties():
    rows = [list("." * 96) for _ in range(96)]
    for x, y in ((15, 15), (14, 15), (15, 16)):
        rows[y - 1][x - 1] = "#"
    raw = snapshot(400)
    raw["map"]["bounds"] = [1, 1, 96, 96]
    raw["observation"]["base_center"] = [23, 44]
    raw["legal_actions"]["enemy_base"] = [74, 53]
    config = {"rules": {"maps": {"scenario-map": {"layout": {
        "origin": [1, 1], "rows": ["".join(row) for row in rows]}}}}}
    military = Military()
    military._prepare_sweep(View(raw, config))
    assert military.sweep == [
        (82, 60), (60, 60), (82, 37), (60, 37),
        (82, 82), (60, 82), (37, 60), (82, 15),
        (37, 37), (60, 15), (37, 82), (37, 15),
        (15, 60), (15, 37), (15, 82), (16, 15)]
