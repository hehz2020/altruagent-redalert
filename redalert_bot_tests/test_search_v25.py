from altru_redalert.combat import Military
from altru_redalert.core import Controller
from altru_redalert.model import View
from redalert_bot_tests.test_adversarial import actor, commands, snapshot
from redalert_bot_tests.test_v24_integration import accepted, legal_batch, mapped


def search_view(now, point=(20, 20), *, buildings=(), scout=None):
    army = [actor(10 + i, "2tnk", *point) for i in range(8)]
    if scout is not None:
        army.append(actor(99, "e1", *scout))
    raw = snapshot(now, units=army, enemy_buildings=buildings)
    raw["legal_actions"]["enemy_base"] = [80, 20]
    return View(raw, mapped())


def search_policy():
    military = Military()
    military.mode = "pressure"
    military.initial_spawn_checked = True
    military.sweep = [(40, 40), (60, 20)]
    military.visited[(80, 20)] = 400
    return military


def test_cleared_spawn_revisit_cannot_interrupt_unfinished_search():
    military = search_policy()
    first = search_view(400)
    assert military._goal(first, (20, 20)) == (40, 40)
    later = search_view(590, point=(25, 20))
    assert military._goal(later, (25, 20)) != (80, 20)


def test_active_search_does_not_change_to_new_nearest_region_midroute():
    military = search_policy()
    assert military._goal(search_view(400), (20, 20)) == (40, 40)
    assert military._goal(search_view(420, point=(42, 20)), (42, 20)) == (40, 40)


def test_arrival_by_a_scout_completes_region_before_main_army_arrives():
    military = search_policy()
    assert military._goal(search_view(400), (20, 20)) == (40, 40)
    next_view = search_view(420, scout=(40, 40))
    military._remember(next_view, next_view.units)
    assert military.visited[(40, 40)] == 420
    assert military._goal(next_view, (20, 20)) == (60, 20)


def test_reaching_search_region_selects_an_unvisited_region():
    military = search_policy()
    assert military._goal(search_view(400), (20, 20)) == (40, 40)
    arrived = search_view(425, point=(39, 40))
    military._remember(arrived, arrived.units)
    assert military._goal(arrived, (39, 40)) == (60, 20)


def test_new_visible_factory_immediately_interrupts_search():
    military = search_policy()
    assert military._goal(search_view(400), (20, 20)) == (40, 40)
    found = search_view(404, buildings=[actor(200, "weap", 70, 20)])
    military._remember(found, found.units)
    assert military._goal(found, (20, 20)) == (70, 20)
    assert military.search_goal is None


def test_stalled_search_is_deferred_and_can_be_retried():
    military = search_policy()
    assert military._goal(search_view(400), (20, 20)) == (40, 40)
    assert military._goal(search_view(440), (20, 20)) == (60, 20)
    assert (40, 40) not in military.visited
    assert military._goal(search_view(540), (20, 20)) == (40, 40)


def test_repeated_short_motion_cannot_hold_search_goal_forever():
    military = search_policy()
    assert military._goal(search_view(400), (20, 20)) == (40, 40)
    for now, point in ((420, (24, 20)), (440, (20, 24)), (460, (24, 24)),
                       (480, (20, 20)), (500, (24, 20))):
        assert military._goal(search_view(now, point), point) == (40, 40)
    assert military._goal(search_view(520, (20, 24)), (20, 24)) == (60, 20)


def test_changed_map_discards_search_goal_that_is_no_longer_reachable():
    military = search_policy()
    assert military._goal(search_view(400), (20, 20)) == (40, 40)
    raw = snapshot(404, units=[actor(10 + i, "2tnk", 20, 20) for i in range(8)])
    rows = ["." * 25 + "~" * 10 + "." * 61] * 96
    current = View(raw, mapped(rows))
    military._prepare_sweep(current)
    goal = military._goal(current, (20, 20))
    assert goal[0] < 29
    assert military.ground_routes.reachable((20, 20), goal)


def test_uninspected_enemy_spawn_remains_initial_objective():
    military = Military()
    military.sweep = [(40, 40), (60, 20)]
    assert military._goal(search_view(400), (20, 20)) == (80, 20)


def test_scout_near_spawn_cannot_start_cleanup_before_main_army_arrives():
    military = Military()
    military.sweep = [(40, 40), (60, 20)]
    current = search_view(400, scout=(79, 20))
    military._remember(current, current.units)
    assert (80, 20) not in military.visited
    assert military._goal(current, (20, 20)) == (80, 20)
    assert not military.initial_spawn_checked
    assert military.search_goal is None


def test_initial_spawn_does_not_time_out_while_main_army_is_regrouping():
    military = Military()
    military.sweep = [(40, 40), (60, 20)]
    for now in (30, 60, 90, 150, 300):
        assert military._goal(search_view(now), (20, 20)) == (80, 20)
        assert military.search_goal is None
        assert not military.search_deferred


