from altru_redalert.economy import Economy
from altru_redalert.macro_map import MacroMap
from altru_redalert.mining import MiningManager
from altru_redalert.model import View
from redalert_bot_tests.test_economy_v2 import actor


def mining_view(now=0, *, units=None, enemies=(), towers=(), ore=((21, 20), (18, 34)),
                walls=(), map_known=True):
    rows = [["."] * 80 for _ in range(50)]
    for x, y in walls:
        rows[y][x] = "#"
    for x, y in ore:
        rows[y][x] = "$"
    config = {"rules": {"maps": {"test": {"layout": {
        "origin": [0, 0], "rows": ["".join(row) for row in rows]}}}}} if map_known else {}
    return View({"map": {"id": "test", "bounds": [0, 0, 80, 50]},
        "time": {"game_seconds": now, "remaining_seconds": 1000},
        "observation": {"base_center": [12, 20],
            "units": units if units is not None else [actor(10, "harv", 21, 20, idle=False)],
            "buildings": [actor(1, "proc", 12, 20), *towers],
            "visible_enemies": list(enemies)}} , config)


def commands(manager, view):
    return [intent.order for intent in manager.propose(view, MacroMap(view))]


def retreat_then(manager, **kwargs):
    v = mining_view(enemies=[actor(50, "2tnk", 24, 20)], **kwargs)
    result = commands(manager, v)
    assert len(result) == 1 and result[0]["cmd"] == "move"
    return result[0]["to"]


def test_single_rifle_hit_does_not_interrupt_covered_mining():
    manager = MiningManager()
    units = [actor(10, "harv", 21, 20, idle=False), actor(11, "ftrk", 20, 22)]
    raid = [actor(50, "e1", 24, 20)]
    assert commands(manager, mining_view(units=units, enemies=raid)) == []
    units[0]["hp"] = 99
    assert commands(manager, mining_view(2, units=units, enemies=raid)) == []


def test_healthy_harvester_does_not_panic_at_uncovered_rifle():
    assert commands(MiningManager(), mining_view(enemies=[actor(50, "e1", 23, 20)])) == []


def test_heavy_raid_retreats_only_the_threatened_harvester():
    manager = MiningManager()
    units = [actor(10, "harv", 21, 20, idle=False), actor(11, "harv", 18, 34, idle=False)]
    destination = retreat_then(manager, units=units)
    assert destination[0] < 21
    assert 2 < ((destination[0] - 21) ** 2 + (destination[1] - 20) ** 2) ** .5 <= 24
    assert manager.units[10]["retreat"] and not manager.units[11]["retreat"]


def test_rocket_infantry_counts_as_credible_anti_armor_threat():
    result = commands(MiningManager(), mining_view(enemies=[actor(50, "e3", 24, 20)]))
    assert result and result[0]["cmd"] == "move"


def test_safety_recovery_targets_near_ore_even_while_unit_still_moving():
    manager = MiningManager()
    target = retreat_then(manager)
    unit = actor(10, "harv", *target, idle=False)
    assert commands(manager, mining_view(2, units=[unit])) == []
    result = commands(manager, mining_view(4, units=[unit]))
    assert result == [{"cmd": "harvest", "units": [10], "to": [21, 20]}]
    assert not manager.units[10]["retreat"]
    assert commands(manager, mining_view(6, units=[unit])) == []


def test_returning_cargo_and_unloading_are_never_retargeted():
    for activity in ("ReturnToBase", "UnloadResources", "Docking"):
        manager = MiningManager()
        target = retreat_then(manager)
        unit = actor(10, "harv", *target, idle=False, act=activity)
        assert commands(manager, mining_view(4, units=[unit])) == []
        assert manager.units[10]["retreat"]
        unit["act"] = "Move"
        assert commands(manager, mining_view(8, units=[unit]))[0]["cmd"] == "harvest"


def test_regular_harvesting_and_unknown_nonidle_activity_are_not_overridden():
    for activity in ("HarvestResource", "Move", None):
        unit = actor(10, "harv", 21, 20, idle=False, act=activity)
        assert commands(MiningManager(), mining_view(units=[unit])) == []


def test_ore_route_does_not_cross_visible_tank_fire():
    unit = actor(10, "harv", 15, 20, idle=True)
    result = commands(MiningManager(), mining_view(units=[unit], ore=((32, 20), (12, 35)),
                      enemies=[actor(50, "2tnk", 26, 20)]))
    assert result == [{"cmd": "harvest", "units": [10], "to": [12, 35]}]


def test_disconnected_ore_is_not_selected_by_euclidean_proximity():
    unit = actor(10, "harv", 18, 20, idle=True)
    result = commands(MiningManager(), mining_view(units=[unit], ore=((22, 20), (12, 35)),
                      walls=[(20, y) for y in range(50)]))
    assert result == [{"cmd": "harvest", "units": [10], "to": [12, 35]}]


