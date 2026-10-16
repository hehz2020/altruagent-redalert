from altru_redalert.combat import Military
from altru_redalert.model import View
from redalert_bot_tests.test_development_v22 import development_view, purchases
from redalert_bot_tests.test_economy_v2 import actor


def test_second_refinery_precedes_factory_without_a_light_vehicle_requirement():
    v = development_view(seconds=55, cash=1400, factory=False, vehicle=False)
    assert purchases(v) == [{"cmd": "build", "item": "proc"}]


def test_first_combat_escort_precedes_an_uncommitted_third_miner():
    # v26 deliberately covers the vulnerable depot/third-miner interval first.
    # Once that single escort exists, the third miner keeps its exact-price goal.
    for cash in (599, 600, 1099, 1100):
        v = development_view(seconds=140, cash=cash, harvesters=2,
                             refineries=2, vehicle=False)
        expected = [] if cash < 600 else [{"cmd": "train", "item": "ftrk"}]
        if cash >= 900:
            expected.append({"cmd": "train", "item": "e3"})
        assert purchases(v) == expected
    v = development_view(seconds=141, cash=1100, harvesters=2, refineries=2, vehicle=True)
    assert purchases(v) == [{"cmd": "train", "item": "harv"}]


def test_queued_third_miner_allows_parallel_tank_technology_before_150_seconds():
    v = development_view(seconds=140, cash=2300, harvesters=2, refineries=2,
                         vehicle=False, pending=[{"cmd": "train", "item": "harv"}])
    assert purchases(v) == [{"cmd": "build", "item": "fix"}]


def test_exact_first_heavy_tank_funds_survive_infantry_and_car_choices():
    for cash, expected in ((1149, []), (1150, [{"cmd": "train", "item": "3tnk"}])):
        v = development_view(seconds=190, cash=cash, harvesters=3, refineries=2,
                             repair_shop=True, vehicle=False)
        assert purchases(v) == expected


def test_three_tanks_unlock_protected_fourth_miner():
    v = development_view(seconds=280, cash=1100, harvesters=3, refineries=2,
                         repair_shop=True, vehicle=False)
    v.raw["observation"]["units"] += [actor(70 + i, "3tnk") for i in range(3)]
    v = View(v.raw, v.config)
    assert purchases(v) == [{"cmd": "train", "item": "harv"}]


def test_opening_armor_waits_together_but_local_home_defense_still_fires():
    def army_view(tanks, enemies=()):
        v = development_view(seconds=240, harvesters=3, refineries=2,
                             repair_shop=True, vehicle=False, enemies=enemies)
        v.raw["observation"]["units"] += [actor(70 + i, "3tnk", 13, 12 + i) for i in range(tanks)]
        return View(v.raw, v.config)
    one = Military()
    one.propose(army_view(1))
    assert one.mode == "regroup"
    three = Military()
    three.propose(army_view(3))
    assert three.mode == "pressure"
    attacked = Military()
    result = attacked.propose(army_view(1, [actor(90, "e1", 13, 14)]))
    assert any(i.order["cmd"] in {"attack", "attack_move"} for i in result)