def test_main_army_inspection_starts_cleanup_and_can_complete_a_later_spawn_revisit():
    military = Military()
    military.mode = "pressure"
    military.sweep = [(40, 40), (60, 20)]
    assert military._goal(search_view(400, (74, 20)), (74, 20)) == (60, 20)
    assert military.initial_spawn_checked
    assert military.visited[(80, 20)] == 400
    military.visited.update({(40, 40): 450, (60, 20): 460})
    assert military._goal(search_view(470, (40, 40)), (40, 40)) == (80, 20)
    assert military._goal(search_view(490, (74, 20)), (74, 20)) == (40, 40)


def test_search_timeouts_pause_while_regrouping_or_retreating():
    for mode in ("regroup", "retreat", "defend", "standoff"):
        military = search_policy()
        assert military._goal(search_view(400), (20, 20)) == (40, 40)
        military._set_mode(mode, 410)
        for now in (420, 450, 550, 650):
            assert military._goal(search_view(now), (20, 20)) == (40, 40)
            assert not military.search_deferred
        military._set_mode("pressure", 650)
        assert military._goal(search_view(679), (20, 20)) == (40, 40)
        assert military._goal(search_view(681), (20, 20)) == (60, 20)


def test_search_timeouts_pause_without_a_main_army():
    for units in ([], [actor(99, "e1", 20, 20)]):
        military = search_policy()
        idle = View(snapshot(800, units=units), mapped())
        military._prepare_sweep(idle)
        military.initial_spawn_checked = True
        military.sweep = [(40, 40), (60, 20)]
        assert military._goal(search_view(400), (20, 20)) == (40, 40)
        military.propose(idle)
        assert military.search_goal == (40, 40)
        assert military.search_progress_at == 800
        assert military.search_deadline > 800
        assert military._goal(search_view(801), (20, 20)) == (40, 40)


def test_search_pauses_when_every_tank_withdraws_and_resumes_afterward():
    military, config = Military(), mapped()
    army = [dict(actor(10 + i, "2tnk", 50, 50), hp=20) for i in range(8)]
    first = View(snapshot(400, units=army, enemies=[actor(300, "e1", 54, 50)]), config)
    military._prepare_sweep(first)
    military.initial_spawn_checked = True
    military.mode = "pressure"
    military.visited[tuple(first.enemy_base)] = 390
    for now in (400, 410, 420, 431):
        current = View(snapshot(now, units=army, enemies=[actor(300, "e1", 54, 50)]), config)
        orders = military.propose(current)
        assert orders
        assert all(order.key.startswith("military:wounded") for order in orders)
        assert military.search_goal == (40, 40)
        assert military.search_progress_at == now
        assert not military.search_deferred
    for now in (432, 460):
        orders = military.propose(View(snapshot(now, units=army), config))
        assert any(order.key.startswith("military:pressure") for order in orders)
        assert military.search_goal == (40, 40)
    military.propose(View(snapshot(462, units=army), config))
    assert military.search_goal != (40, 40)
    assert military.search_deferred[(40, 40)] > 462


def test_search_pauses_while_all_units_fire_and_resumes_afterward():
    military, config = Military(), mapped()
    army = [dict(actor(10 + i, "2tnk", 50, 50), hp=20) for i in range(8)]
    first = View(snapshot(400, units=army, enemies=[actor(300, "arty", 54, 50)]), config)
    military._prepare_sweep(first)
    military.initial_spawn_checked = True
    military.mode = "pressure"
    military.visited[tuple(first.enemy_base)] = 390
    for now in (400, 410, 420, 431):
        current = View(snapshot(now, units=army, enemies=[actor(300, "arty", 54, 50)]), config)
        orders = military.propose(current)
        assert orders
        assert all(order.key.startswith("military:fire") for order in orders)
        assert military.search_goal == (40, 40)
        assert military.search_progress_at == now
        assert not military.search_deferred
    for now in (432, 460):
        orders = military.propose(View(snapshot(now, units=army), config))
        assert any(order.key.startswith("military:pressure") for order in orders)
        assert military.search_goal == (40, 40)
    military.propose(View(snapshot(462, units=army), config))
    assert military.search_goal != (40, 40)
    assert military.search_deferred[(40, 40)] > 462


def test_controller_enemy_contact_overrides_search_goal_hysteresis():
    bot, config = Controller(), mapped()
    army = [actor(10 + i, "2tnk", 30, 30) for i in range(8)]
    bot.military.visited[(60, 30)] = 400
    first_raw = snapshot(400, units=army)
    bot.military._prepare_sweep(View(first_raw, config))
    bot.military.initial_spawn_checked = True
    first = commands(bot.decide(first_raw, config))
    assert bot.military.army_goal == (40, 40)
    accepted(bot, first)
    next_raw = snapshot(404, units=army, enemy_buildings=[actor(200, "weap", 44, 42)])
    result = commands(bot.decide(next_raw, config))
    legal_batch(next_raw, config, result)
    assert bot.military.army_goal == (44, 42)
    assert bot.military.search_goal is None
