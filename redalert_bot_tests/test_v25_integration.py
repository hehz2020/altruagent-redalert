from copy import deepcopy

import pytest

from altru_redalert.core import Controller
from redalert_bot_tests.test_adversarial import actor, commands, snapshot
from redalert_bot_tests.test_development_v22 import development_view
from redalert_bot_tests.test_v24_integration import accepted, legal_batch, mapped


def test_large_army_uses_remaining_batch_capacity_and_sends_remainder_next_frame():
    units = [{**actor(10 + i, "2tnk", 40 + i % 5, 30 + i % 5),
              "idle": False, "act": "Move"} for i in range(200)]
    buildings = [actor(1, "fact"), actor(2, "powr"), actor(3, "tent"),
                 actor(4, "proc"), actor(5, "weap")]
    config = {"rules": {"units": {"2tnk": {"cost": 850, "queue": "Vehicle"}}}}
    raw = snapshot(400, units=units, buildings=buildings, build=["powr"],
                   train=["2tnk"], cash=5000)
    raw["observation"]["economy"]["power_provided"] = 50
    bot = Controller()
    first = commands(bot.decide(raw, config))
    legal_batch(raw, config, first)
    production = [order for order in first if order["cmd"] in {"build", "train"}]
    assert production == [{"cmd": "build", "item": "powr"},
                          {"cmd": "train", "item": "2tnk"}]
    sent = {uid for order in first for uid in order.get("units", [])}
    assert len(sent) == 198
    accepted(bot, first)
    raw = deepcopy(raw)
    raw["time"]["game_seconds"] = 403
    raw["state_version"] = raw["observation"]["tick"] = 403 * 25
    second = commands(bot.decide(raw, config))
    legal_batch(raw, config, second)
    remaining = {unit["id"] for unit in units} - sent
    assert remaining <= {uid for order in second for uid in order.get("units", [])}


@pytest.mark.parametrize("verdict", ["rejected", "lost", "STALE_STATE"])
def test_explicit_failed_attack_is_retried_after_backoff_while_previous_move_is_active(verdict):
    units = [{**actor(10 + i, "2tnk", 65, 35 + i % 3),
              "idle": False, "act": "Move"} for i in range(8)]
    config = mapped()
    bot = Controller()
    first_raw = snapshot(400, units=units, enemy_buildings=[actor(91, "weap", 68, 36)])
    first = commands(bot.decide(first_raw, config))
    assert {uid for order in first if order.get("target") == 91
            for uid in order.get("units", [])} == {unit["id"] for unit in units}
    if verdict == "STALE_STATE":
        bot.on_result({"error": "STALE_STATE"})
    else:
        bot.on_result({"accepted": True, "results": [
            {"index": i, "status": verdict, "reason": "not_applied"}
            for i in range(len(first))]})
    next_raw = snapshot(403, units=units, enemy_buildings=[actor(91, "weap", 68, 36)])
    second = commands(bot.decide(next_raw, config))
    legal_batch(next_raw, config, second)
    assert {uid for order in second if order.get("target") == 91
            for uid in order.get("units", [])} == {unit["id"] for unit in units}


