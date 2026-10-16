"""Independent adversarial review cases for v2.5 military decisions."""

from altru_redalert.combat import Military
from altru_redalert.tactics import force_ratio
from redalert_bot_tests.test_adversarial import actor, snapshot
from redalert_bot_tests.test_tank_cohesive_v3 import mapped


def test_entering_remembered_static_fire_starts_a_current_retreat():
    military = Military()
    army = [actor(10 + i, "2tnk", 36, 30 + i) for i in range(3)]
    # The towers were observed while this squad was elsewhere. They are still
    # credible hazards, but none is a currently visible attack target.
    military.contacts = {
        100 + i: (actor(100 + i, "tsla", 40, 28 + i), 400, True)
        for i in range(6)
    }
    view = mapped(snapshot(420, units=army,
                           enemy_buildings=[actor(200, "proc", 80, 30)]))
    military.mark_sent([{"cmd": "attack", "units": [10, 11, 12], "target": 200}], 419)
    orders = [intent.order for intent in military.propose(view)]
    assert military.last_ratio < .8
    assert military.mode == "retreat"
    assert military.retreat_until > view.now
    assert {uid for order in orders if order["cmd"] == "move"
            for uid in order["units"]} == {10, 11, 12}
    assert not any(order.get("target") in military.contacts for order in orders)


def test_expired_static_memory_does_not_keep_the_army_withdrawing():
    military = Military()
    army = [actor(10 + i, "2tnk", 36, 30 + i) for i in range(3)]
    military.contacts = {
        100 + i: (actor(100 + i, "tsla", 40, 28 + i), 400, True)
        for i in range(6)
    }
    for now in (420, 440, 446):
        view = mapped(snapshot(now, units=army,
                               enemy_buildings=[actor(200, "proc", 80, 30)]))
        military.propose(view)
    assert military.mode == "pressure"
    assert military.retreat_until <= view.now


def test_raid_keeps_the_tanks_needed_to_face_a_nearby_enemy_army():
    military = Military()
    army = [actor(10 + i, "2tnk", 20, 30 + i % 3) for i in range(5)]
    army += [actor(30 + i, "e1", 20, 30 + i % 3) for i in range(10)]
    enemy_army = [actor(100 + i, "3tnk", 35, 30 + i % 3) for i in range(5)]
    view = mapped(snapshot(400, units=army,
                           enemies=enemy_army + [actor(200, "harv", 20, 60)]))
    assert force_ratio(view, army, enemy_army) > 1.35
    military.propose(view)
    assert not military.raid_ids
    assert military.mode != "retreat"
