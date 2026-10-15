from copy import deepcopy
import unittest

from altru_redalert.core import Controller, validate_order
from altru_redalert.model import View


def actor(ident, kind, x=12, y=12, **extra):
    return dict(id=ident, type=kind, x=x, y=y, hp=100, idle=True, **extra)


def snapshot(seconds=1, *, buildings=(), units=(), cash=5000,
             build=(), train=(), production=(), enemies=(), enemy_buildings=(),
             remaining=1199, kills=0, deaths=0):
    return {
        "session_id": "scenario", "game_type": "red_alert", "phase": "playing",
        "state_version": int(seconds * 25), "is_current_actor": True,
        "is_terminal": False,
        "time": {"game_seconds": seconds, "remaining_seconds": remaining},
        "map": {"id": "scenario-map", "bounds": [4, 4, 96, 96]},
        "observation": {
            "tick": int(seconds * 25), "base_center": [12, 12],
            "units": list(units), "buildings": list(buildings),
            "visible_enemies": list(enemies), "visible_enemy_buildings": list(enemy_buildings),
            "production": list(production), "available_production": list(build) + list(train),
            "economy": {"cash": cash, "ore": 0, "power_provided": 200, "power_drained": 80},
            "military": {"kills_cost": kills, "deaths_cost": deaths},
        },
        "legal_actions": {"build": list(build), "train": list(train),
                          "place": [p["item"] for p in production if p.get("ready")],
                          "enemy_base": [60, 30]},
        "limits": {"max_orders_per_batch": 20, "max_units_per_order": 50, "max_train_count": 10},
    }


def commands(result):
    return result.get("orders", []) if result else []


class ProductionRecoveryScenarios(unittest.TestCase):
    def setUp(self):
        self.buildings = [actor(1, "fact"), actor(2, "powr"), actor(3, "tent"), actor(4, "proc")]

    def test_last_harvester_lost_before_factory_does_not_spend_bank_on_factory(self):
        state = snapshot(80, buildings=self.buildings, cash=2000,
                         build=["powr", "proc", "weap"], train=["e1", "harv"])
        result = commands(Controller().decide(state))
        self.assertIn({"cmd": "train", "item": "harv"}, result)
        self.assertNotIn({"cmd": "build", "item": "weap"}, result)

    def test_no_harvester_and_no_vehicle_producer_recovers_via_refinery(self):
        state = snapshot(80, buildings=self.buildings, cash=1700,
                         build=["powr", "proc", "weap"], train=["e1"])
        result = commands(Controller().decide(state))
        self.assertIn({"cmd": "build", "item": "proc"}, result)
        self.assertNotIn({"cmd": "build", "item": "weap"}, result)

    def test_yard_and_harvester_lost_saves_income_before_unaffordable_mcv(self):
        buildings = [b for b in self.buildings if b["type"] != "fact"] + [actor(5, "weap")]
        config = {"rules": {"units": {"mcv": {"cost": 2500, "queue": "Vehicle", "build_time_s": 60}}}}
        state = snapshot(300, buildings=buildings, cash=1100, train=["e1", "harv", "mcv"])
        result = commands(Controller().decide(state, config))
        self.assertIn({"cmd": "train", "item": "harv"}, result)

    def test_pending_build_is_not_repeated_during_delayed_observation(self):
        bot = Controller()
        state = snapshot(buildings=[actor(1, "fact")], build=["powr"])
        self.assertIn({"cmd": "build", "item": "powr"}, commands(bot.decide(state)))
        bot.on_result({"accepted": True, "results": [{"index": 0, "status": "pending"}]})
        for seconds in (1.2, 2.2, 4.2, 7.9):
            delayed = deepcopy(state)
            delayed["state_version"] = delayed["observation"]["tick"] = int(seconds * 25)
            delayed["time"]["game_seconds"] = seconds
            self.assertFalse(any(o.get("cmd") == "build" for o in commands(bot.decide(delayed))))

    def test_lost_build_retries_after_authoritative_lost_verdict(self):
        bot = Controller()
        state = snapshot(buildings=[actor(1, "fact")], build=["powr"])
        bot.decide(state)
        bot.on_result({"accepted": True, "batch": 9, "results": [{"index": 0, "status": "pending"}]})
        lost = snapshot(1.4, buildings=[actor(1, "fact")], build=["powr"])
        lost["last_orders"] = {"state_version": 25, "batch": 9,
                               "results": [{"index": 0, "status": "lost", "reason": "not_applied"}]}
        bot.decide(lost)
        retry = snapshot(2.2, buildings=[actor(1, "fact")], build=["powr"])
        self.assertIn({"cmd": "build", "item": "powr"}, commands(bot.decide(retry)))

    def test_finished_building_is_placed_even_when_clock_is_almost_over(self):
        state = snapshot(1198, buildings=[actor(1, "fact")], cash=0, remaining=2,
                         production=[{"queue": "Building", "item": "powr", "progress": 1, "ready": True}])
        result = commands(Controller().decide(state))
        self.assertIn({"cmd": "place", "item": "powr"}, result)


class CombatContractScenarios(unittest.TestCase):
    def test_stale_enemy_id_and_wreck_cannot_be_attack_targets(self):
        state = snapshot(units=[actor(1, "1tnk")], enemies=[actor(20, "3tnk.husk", wreck=True)])
        view = View(state)
        for target in (20, 21):
            self.assertIsNone(validate_order({"cmd": "attack", "units": [1], "target": target}, view))

    def test_orders_cannot_command_enemy_ids(self):
        state = snapshot(units=[actor(1, "1tnk")], enemies=[actor(20, "3tnk")])
        self.assertIsNone(validate_order({"cmd": "move", "units": [20], "to": [40, 40]}, View(state)))

    def test_command_coordinates_use_playable_bounds_not_outer_map_size(self):
        state = snapshot(units=[actor(1, "1tnk")])
        state["map"].update(width=104, height=104)
        self.assertIsNone(validate_order({"cmd": "move", "units": [1], "to": [102, 102]}, View(state)))

    def test_countdown_does_not_override_overwhelming_local_disadvantage(self):
        own = [actor(i, "1tnk", 30+i%2, 30+i%3) for i in range(10, 16)]
        enemies = [actor(i, "3tnk", 35+i%2, 30+i%3) for i in range(100, 122)]
        state = snapshot(1150, units=own, enemies=enemies, cash=0, remaining=50, deaths=5000)
        result = commands(Controller().decide(state))
        self.assertTrue(any(o["cmd"] == "move" for o in result))
        self.assertFalse(any(o["cmd"] in {"attack", "attack_move"} for o in result))

    def test_busy_army_keeps_stable_accepted_order_between_refreshes(self):
        own = [actor(i, "1tnk", 30+i%2, 30+i%3) for i in range(10, 16)]
        state = snapshot(300, units=own, cash=0)
        bot = Controller()
        first = commands(bot.decide(state))
        self.assertTrue(any(o["cmd"] == "attack_move" for o in first))
        bot.on_result({"accepted": True,
                       "results": [{"index": i, "status": "ok"} for i in range(len(first))]})
        later = deepcopy(state)
        later["time"]["game_seconds"] = 303.2
        later["state_version"] = later["observation"]["tick"] = 7580
        for unit in later["observation"]["units"]:
            unit.update(idle=False, act="AttackMove")
        self.assertFalse(any(o["cmd"] in {"move", "attack_move"} for o in commands(bot.decide(later))))


if __name__ == "__main__":
    unittest.main()