def test_two_mining_raids_get_separate_local_escorts_while_main_force_advances():
    army = [actor(10 + i, "2tnk", 55 + i % 3, 60 + i // 3) for i in range(12)]
    miners = [{**actor(30, "harv", 28, 20), "idle": False},
              {**actor(31, "harv", 28, 50), "idle": False}]
    escorts = [actor(32, "apc", 22, 20), actor(33, "apc", 22, 50)]
    raw = snapshot(400, units=army + miners + escorts,
                   buildings=[actor(1, "proc", 22, 20), actor(2, "proc", 22, 50)],
                   enemies=[actor(100, "e1", 32, 20), actor(101, "e1", 32, 50)],
                   enemy_buildings=[actor(102, "weap", 80, 60)])
    config = mapped()
    result = commands(Controller().decide(raw, config))
    legal_batch(raw, config, result)
    assert {"cmd": "attack_move", "units": [32], "to": [32, 20]} in result
    assert {"cmd": "attack_move", "units": [33], "to": [32, 50]} in result
    assert not any({30, 31}.intersection(order.get("units", [])) for order in result)
    advancing = {uid for order in result if order["cmd"] == "attack_move"
                 and order["to"][0] > 55 for uid in order["units"]}
    assert {unit["id"] for unit in army} <= advancing


def ore_map():
    rows = [["."] * 96 for _ in range(96)]
    for x, y in ((21, 20), (21, 24)):
        rows[y - 4][x - 4] = "$"
    return mapped(["".join(row) for row in rows])


def test_batch_limited_mining_command_does_not_delay_the_unselected_miner():
    miners = [actor(30, "harv", 18, 20), actor(31, "harv", 18, 24)]
    raw = snapshot(400, units=miners, buildings=[actor(1, "proc", 12, 20)])
    raw["limits"]["max_orders_per_batch"] = 1
    config = ore_map()
    bot = Controller()
    first = commands(bot.decide(raw, config))
    legal_batch(raw, config, first)
    assert len(first) == 1 and first[0]["cmd"] == "harvest"
    accepted(bot, first)
    raw["time"]["game_seconds"] = 400.2
    raw["state_version"] = raw["observation"]["tick"] = 10005
    second = commands(bot.decide(raw, config))
    legal_batch(raw, config, second)
    assert len(second) == 1 and second[0]["cmd"] == "harvest"
    assert set(first[0]["units"] + second[0]["units"]) == {30, 31}


def test_rejected_mine_assignment_retries_after_backoff_without_losing_near_ore():
    raw = snapshot(400, units=[actor(30, "harv", 18, 20)],
                   buildings=[actor(1, "proc", 12, 20)])
    config = ore_map()
    bot = Controller()
    first = commands(bot.decide(raw, config))
    assert first == [{"cmd": "harvest", "units": [30], "to": [21, 20]}]
    bot.on_result({"accepted": True, "results": [
        {"index": 0, "status": "rejected", "reason": "not_applied"}]})
    raw["time"]["game_seconds"] = 404.2
    raw["state_version"] = raw["observation"]["tick"] = 10105
    second = commands(bot.decide(raw, config))
    legal_batch(raw, config, second)
    assert second == first


def test_remote_rocket_squad_does_not_mask_local_aa_production_emergency():
    view = development_view(seconds=150, cash=1100, harvesters=2,
                            refineries=2, vehicle=False,
                            enemies=[actor(90, "yak", 31, 12)])
    view.raw["observation"]["units"] += [actor(100 + i, "e3", 80, 60) for i in range(4)]
    result = commands(Controller().decide(view.raw, view.config))
    legal_batch(view.raw, view.config, result)
    assert {"cmd": "train", "item": "ftrk"} in result
    assert any(order.get("item") == "e3" for order in result)
    assert not any(order.get("item") in {"harv", "proc", "fix"} for order in result)


@pytest.mark.parametrize("opponent,command", [("e1", "move"), ("arty", "attack")])
def test_cleanup_survives_combat_interruption_then_detects_a_real_blockage(opponent, command):
    bot, config = Controller(), mapped()
    army = [actor(10 + i, "2tnk", 60, 30) for i in range(8)]
    first = commands(bot.decide(snapshot(400, units=army), config))
    accepted(bot, first)
    goal = bot.military.search_goal
    assert goal is not None
    interrupted = [{**unit, "x": 50, "y": 50, "hp": 20} for unit in army]
    for now in range(404, 441, 4):
        raw = snapshot(now, units=interrupted, enemies=[actor(300, opponent, 54, 50)])
        result = commands(bot.decide(raw, config))
        legal_batch(raw, config, result)
        assert {uid for order in result if order["cmd"] == command
                for uid in order.get("units", [])} == {unit["id"] for unit in army}
        assert not any(order["cmd"] == "attack_move" for order in result)
        assert bot.military.search_goal == goal
        accepted(bot, result)
    resumed = [{**unit, "hp": 100} for unit in interrupted]
    for now in (444, 452, 460, 468):
        raw = snapshot(now, units=resumed)
        result = commands(bot.decide(raw, config))
        legal_batch(raw, config, result)
        assert bot.military.search_goal == goal
        assert any(order["cmd"] == "attack_move" for order in result)
        accepted(bot, result)
    raw = snapshot(472, units=resumed)
    result = commands(bot.decide(raw, config))
    legal_batch(raw, config, result)
    assert bot.military.search_goal is not None and bot.military.search_goal != goal
    assert any(order["cmd"] == "attack_move" for order in result)
