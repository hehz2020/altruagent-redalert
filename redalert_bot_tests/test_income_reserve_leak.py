import pytest

from altru_redalert.economy import Economy
from redalert_bot_tests.test_economy_v2 import actor, view


def no_income_view(cash, *, production=(), pending=()):
    return view(cash=cash, units=[actor(i, "e1") for i in range(30, 34)],
                train=["harv", "e1", "e3"], production=production, pending=pending)


def purchases(v):
    return [intent.order for intent in Economy().propose(v)
            if intent.order["cmd"] in {"build", "train"}]


@pytest.mark.parametrize("cash", [300, 950, 1099])
def test_unaffordable_emergency_harvester_keeps_all_income_recovery_funds(cash):
    assert purchases(no_income_view(cash)) == []


@pytest.mark.parametrize("cash, rockets", [(1100, 0), (1400, 1), (1700, 2)])
def test_successful_emergency_harvester_leaves_its_real_surplus_available(cash, rockets):
    v = no_income_view(cash)
    result = purchases(v)
    expected = [{"cmd": "train", "item": "harv"}]
    if rockets:
        expected.append({"cmd": "train", "item": "e3", **({"count": rockets} if rockets > 1 else {})})
    assert result == expected
    assert sum(v.cost(o["item"]) * o.get("count", 1) for o in result) == cash


@pytest.mark.parametrize("production,pending,cash", [
    ([{"item": "harv", "queue": "Vehicle", "count": 1, "progress": .5}], [], 850),
    ([], [{"cmd": "train", "item": "harv"}], 1400),
])
def test_incoming_harvester_reserves_only_its_existing_queue_or_request(production, pending, cash):
    v = no_income_view(cash, production=production, pending=pending)
    assert purchases(v) == [{"cmd": "train", "item": "e3"}]


@pytest.mark.parametrize("production,pending,cash", [
    ([{"item": "proc", "queue": "Building", "count": 1, "progress": .5}], [], 2100),
    ([], [{"cmd": "build", "item": "proc"}], 2800),
])
def test_existing_refinery_commitment_is_not_reserved_a_second_time(production, pending, cash):
    v = no_income_view(cash, production=production, pending=pending)
    assert purchases(v) == [{"cmd": "train", "item": "harv"},
                            {"cmd": "train", "item": "e3"}]


def test_pending_recovery_and_infantry_requests_are_not_duplicated():
    v = no_income_view(1700, pending=[{"cmd": "train", "item": "harv"},
                                     {"cmd": "train", "item": "e3", "count": 2}])
    assert purchases(v) == []
