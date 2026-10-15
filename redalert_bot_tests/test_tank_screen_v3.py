from altru_redalert.economy import Economy, _reserved
from altru_redalert.model import View
from redalert_bot_tests.test_development_v22 import development_view, purchases, purchase_cost
from redalert_bot_tests.test_economy_v2 import actor


def screen_view(*, tanks=3, rifles=4, harvesters=4, cash=1150,
                allied=False, production=(), pending=(), enemies=()):
    v = development_view(seconds=350, cash=cash, harvesters=harvesters,
                         refineries=2, repair_shop=True, vehicle=False,
                         production=production, pending=pending, enemies=enemies)
    v.raw["observation"]["units"] = [u for u in v.units if u["type"] != "e1"]
    v.raw["observation"]["units"] += [actor(50+i, "e1") for i in range(rifles)]
    v.raw["observation"]["units"] += [actor(70+i, "2tnk" if allied else "3tnk")
                                      for i in range(tanks)]
    if allied:
        v.raw["legal_actions"]["train"] = ["e1", "e3", "harv", "2tnk", "jeep"]
    return View(v.raw, v.config, list(pending))


def test_first_three_tanks_are_unchanged_but_next_slot_gets_a_legal_screen_car():
    policy = Economy()
    assert purchases(screen_view(tanks=2, rifles=0), policy) == [
        {"cmd": "train", "item": "3tnk"}]
    assert purchases(screen_view(cash=599), policy) == []
    assert purchases(screen_view(cash=600), policy) == [
        {"cmd": "train", "item": "ftrk"}]
    assert purchases(screen_view(allied=True, cash=500)) == [
        {"cmd": "train", "item": "jeep"}]


def test_fourth_miner_keeps_the_original_priority_over_the_screen_car():
    assert purchases(screen_view(harvesters=3, cash=1100)) == [
        {"cmd": "train", "item": "harv"}]


def test_observed_core_milestone_restores_three_rifles_after_losses():
    policy = Economy()
    purchases(screen_view(cash=0), policy)
    damaged = screen_view(tanks=2, rifles=0, cash=1175)
    result = purchases(damaged, policy)
    assert result == [{"cmd": "train", "item": "e1", "count": 3}]
    assert purchase_cost(damaged, result) == 300
    waiting = screen_view(tanks=2, rifles=0, cash=1175, pending=result)
    next_orders = purchases(waiting, policy)
    assert next_orders == [{"cmd": "train", "item": "ftrk"}]
    assert purchase_cost(waiting, next_orders) + _reserved(waiting) <= waiting.funds


def test_queued_screen_car_is_counted_and_its_unpaid_cost_is_not_reused():
    v = screen_view(cash=1450, production=[
        {"item": "ftrk", "queue": "Vehicle", "progress": .5}])
    assert purchases(v) == []
    pending = screen_view(cash=1150, pending=[{"cmd": "train", "item": "ftrk"}])
    assert purchases(pending) == []


def test_lost_income_recovery_has_priority_even_after_the_core_milestone():
    policy = Economy()
    purchases(screen_view(cash=0), policy)
    v = screen_view(tanks=2, rifles=0, harvesters=0, cash=950)
    assert purchases(v, policy) == []
    v = screen_view(tanks=2, rifles=0, harvesters=0, cash=1100)
    assert purchases(v, policy) == [{"cmd": "train", "item": "harv"}]


def test_visible_close_attack_still_releases_development_savings():
    policy = Economy()
    purchases(screen_view(cash=0), policy)
    v = screen_view(tanks=2, rifles=0, cash=300,
                    enemies=[actor(90, "2tnk", 13, 12), actor(91, "2tnk", 14, 12)])
    result = purchases(v, policy)
    assert result == [{"cmd": "train", "item": "e3"}]
