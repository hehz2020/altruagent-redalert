"""Development spending contracts for the frozen macro candidate.

These scripted player-view scenarios test affordability, recovery and request
reconciliation. They contain no match logs and do not establish a win rate.
"""

from copy import deepcopy

import pytest

from altru_redalert.economy import Economy
from altru_redalert.model import View
from redalert_bot_tests.test_economy_v2 import actor, view


def development_view(*, cash=900, seconds=200, harvesters=1, refineries=1,
                     factory=True, repair_shop=False, vehicle=True,
                     enemies=(), production=(), pending=(), power_surplus=280):
    """A small defensive opening, with legal production matching its tech."""
    buildings = [actor(1, "fact", 10, 10), actor(2, "powr"), actor(3, "tent")]
    buildings += [actor(4 + i, "proc", 14 + 3 * i, 10) for i in range(refineries)]
    if factory:
        buildings.append(actor(10, "weap", 12, 12))
    if repair_shop:
        buildings.append(actor(11, "fix", 10, 14))
    units = [actor(20 + i, "harv", idle=False) for i in range(harvesters)]
    units += [actor(30 + i, "e1") for i in range(4)]
    if vehicle:
        units.append(actor(40, "ftrk"))
    train = ["e1", "e3"]
    if factory:
        train += ["harv", "ftrk"]
    if repair_shop:
        train.append("3tnk")
    build = ["powr", "proc"]
    build.append("fix" if factory else "weap")
    initial = view(seconds, cash=cash, units=units, buildings=buildings,
                   train=train, build=build, enemies=enemies,
                   production=production, pending=pending)
    reference = deepcopy(initial.config)
    # Public heavy-tank price, rather than an invented cheap fallback. Queue
    # entries below use the platform's item/count/progress representation.
    reference["rules"]["units"]["3tnk"] = {"cost": 1150, "queue": "Vehicle"}
    initial.raw["observation"]["economy"].update(
        power_provided=120 + power_surplus, power_drained=120)
    return View(initial.raw, reference, list(pending))


def purchases(v, policy=None):
    return [intent.order for intent in (policy or Economy()).propose(v)
            if intent.order["cmd"] in {"build", "train"}]


def purchase_cost(v, orders):
    return sum(v.cost(order["item"]) * order.get("count", 1) for order in orders)


def test_single_harvester_keeps_income_packets_for_the_second_harvester():
    policy = Economy()
    # Legal cheap units must not consume each packet before 1100 is reached.
    for seconds, cash in ((200, 600), (205, 900), (210, 1099)):
        assert purchases(development_view(seconds=seconds, cash=cash), policy) == []
    v = development_view(seconds=215, cash=1100)
    assert purchases(v, policy) == [{"cmd": "train", "item": "harv"}]


def test_factory_savings_allow_prerequisite_power_then_the_factory():
    policy = Economy()
    low_power = development_view(cash=300, factory=False, vehicle=False, power_surplus=0)
    assert purchases(low_power, policy) == [{"cmd": "build", "item": "powr"}]
    # A fresh observation confirms the extra power and enough accumulated cash.
    powered = development_view(seconds=220, cash=2000, factory=False,
                               vehicle=False, power_surplus=100)
    powered.buildings.append(actor(12, "powr", 9, 14))
    assert purchases(powered, policy) == [{"cmd": "build", "item": "weap"}]


def test_two_harvesters_can_fund_the_second_refinery_at_its_exact_price():
    policy = Economy()
    assert purchases(development_view(cash=1399, harvesters=2), policy) == []
    ready = development_view(seconds=205, cash=1400, harvesters=2)
    assert purchases(ready, policy) == [{"cmd": "build", "item": "proc"}]


def test_two_refineries_can_fund_the_repair_shop_without_surplus_padding():
    policy = Economy()
    assert purchases(development_view(cash=1199, harvesters=2, refineries=2), policy) == []
    ready = development_view(seconds=205, cash=1200, harvesters=2, refineries=2)
    assert purchases(ready, policy) == [{"cmd": "build", "item": "fix"}]