def test_unknown_ore_uses_engine_harvest_after_short_safety_pause():
    manager = MiningManager()
    target = retreat_then(manager, map_known=False)
    unit = actor(10, "harv", *target, idle=False)
    assert commands(manager, mining_view(4, units=[unit], map_known=False)) == [
        {"cmd": "harvest", "units": [10]}]


def test_idle_failed_directed_harvest_reverts_to_automatic_after_two_attempts():
    manager = MiningManager()
    unit = actor(10, "harv", 21, 20, idle=True)
    for now in (0, 12):
        assert "to" in commands(manager, mining_view(now, units=[unit]))[0]
    assert commands(manager, mining_view(24, units=[unit])) == [
        {"cmd": "harvest", "units": [10]}]


def test_dead_harvester_state_is_removed():
    manager = MiningManager()
    retreat_then(manager)
    assert commands(manager, mining_view(4, units=[])) == []
    assert manager.units == {}


def test_far_ore_does_not_force_a_long_manual_route():
    unit = actor(10, "harv", 15, 20, idle=True)
    result = commands(MiningManager(), mining_view(units=[unit], ore=((65, 20),)))
    assert result == [{"cmd": "harvest", "units": [10]}]


def test_real_economy_uses_mining_manager():
    economy = Economy()
    v = mining_view(enemies=[actor(50, "e1", 23, 20)])
    economy._refresh(v)
    assert economy._harvest(v) == []
    v = mining_view(2, enemies=[actor(50, "2tnk", 24, 20)])
    economy._refresh(v)
    assert economy._harvest(v)[0].order["cmd"] == "move"


def test_clearly_outbound_far_miner_gets_one_safe_near_ore_redirect():
    manager = MiningManager()
    first = actor(10, "harv", 32, 20, idle=False, act="Move")
    assert commands(manager, mining_view(units=[first])) == []
    second = actor(10, "harv", 36, 20, idle=False, act="Move")
    assert commands(manager, mining_view(4, units=[second])) == [
        {"cmd": "harvest", "units": [10], "to": [21, 20]}]
    third = actor(10, "harv", 40, 20, idle=False, act="Move")
    assert commands(manager, mining_view(8, units=[third])) == []


def test_inbound_far_miner_and_full_return_activity_are_preserved():
    for activity, first_x, second_x in (("Move", 40, 36), ("ReturnToBase", 32, 36)):
        manager = MiningManager()
        first = actor(10, "harv", first_x, 20, idle=False, act=activity)
        second = actor(10, "harv", second_x, 20, idle=False, act=activity)
        assert commands(manager, mining_view(units=[first])) == []
        assert commands(manager, mining_view(4, units=[second])) == []


def test_distant_enemy_mine_does_not_prevent_local_automatic_recovery():
    manager = MiningManager()
    unit = actor(10, "harv", 21, 20, idle=True)
    for now in (0, 12):
        result = commands(manager, mining_view(now, units=[unit], ore=((21, 20), (65, 20)),
                          enemies=[actor(50, "gun", 66, 20)]))
        assert result[0]["to"] == [21, 20]
    result = commands(manager, mining_view(24, units=[unit], ore=((21, 20), (65, 20)),
                      enemies=[actor(50, "gun", 66, 20)]))
    assert result == [{"cmd": "harvest", "units": [10]}]


def test_composite_harvest_activity_allows_safe_outbound_redirect():
    manager = MiningManager()
    first = actor(10, "harv", 32, 20, idle=False, act="FindAndDeliverResources")
    second = actor(10, "harv", 36, 20, idle=False, act="FindAndDeliverResources")
    assert commands(manager, mining_view(units=[first])) == []
    assert commands(manager, mining_view(4, units=[second])) == [
        {"cmd": "harvest", "units": [10], "to": [21, 20]}]


def test_retreat_still_works_on_known_terrain_without_initial_ore():
    target = retreat_then(MiningManager(), ore=())
    assert target[0] < 21


def test_five_hz_slow_outbound_miner_accumulates_trend_before_redirect():
    manager = MiningManager()
    commands_seen = []
    for frame in range(121):
        unit = actor(10, "harv", 32 + frame // 3, 20, idle=False,
                     act="FindAndDeliverResources")
        result = commands(manager, mining_view(frame * .2, units=[unit]))
        commands_seen.extend((frame * .2, order) for order in result)
    assert len(commands_seen) == 1
    assert 0 < commands_seen[0][0] <= 2
    assert commands_seen[0][1] == {"cmd": "harvest", "units": [10], "to": [21, 20]}


def test_five_hz_returning_miner_resets_outward_trend():
    manager = MiningManager()
    for frame in range(61):
        x = 34 + frame // 3 if frame < 3 else 35 - (frame - 3) // 3
        unit = actor(10, "harv", x, 20, idle=False, act="FindAndDeliverResources")
        assert commands(manager, mining_view(frame * .2, units=[unit])) == []
