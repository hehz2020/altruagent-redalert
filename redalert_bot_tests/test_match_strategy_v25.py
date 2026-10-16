from copy import deepcopy

from altru_redalert.combat import Military
from altru_redalert.core import Controller, validate_order
from altru_redalert.model import View, distance
from altru_redalert.tactics import force_ratio
from redalert_bot_tests.test_adversarial import actor, commands, snapshot
from redalert_bot_tests.test_v24_integration import accepted, legal_batch, mapped


def tanks(count=8, x=40, y=30):
    return [actor(10+i, "2tnk", x+i % 2, y+i // 2) for i in range(count)]


def test_late_lead_replaces_existing_attack_and_stops_new_raid():
    bot, config = Controller(), mapped()
    army = tanks(16)
    enemy = [actor(200, "harv", 70, 50)]
    buildings = [actor(1, "fact", 12, 12), actor(2, "proc", 18, 15)]
    before = snapshot(1100, units=army, buildings=buildings, enemies=enemy,
                      remaining=100, kills=5000, deaths=1000)
    first = commands(bot.decide(before, config))
    assert any(o["cmd"] == "attack_move" for o in first)
    accepted(bot, first)
    after = snapshot(1112, units=army, buildings=buildings, enemies=enemy,
                     remaining=88, kills=5000, deaths=1000)
    result = commands(bot.decide(after, config))
    legal_batch(after, config, result)
    assert bot.military.mode == "protect-lead"
    assert not bot.military.raid_ids
    assert bot.military.commit_until == 0
    returns = {uid for o in result if o["cmd"] == "move" and o["to"][0] < 40
               for uid in o["units"]}
    assert returns == {a["id"] for a in army}


def test_losing_the_late_lead_resumes_pressure_without_waiting_for_old_commit():
    bot, config, army = Controller(), mapped(), tanks()
    buildings = [actor(1, "fact", 12, 12)]
    raw = snapshot(1140, units=army, buildings=buildings, remaining=60,
                   kills=6000, deaths=2000)
    accepted(bot, commands(bot.decide(raw, config)))
    raw = snapshot(1144, units=army, buildings=buildings, remaining=56,
                   kills=6000, deaths=6500)
    orders = commands(bot.decide(raw, config))
    assert bot.military.mode == "pressure"
    assert any(o["cmd"] == "attack_move" and o["to"][0] > 40 for o in orders)


def test_missing_score_or_tied_score_never_assumes_lead():
    military = Military()
    raw = snapshot(1140, units=tanks(), remaining=60, kills=2000, deaths=2000)
    assert not military._protect_lead(View(raw))
    raw["observation"]["military"] = {"assets_value": 100000}
    assert not military._protect_lead(View(raw))
    raw["observation"]["military"] = {"kills_cost": 5000}
    assert not military._protect_lead(View(raw))


def test_protecting_lead_does_not_ignore_immediate_miner_attack():
    army = tanks(8, 50, 50) + [actor(30, "2tnk", 22, 20), actor(31, "harv", 24, 20)]
    raw = snapshot(1150, units=army, buildings=[actor(1, "proc", 18, 20)],
                   enemies=[actor(100, "jeep", 27, 20)], remaining=50,
                   kills=6000, deaths=2000)
    bot = Controller()
    orders = commands(bot.decide(raw, mapped()))
    escort = [o for o in orders if 30 in o.get("units", [])]
    assert escort and escort[0]["cmd"] in {"attack", "attack_move"}
    assert bot.military.mode == "protect-lead"


def test_recent_fog_contact_not_erased_or_double_counted():
    military, army = Military(), tanks()
    enemy = actor(100, "3tnk", 45, 30)
    view = View(snapshot(400, units=army, enemies=[enemy]))
    military._remember(view, army)
    assert len(military._nearby_threats(view, [enemy], (40, 30))) == 1
    fog = View(snapshot(403, units=army))
    assert len(military._nearby_threats(fog, [], (40, 30))) == 1
    stale = View(snapshot(409, units=army))
    assert military._nearby_threats(stale, [], (40, 30)) == []


def test_fog_contact_changes_survival_decision_but_is_never_attack_id():
    military, army = Military(), tanks(3, 20, 30)
    enemies = [actor(100+i, "3tnk", 40, 30+i % 3) for i in range(10)]
    first = View(snapshot(400, units=army, enemies=enemies))
    military.propose(first)
    forward = [{**a, "x": 30} for a in army]
    later = View(snapshot(403, units=forward))
    result = military.propose(later)
    assert military.mode == "retreat"
    assert not any(i.order.get("target") in {e["id"] for e in enemies} for i in result)
    assert all(validate_order(i.order, later) is not None for i in result)


def test_remote_exposed_refinery_beats_nearer_heavily_defended_factory():
    army = tanks(6, 35, 30)
    factory, refinery = actor(200, "weap", 54, 30), actor(201, "proc", 55, 65)
    towers = [actor(210+i, "tsla", 50+i % 2, 28+i) for i in range(5)]
    view = View(snapshot(500, units=army, enemy_buildings=[factory, refinery]+towers), mapped())
    assert Military()._goal(view, (35, 31), army) == (55, 65)


def test_clear_local_superiority_still_attacks_and_does_not_hide_behind_fog_rule():
    army = [actor(10+i, "3tnk", 45, 30+i % 3) for i in range(8)]
    enemies = [actor(100+i, "e1", 49, 30+i) for i in range(2)]
    view = View(snapshot(500, units=army, enemies=enemies,
                         enemy_buildings=[actor(200, "weap", 55, 31)]))
    military = Military()
    orders = military.propose(view)
    assert military.mode == "pressure"
    assert not any(i.order["cmd"] == "move" and i.order["to"][0] < 45 for i in orders)
    assert any(i.order["cmd"] in {"attack", "attack_move"} for i in orders)


def test_one_rocket_does_not_magically_double_an_infantry_army_against_armor():
    rifles = [actor(10+i, "e1", 30, 30+i % 3) for i in range(30)]
    enemy = [actor(100+i, "3tnk", 34, 30+i % 3) for i in range(7)]
    view = View(snapshot(500, units=rifles, enemies=enemy))
    before = force_ratio(view, rifles, enemy)
    after = force_ratio(view, rifles+[actor(70, "e3", 30, 30)], enemy)
    assert before < 1.0 and after < 1.0
    assert after < before * 1.5