def test_first_heavy_tank_uses_the_public_1150_cost_boundary():
    policy = Economy()
    poor = development_view(cash=1149, harvesters=2, refineries=2, repair_shop=True)
    assert poor.cost("3tnk") == 1150
    assert purchases(poor, policy) == []
    ready = development_view(seconds=205, cash=1150, harvesters=2,
                             refineries=2, repair_shop=True)
    result = purchases(ready, policy)
    assert result == [{"cmd": "train", "item": "3tnk"}]
    assert purchase_cost(ready, result) == ready.funds


def test_substantial_close_threat_releases_savings_but_a_scout_does_not():
    scout = [actor(90, "e1", 18, 12)]
    distant_armor = [actor(90, "2tnk", 29, 12)]
    assert purchases(development_view(enemies=scout)) == []
    assert purchases(development_view(enemies=distant_armor)) == []
    for attackers in ([actor(90, "2tnk", 20, 12)],
                      scout + [actor(91, "e1", 19, 12)]):
        threatened = development_view(enemies=attackers)
        result = purchases(threatened)
        assert any(order["cmd"] == "train" and order["item"] in {"ftrk", "e1", "e3"}
                   for order in result)
        assert all(order["item"] != "harv" for order in result)
        assert purchase_cost(threatened, result) <= threatened.funds


def test_stalled_income_releases_defense_budget_after_45_seconds_for_20_seconds():
    policy = Economy()
    assert purchases(development_view(seconds=200), policy) == []
    assert purchases(development_view(seconds=244.99), policy) == []
    # Proposals are inspected without submitting them; cash and queues remain
    # unchanged so this isolates the duration of the defensive spending window.
    for seconds in (245, 264.99):
        v = development_view(seconds=seconds)
        result = purchases(v, policy)
        assert any(order["cmd"] == "train" and order["item"] != "harv" for order in result)
        assert purchase_cost(v, result) <= v.funds
    assert purchases(development_view(seconds=265), policy) == []


def test_real_income_progress_resets_the_stalled_savings_timer():
    policy = Economy()
    assert purchases(development_view(seconds=200, cash=900), policy) == []
    assert purchases(development_view(seconds=244, cash=950), policy) == []
    # The original 245-second timeout is no longer a reason to spend the fund.
    assert purchases(development_view(seconds=245, cash=950), policy) == []
    assert purchases(development_view(seconds=288.99, cash=950), policy) == []
    assert purchases(development_view(seconds=289, cash=950), policy)


def test_unconfirmed_development_orders_are_reserved_and_never_duplicated():
    policy = Economy()
    pending_harvester = {"cmd": "train", "item": "harv"}
    waiting = development_view(cash=2500, pending=[pending_harvester])
    result = purchases(waiting, policy)
    assert result == [{"cmd": "build", "item": "proc"}]
    assert 1100 + purchase_cost(waiting, result) <= waiting.funds
    # Neither uncertain request can be repeated or treated as refunded money.
    both_pending = development_view(seconds=205, cash=2500,
                                    pending=[pending_harvester, *result])
    assert purchases(both_pending, policy) == []
    # A later confirmed view advances to the next development step.
    confirmed = development_view(seconds=230, cash=1200, harvesters=2, refineries=2)
    assert purchases(confirmed, policy) == [{"cmd": "build", "item": "fix"}]


@pytest.mark.parametrize("cash", [2874, 2875, 2975, 3475])
def test_heavy_tank_queue_tails_and_pending_infantry_cannot_be_spent_twice(cash):
    production = [{"queue": "Vehicle", "item": "3tnk", "count": 3, "progress": .5}]
    v = development_view(cash=cash, harvesters=2, refineries=2,
                         repair_shop=True, production=production)
    result = purchases(v)
    unpaid_tanks = 1150 * 2.5
    assert purchase_cost(v, result) <= max(0, cash - unpaid_tanks)
    assert all(v.queue(order["item"]) != "Vehicle" for order in result)
    if cash == 3475:
        assert result == [{"cmd": "train", "item": "e3", "count": 2}]
        pending = development_view(seconds=205, cash=cash, harvesters=2,
                                   refineries=2, repair_shop=True,
                                   production=production, pending=result)
        assert purchases(pending) == []
