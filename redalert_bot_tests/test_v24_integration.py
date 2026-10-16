from copy import deepcopy
from random import Random

import pytest

from altru_redalert.core import Controller, validate_order
from altru_redalert.ground_routes import GroundRoutes
from altru_redalert.model import View, distance
from redalert_bot_tests.test_adversarial import actor, commands, snapshot


def mapped(rows=None):
    return {"rules": {"maps": {"scenario-map": {"layout": {
        "origin": [4, 4], "rows": rows or ["." * 96] * 96}}}}}


def accepted(bot, result):
    bot.on_result({"accepted": True, "results": [
        {"index": i, "status": "ok"} for i in range(len(result))]})


def apply_movement(units, result):
    for order in result:
        if order["cmd"] in {"move", "attack_move"}:
            for unit in units:
                if unit["id"] in order["units"]:
                    unit["x"], unit["y"] = order["to"]


def legal_batch(raw, config, result):
    view = View(raw, config)
    assert len(result) <= 20
    assert sum(len(order.get("units", [])) or order.get("count", 1)
               for order in result) <= 200
    ids = [uid for order in result for uid in order.get("units", [])]
    assert len(ids) == len(set(ids))
    assert all(validate_order(order, view) == order for order in result)
    assert sum(view.cost(order["item"]) * order.get("count", 1)
               for order in result if order["cmd"] in {"train", "build"}) <= view.funds


def test_controller_reaches_factory_around_visible_static_fire_corridor():
    bot, config = Controller(), mapped()
    army = [actor(10 + i, "2tnk", 20, 35 + i % 3) for i in range(8)]
    towers = [actor(91, "tsla", 50, 34), actor(92, "tsla", 50, 38)]
    positions = []
    attacked = set()
    for step in range(18):
        raw = snapshot(400 + step * 4, units=deepcopy(army),
                       buildings=[actor(1, "fact", 12, 12)],
                       enemy_buildings=towers + [actor(93, "weap", 80, 36)])
        result = commands(bot.decide(raw, config))
        legal_batch(raw, config, result)
        attacked.update(o["target"] for o in result if o["cmd"] == "attack")
        apply_movement(army, result)
        positions.append((army[0]["x"], army[0]["y"]))
        accepted(bot, result)
        if 93 in attacked:
            break
    assert 93 in attacked
    assert not attacked.intersection({91, 92})
    assert min(distance(point, (50, 34)) for point in positions) >= 8
    assert min(distance(point, (50, 38)) for point in positions) >= 8
    assert sum(distance(a, b) for a, b in zip(positions, positions[1:])) < 95


