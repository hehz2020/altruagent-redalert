from copy import deepcopy

from altru_redalert.core import Controller, validate_order
from altru_redalert.model import Intent, View
from redalert_bot_tests.test_controller import actor, state, orders


def test_ready_vehicle_is_never_a_building_placement():
    raw = state(units=[actor(1, "e1")], production=[
        {"queue": "Vehicle", "item": "1tnk", "ready": True, "progress": 1}])
    raw["legal_actions"]["place"] = []
    assert View(raw).ready_to_place() == set()
    assert validate_order({"cmd": "place", "item": "1tnk"}, View(raw)) is None
    del raw["legal_actions"]["place"]
    assert View(raw).ready_to_place() == set()
    assert validate_order({"cmd": "place", "item": "1tnk"}, View(raw)) is None


def test_explicit_empty_place_list_overrides_stale_ready_structure():
    raw = state(production=[{"queue": "Building", "item": "powr", "ready": True}])
    raw["legal_actions"]["place"] = []
    assert validate_order({"cmd": "place", "item": "powr"}, View(raw)) is None
    raw["legal_actions"]["place"] = ["powr"]
    assert validate_order({"cmd": "place", "item": "powr"}, View(raw)) is not None


def test_partial_batch_observation_keeps_only_unrepresented_reservation():
    class Producer:
        pending = []
        def propose(self, view):
            self.pending = deepcopy(view.pending_orders)
            return [Intent({"cmd": "train", "item": "e1", "count": 5}, cooldown=0)]
    class NoMilitary:
        def propose(self, view):
            return []
        def mark_sent(self, batch, now):
            pass
    c = Controller()
    producer = Producer()
    c.economy, c.military = producer, NoMilitary()
    assert orders(c.decide(state(0, train=["e1"])), "train")[0]["count"] == 5
    assert not orders(c.decide(state(5, train=["e1"], production=[
        {"queue": "Infantry", "item": "e1", "progress": .1}])), "train")
    assert producer.pending == [{"cmd": "train", "item": "e1", "count": 4}]
    assert not orders(c.decide(state(250, train=["e1"], units=[actor(9, "e1")],
        production=[{"queue": "Infantry", "item": "e1", "progress": .5}])), "train")
    assert producer.pending == [{"cmd": "train", "item": "e1", "count": 3}]
    assert c.stats["unconfirmed_expiries"] == 0
    c.decide(state(300, train=["e1"], units=[actor(9, "e1"), actor(10, "e1")],
        production=[{"queue": "Infantry", "item": "e1", "count": 3, "progress": .1}]))
    assert not producer.pending
    assert c.stats["observed_confirmations"] == 1


def test_platform_deploy_list_and_target_ids_are_authoritative():
    raw = state(units=[actor(1, "mcv"), actor(2, "mcv")], buildings=[actor(5, "fact")])
    raw["legal_actions"]["deploy"] = [{"id": 2}, {"id": []}]
    view = View(raw)
    assert validate_order({"cmd": "deploy", "units": [1, 2]}, view)["units"] == [2]
    assert validate_order({"cmd": "repair", "building": [], "on": True}, view) is None
    assert validate_order({"cmd": "guard", "units": [1], "target": []}, view) is None


def test_server_engine_command_limit_is_honored():
    class NoEconomy:
        def propose(self, view):
            return []
    class MoveArmy:
        def propose(self, view):
            return [Intent({"cmd": "attack_move", "units": [a["id"] for a in view.units],
                            "to": [64, 12]})]
        def mark_sent(self, batch, now):
            pass
    c = Controller()
    c.economy, c.military = NoEconomy(), MoveArmy()
    raw = state(units=[actor(i, "e1") for i in range(1, 101)])
    raw["limits"] = {"max_units_per_order": 20, "max_engine_commands_per_batch": 40}
    batch = orders(c.decide(raw))
    assert sum(len(o["units"]) for o in batch) == 40


def test_cancel_waits_for_smaller_queue_before_cancelling_next_unit():
    class Cancel:
        def propose(self, view):
            return [Intent({"cmd": "cancel", "item": "1tnk"}, cooldown=0)]
    class Empty:
        def propose(self, view):
            return []
        def mark_sent(self, batch, now):
            pass
    c = Controller()
    c.economy, c.military = Cancel(), Empty()
    queued = [{"queue": "Vehicle", "item": "1tnk", "count": 2, "progress": .1}]
    assert orders(c.decide(state(0, production=queued)), "cancel")
    c.on_result({"results": [{"index": 0, "status": "ok"}]})
    assert not orders(c.decide(state(5, production=queued)), "cancel")
    queued[0]["count"] = 1
    assert orders(c.decide(state(10, production=queued)), "cancel")
    assert c.stats["observed_confirmations"] == 1
