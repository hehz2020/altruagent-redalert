from altru_redalert.mining import MiningManager
from redalert_bot_tests.test_economy_v2 import actor
from redalert_bot_tests.test_mining_v24 import commands, mining_view, retreat_then


def test_active_miner_reserves_ore_without_receiving_new_orders():
    manager = MiningManager()
    units = [actor(10, "harv", 21, 20, idle=False, act="HarvestResource"),
             actor(11, "harv", 18, 20)]
    result = commands(manager, mining_view(units=units, ore=((21, 20), (21, 24))))
    assert result == [{"cmd": "harvest", "units": [11], "to": [21, 24]}]
    manager.mark_sent(result, 0)
    units[1].update(x=21, y=24, idle=False, act="HarvestResource")
    for now in (2, 8, 22, 50):
        assert commands(manager, mining_view(now, units=units, ore=((21, 20), (21, 24)))) == []


def test_departed_miner_releases_its_soft_reservation():
    manager = MiningManager()
    first = [actor(10, "harv", 21, 20, idle=False, act="HarvestResource")]
    assert commands(manager, mining_view(units=first, ore=((21, 20), (21, 24)))) == []
    second = [actor(10, "harv", 14, 20, idle=False, act="UnloadResources"),
              actor(11, "harv", 18, 20)]
    assert commands(manager, mining_view(4, units=second, ore=((21, 20), (21, 24)))) == [
        {"cmd": "harvest", "units": [11], "to": [21, 20]}]


def test_crowding_does_not_disable_the_only_safe_mine():
    units = [actor(10, "harv", 21, 20, idle=False, act="HarvestResource"),
             actor(11, "harv", 18, 20)]
    assert commands(MiningManager(), mining_view(units=units, ore=((21, 20),))) == [
        {"cmd": "harvest", "units": [11], "to": [21, 20]}]


def test_visible_transport_blockade_does_not_trigger_unsafe_automatic_harvest():
    manager = MiningManager()
    unit = actor(10, "harv", 15, 20)
    enemy = actor(50, "gun", 26, 20)
    for now in (0, 4, 12, 24):
        assert commands(manager, mining_view(now, units=[unit], ore=((35, 20),),
                                            enemies=[enemy])) == []
    assert commands(manager, mining_view(28, units=[unit], ore=((35, 20),))) == [
        {"cmd": "harvest", "units": [10], "to": [35, 20]}]


def test_blocked_route_falls_back_to_a_safe_other_mine():
    unit = actor(10, "harv", 15, 20)
    assert commands(MiningManager(), mining_view(units=[unit], ore=((35, 20), (12, 35)),
                    enemies=[actor(50, "gun", 26, 20)])) == [
        {"cmd": "harvest", "units": [10], "to": [12, 35]}]


def test_delivery_route_is_checked_after_idle_retry_budget_is_used():
    manager = MiningManager()
    unit = actor(10, "harv", 15, 20)
    for now in (0, 12):
        result = commands(manager, mining_view(now, units=[unit], ore=((35, 20),)))
        manager.mark_sent(result, now)
        assert result[0]["to"] == [35, 20]
    assert commands(manager, mining_view(24, units=[unit], ore=((35, 20),),
                    enemies=[actor(50, "gun", 26, 20)])) == []
    assert commands(manager, mining_view(28, units=[unit], ore=((35, 20),))) == [
        {"cmd": "harvest", "units": [10]}]


def test_unselected_miner_can_retry_on_next_observation():
    manager = MiningManager()
    units = [actor(10, "harv", 18, 20), actor(11, "harv", 18, 24)]
    result = commands(manager, mining_view(units=units))
    assert len(result) == 2
    manager.mark_sent(result[:1], 0)
    assert manager.units[10]["restore_tries"] == 1
    assert manager.units[11]["restore_tries"] == 0
    second = commands(manager, mining_view(.2, units=units))
    assert len(second) == 1 and second[0]["units"] == [11]


def test_unselected_retreat_retries_without_erasing_observed_damage():
    manager = MiningManager()
    units = [actor(10, "harv", 21, 20, idle=False)]
    result = commands(manager, mining_view(units=units, enemies=[actor(50, "2tnk", 24, 20)]))
    assert result[0]["cmd"] == "move"
    manager.mark_sent([], 0)
    units[0]["hp"] = 95
    retry = commands(manager, mining_view(.2, units=units, enemies=[actor(50, "2tnk", 24, 20)]))
    assert retry[0]["cmd"] == "move"
    assert manager.units[10]["hp"] == 95
    assert manager.units[10]["danger_at"] == .2


def test_unsent_far_redirect_does_not_consume_lifetime_opportunity():
    manager = MiningManager()
    assert commands(manager, mining_view(units=[actor(10, "harv", 32, 20, idle=False)])) == []
    result = commands(manager, mining_view(4, units=[actor(10, "harv", 36, 20, idle=False)]))
    assert result[0]["cmd"] == "harvest"
    manager.mark_sent([], 4)
    assert not manager.units[10].get("far_redirected")
    retry = commands(manager, mining_view(4.2, units=[actor(10, "harv", 36, 20, idle=False)]))
    assert retry[0]["cmd"] == "harvest"


def test_rejected_recovery_preserves_retreat_until_retry_is_sent():
    manager = MiningManager()
    target = retreat_then(manager)
    manager.mark_sent([{"cmd": "move", "units": [10], "to": target}], 0)
    unit = actor(10, "harv", *target, idle=False)
    recovery = commands(manager, mining_view(4, units=[unit]))
    manager.mark_sent(recovery, 4)
    assert not manager.units[10]["retreat"]
    manager.mark_failed(recovery[0], 4)
    assert manager.units[10]["retreat"]
    assert manager.units[10]["command_at"] == 0
    assert commands(manager, mining_view(4.2, units=[unit]))[0]["cmd"] == "harvest"


def test_late_failure_does_not_undo_a_newer_command():
    manager = MiningManager()
    unit = actor(10, "harv", 18, 20)
    first = commands(manager, mining_view(units=[unit]))
    manager.mark_sent(first, 0)
    second = commands(manager, mining_view(12, units=[unit]))
    manager.mark_sent(second, 12)
    manager.mark_failed(first[0], 0)
    assert manager.units[10]["command_at"] == 12
    assert manager.units[10]["restore_tries"] == 2
    assert commands(manager, mining_view(12.2, units=[unit])) == []


def test_dead_miners_do_not_retain_command_rollback_state():
    manager = MiningManager()
    result = commands(manager, mining_view(units=[actor(10, "harv", 18, 20)]))
    manager.mark_sent(result, 0)
    assert manager._issued
    commands(manager, mining_view(2, units=[]))
    assert manager.units == {} and manager._issued == {} and manager._offered == {}