def test_controller_cancels_attack_when_overwhelming_reinforcements_arrive():
    bot, config = Controller(), mapped()
    army = [actor(10 + i, "2tnk", 65, 35 + i % 3) for i in range(8)]
    defenders = [actor(91, "gun", 80, 36), actor(93, "weap", 80, 36)]
    raw = snapshot(400, units=army, buildings=[actor(1, "fact", 12, 12)],
                   enemy_buildings=defenders)
    initial = commands(bot.decide(raw, config))
    assert any(o["cmd"] == "attack_move" and o["to"][0] > 65 for o in initial)
    accepted(bot, initial)
    defenders += [actor(100 + i, "tsla", 68 + i % 3, 30 + i // 3) for i in range(20)]
    raw = snapshot(404, units=army, buildings=[actor(1, "fact", 12, 12)],
                   enemy_buildings=defenders)
    result = commands(bot.decide(raw, config))
    legal_batch(raw, config, result)
    withdrawing = {uid for o in result if o["cmd"] == "move" and o["to"][0] < 65
                   for uid in o["units"]}
    assert withdrawing == {u["id"] for u in army}


def test_controller_never_uses_old_enemy_ids_as_live_attack_targets():
    bot, config = Controller(), mapped()
    army = [actor(10 + i, "2tnk", 65, 35 + i % 3) for i in range(8)]
    raw = snapshot(400, units=army, enemy_buildings=[actor(91, "weap", 68, 36)])
    initial = commands(bot.decide(raw, config))
    assert any(o["cmd"] == "attack" and o["target"] == 91 for o in initial)
    accepted(bot, initial)
    raw = snapshot(404, units=army)
    result = commands(bot.decide(raw, config))
    legal_batch(raw, config, result)
    assert not any(o.get("target") == 91 for o in result)


@pytest.mark.parametrize("cash", [1100, 1400, 2000])
def test_no_harvester_recovery_survives_simultaneous_tower_pressure(cash):
    buildings = [actor(1, "fact", 12, 12), actor(2, "powr", 14, 12),
                 actor(3, "tent", 12, 15), actor(4, "proc", 16, 16),
                 actor(5, "weap", 20, 12)]
    raw = snapshot(400, buildings=buildings, cash=cash,
                   build=["pbox", "gun", "powr", "proc"], train=["harv", "2tnk", "e1"],
                   enemies=[actor(100 + i, "e1", 20, 18 + i % 3) for i in range(6)])
    result = commands(Controller().decide(raw, mapped()))
    legal_batch(raw, mapped(), result)
    assert {"cmd": "train", "item": "harv"} in result
    assert not any(o.get("item") in {"pbox", "gun"} for o in result)


@pytest.mark.parametrize("seed", range(12))
def test_mixed_economy_and_military_orders_remain_legal_and_exclusive(seed):
    rng = Random(seed)
    units = [{**actor(10 + i, "harv", 19 + i * 3, 19), "hp": rng.choice([35, 65, 95, 100])}
             for i in range(3)]
    units += [actor(30 + i, rng.choice(["2tnk", "e1", "e3"]),
                    20 + rng.randrange(30), 20 + rng.randrange(10)) for i in range(20)]
    buildings = [actor(1, "fact", 12, 12), actor(2, "powr", 14, 12),
                 actor(3, "tent", 12, 15), actor(4, "proc", 16, 16),
                 actor(5, "weap", 20, 12), actor(6, "proc", 22, 16)]
    enemies = [actor(100 + i, rng.choice(["2tnk", "e1", "harv"]),
                     26 + rng.randrange(25), 20 + rng.randrange(15)) for i in range(10)]
    raw = snapshot(400, units=units, buildings=buildings, enemies=enemies,
                   enemy_buildings=[actor(200, "gun", 60, 30), actor(201, "weap", 70, 30)],
                   build=["pbox", "gun", "powr", "proc", "fix"],
                   train=["harv", "2tnk", "e1", "e3"], cash=rng.randrange(800, 4000))
    config = mapped()
    bot = Controller()
    for second in (400, 404, 408):
        raw["state_version"] = raw["observation"]["tick"] = second * 25
        raw["time"]["game_seconds"] = second
        result = commands(bot.decide(raw, config))
        legal_batch(raw, config, result)
        accepted(bot, result)


def test_controller_waypoints_stay_on_reachable_bank_when_goal_is_isolated():
    rows = ["." * 96] * 96
    rows = [row[:41] + "~~~~~~~~" + row[49:] for row in rows]
    config = mapped(rows)
    army = [actor(10 + i, "2tnk", 30, 35 + i % 3) for i in range(8)]
    raw = snapshot(400, units=army, enemy_buildings=[actor(93, "weap", 70, 36)])
    result = commands(Controller().decide(raw, config))
    legal_batch(raw, config, result)
    routes = GroundRoutes(View(raw, config))
    assert any(o["cmd"] == "attack_move" for o in result)
    assert all(routes.reachable((30, 36), o["to"])
               for o in result if o["cmd"] in {"move", "attack_move"})


def test_controller_selects_reachable_refinery_over_factory_across_wide_water():
    rows = ["." * 41 + "~~~~~~~~" + "." * 47] * 96
    config = mapped(rows)
    army = [actor(10 + i, "2tnk", 30, 29 + i % 3) for i in range(8)]
    raw = snapshot(400, units=army, enemy_buildings=[
        actor(93, "weap", 54, 30), actor(94, "proc", 25, 60)])
    result = commands(Controller().decide(raw, config))
    legal_batch(raw, config, result)
    toward_refinery = [o for o in result if o["cmd"] == "attack_move"
                       and o["to"][0] <= 30 and o["to"][1] > 30]
    assert {uid for o in toward_refinery for uid in o["units"]} == {u["id"] for u in army}


def test_local_escort_stays_with_harvester_while_main_army_keeps_attacking():
    army = [actor(10 + i, "2tnk", 55 + i % 3, 55 + i // 3) for i in range(12)]
    raw = snapshot(400, units=army + [actor(31, "apc", 27, 22), actor(30, "harv", 28, 20)],
                   buildings=[actor(1, "proc", 22, 20)], enemies=[actor(100, "e1", 31, 20)],
                   enemy_buildings=[actor(101, "weap", 80, 60)])
    result = commands(Controller().decide(raw, mapped()))
    legal_batch(raw, mapped(), result)
    escorts = [o for o in result if 31 in o.get("units", [])]
    assert len(escorts) == 1
    assert escorts[0]["cmd"] in {"attack", "attack_move"}
    if "to" in escorts[0]:
        assert distance(escorts[0]["to"], (28, 20)) <= 8
    else:
        assert escorts[0]["target"] == 100
    advancing = {uid for o in result if o["cmd"] == "attack_move" and o["to"][0] >= 55
                 for uid in o["units"]}
    assert advancing == {u["id"] for u in army}


def test_controller_restarts_near_mining_after_raid_without_interrupting_main_army():
    rows = [["."] * 96 for _ in range(96)]
    for x, y in ((21, 20), (18, 34)):
        rows[y - 4][x - 4] = "$"
    config = mapped(["".join(row) for row in rows])
    army = [actor(10 + i, "2tnk", 60 + i % 3, 55 + i // 3) for i in range(8)]
    miners = [{**actor(30, "harv", 21, 20), "idle": False},
              {**actor(31, "harv", 18, 34), "idle": False}]
    raw = snapshot(400, units=army + miners, buildings=[actor(1, "proc", 12, 20)],
                   enemies=[actor(100, "2tnk", 24, 20)],
                   enemy_buildings=[actor(101, "weap", 80, 60)])
    bot = Controller()
    first = commands(bot.decide(raw, config))
    legal_batch(raw, config, first)
    escape = [o for o in first if 30 in o.get("units", [])]
    assert len(escape) == 1 and escape[0]["cmd"] == "move"
    assert escape[0]["to"][0] < 21
    assert not any(31 in o.get("units", []) for o in first)
    assert any(o["cmd"] == "attack_move" and set(o["units"]) == {a["id"] for a in army}
               for o in first)
    accepted(bot, first)
    apply_movement(miners, first)
    raw = snapshot(404, units=army + miners, buildings=[actor(1, "proc", 12, 20)],
                   enemy_buildings=[actor(101, "weap", 80, 60)])
    second = commands(bot.decide(raw, config))
    legal_batch(raw, config, second)
    assert {"cmd": "harvest", "units": [30], "to": [21, 20]} in second
    assert not any(31 in o.get("units", []) for o in second)


def test_new_match_does_not_inherit_previous_harvester_escape_state():
    bot, config = Controller(), mapped()
    miner = {**actor(30, "harv", 21, 20), "idle": False}
    raw = snapshot(400, units=[miner], buildings=[actor(1, "proc", 12, 20)],
                   enemies=[actor(100, "2tnk", 24, 20)])
    first = commands(bot.decide(raw, config))
    assert any(o["cmd"] == "move" and o["units"] == [30] for o in first)
    accepted(bot, first)
    raw = snapshot(404, units=[miner], buildings=[actor(1, "proc", 12, 20)])
    raw["session_id"] = "new-scenario"
    second = commands(bot.decide(raw, config))
    legal_batch(raw, config, second)
    assert not any(30 in o.get("units", []) for o in second)
