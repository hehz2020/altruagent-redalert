from copy import deepcopy
import unittest

from altru_redalert.core import Controller, validate_order
from altru_redalert.model import FALLBACKS, Intent, View


def actor(uid, kind, x=12, y=12, **extra):
    return {"id": uid, "type": kind, "x": x, "y": y, "hp": 100,
            "idle": True, **extra}


def state(tick=0, *, units=None, buildings=None, production=None, build=None,
          train=None, cash=5000, power=100, drain=0, enemies=None, enemy_buildings=None):
    return {
        "session_id": "test", "game_type": "red_alert", "phase": "playing",
        "is_current_actor": True, "is_terminal": False, "state_version": tick,
        "map": {"id": "sidestep", "bounds": [2, 2, 96, 96]},
        "time": {"game_seconds": tick / 25, "remaining_seconds": 1200 - tick / 25},
        "legal_actions": {"build": build or [], "train": train or [], "enemy_base": [64, 12]},
        "observation": {"tick": tick, "base_center": [12, 12], "units": units or [],
                        "buildings": buildings or [], "production": production or [],
                        "visible_enemies": enemies or [], "visible_enemy_buildings": enemy_buildings or [],
                        "economy": {"cash": cash, "ore": 0, "power_provided": power, "power_drained": drain},
                        "military": {"kills_cost": 0, "deaths_cost": 0}},
    }


def orders(result, cmd=None):
    result = result["orders"] if result else []
    return [o for o in result if cmd is None or o["cmd"] == cmd]


class ContractTests(unittest.TestCase):
    def test_deploy_is_not_resent_while_engine_is_applying_it(self):
        c = Controller()
        s = state(units=[actor(1, "mcv")])
        self.assertEqual(orders(c.decide(s), "deploy"), [{"cmd": "deploy", "units": [1]}])
        c.on_result({"accepted": True, "results": [{"index": 0, "cmd": "deploy", "status": "pending"}]})
        s["state_version"] = s["observation"]["tick"] = 5
        s["time"]["game_seconds"] = .2
        self.assertEqual(orders(c.decide(s), "deploy"), [])
        s = state(10, buildings=[actor(2, "fact")], build=["powr"], power=0)
        self.assertEqual(orders(c.decide(s), "build"), [{"cmd": "build", "item": "powr"}])

    def test_pending_build_and_stale_ack_do_not_duplicate(self):
        c = Controller()
        s = state(100, buildings=[actor(2, "fact")], build=["powr"], power=0)
        first = c.decide(s)
        self.assertEqual(len(orders(first, "build")), 1)
        c.on_result({"accepted": True, "results": [{"index": 0, "cmd": "build", "status": "pending"}]})
        s = state(105, buildings=[actor(2, "fact")], build=["powr"], power=0)
        s["last_orders"] = {"state_version": 100, "batch": 5, "pending": False,
                            "results": [{"index": 0, "cmd": "build", "status": "ok"}]}
        self.assertEqual(orders(c.decide(s), "build"), [])
        s = state(110, buildings=[actor(2, "fact")], build=["powr"], power=0,
                  production=[{"item": "powr", "queue": "Building", "progress": .05, "ready": False}])
        self.assertEqual(orders(c.decide(s), "build"), [])
        self.assertEqual(c.stats["observed_confirmations"], 1)

    def test_rejected_build_recovers_after_bounded_backoff(self):
        c = Controller()
        s = state(100, buildings=[actor(2, "fact")], build=["powr"], power=0)
        c.decide(s)
        c.on_result({"error": "INVALID_ACTION"})
        s = state(110, buildings=[actor(2, "fact")], build=["powr"], power=0)
        self.assertEqual(orders(c.decide(s), "build"), [])
        s = state(175, buildings=[actor(2, "fact")], build=["powr"], power=0)
        self.assertEqual(orders(c.decide(s), "build"), [{"cmd": "build", "item": "powr"}])

    def test_ready_building_is_placed_once_until_reflected(self):
        c = Controller()
        p = [{"item": "powr", "queue": "Building", "ready": True, "progress": 1}]
        s = state(100, buildings=[actor(2, "fact")], production=p, build=["powr"])
        self.assertEqual(orders(c.decide(s), "place"), [{"cmd": "place", "item": "powr"}])
        s = state(105, buildings=[actor(2, "fact")], production=p, build=["powr"])
        self.assertEqual(orders(c.decide(s), "place"), [])

    def test_old_hidden_enemy_and_wreck_are_not_attackable(self):
        v = View(state(units=[actor(1, "e1"), actor(2, "1tnkhusk", wreck=True)],
                       enemies=[actor(9, "e1"), actor(10, "3tnkhusk", wreck=True)]))
        self.assertIsNone(validate_order({"cmd": "attack", "units": [1], "target": 8}, v))
        self.assertIsNone(validate_order({"cmd": "attack", "units": [1], "target": 10}, v))
        self.assertIsNone(validate_order({"cmd": "move", "units": [2], "to": [3, 3]}, v))
        self.assertEqual(validate_order({"cmd": "attack", "units": [1, 2], "target": 9}, v)["units"], [1])

    def test_playable_bounds_and_unknown_fields_are_enforced(self):
        v = View(state(units=[actor(1, "e1")]))
        self.assertIsNone(validate_order({"cmd": "move", "units": [1], "to": [0, 0]}, v))
        self.assertIsNone(validate_order({"cmd": "move", "units": [1], "to": [3, 3], "speed": 9}, v))
        self.assertIsNone(validate_order({"cmd": "move", "units": [1], "to": [True, 3]}, v))

    def test_unknown_production_cost_does_not_become_a_guess(self):
        v = View(state())
        self.assertEqual(v.cost("unknown_tank"), 0)
        v = View(state(), {"rules": {"units": {"e1": {"cost": 123}}}})
        self.assertEqual(v.cost("e1"), 123)

    def test_terminal_and_prestart_never_send_orders(self):
        c = Controller()
        for phase in ("queued", "starting", "waiting_for_agents", "finished"):
            s = state(units=[actor(1, "mcv")])
            s["phase"] = phase
            self.assertIsNone(c.decide(s))

    def test_same_observation_does_not_generate_extra_batches(self):
        c = Controller()
        s = state(units=[actor(1, "mcv")])
        c.decide(s)
        self.assertIsNone(c.decide(s))

    def test_late_game_does_not_queue_unfinishable_factory(self):
        c = Controller()
        s = state(29900, buildings=[actor(2, "fact"), actor(3, "powr"), actor(4, "tent"), actor(5, "proc")],
                  build=["weap", "powr", "proc", "tent"], train=["e1", "harv"])
        self.assertEqual(orders(c.decide(s), "build"), [])

    def test_new_match_resets_pending_and_scout_memory(self):
        c = Controller()
        s = state(units=[actor(1, "mcv")])
        c.decide(s)
        s["session_id"] = "another"
        self.assertEqual(orders(c.decide(s), "deploy"), [{"cmd": "deploy", "units": [1]}])

    def test_large_army_respects_200_expanded_commands(self):
        class Script:
            def propose(self, v):
                return [Intent({"cmd": "attack_move", "units": [u["id"] for u in v.units], "to": [64, 12]})]
            def mark_sent(self, orders, now):
                pass
        class Empty:
            def propose(self, v):
                return []
        c = Controller()
        c.economy, c.military = Empty(), Script()
        s = state(100, units=[actor(i, "e1") for i in range(1, 301)])
        batch = c.decide(s)["orders"]
        self.assertLessEqual(len(batch), 20)
        self.assertLessEqual(sum(len(o["units"]) for o in batch), 200)
        self.assertTrue(all(len(o["units"]) <= 50 for o in batch))


class EconomyTimeline:

    def __init__(self, soviet=False, far=False):
        self.tick = 0
        self.cash = 5000.0
        self.units = [actor(1, "mcv")]
        self.buildings = []
        self.queues = {}
        self.delayed = []
        self.history = []
        self.soviet, self.far = soviet, far
        self.uid = 10

    def counts(self, kind):
        return sum(a["type"] == kind for a in self.units + self.buildings)

    def available(self):
        build, train = [], []
        if self.counts("fact"):
            build += ["powr"]
        if self.counts("powr"):
            build += ["barr" if self.soviet else "tent", "proc"]
        if self.counts("proc"):
            build += ["weap"]
            train += ["harv"]
        if self.counts("barr") + self.counts("tent"):
            train += ["e1"]
        if self.counts("weap"):
            train += ["ftrk", "apc"] if self.soviet else ["1tnk", "jeep"]
        return build, train

    def snapshot(self):
        build, train = self.available()
        s = state(self.tick, units=deepcopy(self.units), buildings=deepcopy(self.buildings),
                  build=build, train=train, cash=self.cash,
                  power=100 * self.counts("powr"),
                  drain=20 * (self.counts("tent") + self.counts("barr")) + 30 * (self.counts("proc") + self.counts("weap")))
        s["observation"]["production"] = [dict(q) for q in self.queues.values()]
        if self.far:
            s["legal_actions"]["enemy_base"] = [90, 90]
        return s

    def new_actor(self, kind):
        self.uid += 1
        return actor(self.uid, kind)

    def advance(self):
        self.tick += 5
        self.cash += self.counts("harv") * 8
        for due, o in list(self.delayed):
            if due > self.tick:
                continue
            self.delayed.remove((due, o))
            cmd = o["cmd"]
            if cmd == "deploy":
                self.units = [u for u in self.units if u["id"] not in o["units"]]
                self.buildings.append(self.new_actor("fact"))
            elif cmd in {"build", "train"}:
                item = o["item"]
                queue = FALLBACKS[item]["queue"]
                if queue in self.queues:
                    raise AssertionError(f"Duplicate production into occupied queue: {o}")
                duration = FALLBACKS[item].get("build_time_s", 20)
                self.queues[queue] = {"item": item, "queue": queue, "progress": 0,
                                      "ready": False, "duration": duration,
                                      "count": o.get("count", 1)}
                self.history.append((self.tick / 25, cmd, item))
            elif cmd == "place":
                queue = FALLBACKS[o["item"]]["queue"]
                self.queues.pop(queue)
                self.buildings.append(self.new_actor(o["item"]))
                if o["item"] == "proc":
                    self.units.append(self.new_actor("harv"))
            elif cmd in {"move", "attack_move"}:
                for u in self.units:
                    if u["id"] in o["units"]:
                        u["x"], u["y"] = o["to"]
                        u["idle"] = False
        for key, q in list(self.queues.items()):
            if q["ready"]:
                continue
            step = min(.2 / q["duration"], 1 - q["progress"])
            cost = FALLBACKS[q["item"]]["cost"] * step
            if self.cash < cost:
                continue
            self.cash -= cost
            q["progress"] += step
            if q["progress"] >= .999999:
                if key in {"Building", "Defense"}:
                    q["ready"] = True
                else:
                    self.units.append(self.new_actor(q["item"]))
                    q["count"] -= 1
                    if q["count"]:
                        q["progress"] = 0
                    else:
                        del self.queues[key]


class TimelineTests(unittest.TestCase):
    def test_opening_reaches_factory_without_duplicate_queues_in_all_branches(self):
        for soviet in (False, True):
            for far in (False, True):
                with self.subTest(soviet=soviet, far=far):
                    sim, c = EconomyTimeline(soviet, far), Controller()
                    for _ in range(1250):
                        action = c.decide(sim.snapshot())
                        if action:
                            for o in action["orders"]:
                                sim.delayed.append((sim.tick + 10, o))
                            c.on_result({"accepted": True, "results": [
                                {"index": i, "cmd": o["cmd"], "status": "pending"}
                                for i, o in enumerate(action["orders"])]})
                        sim.advance()
                    self.assertEqual(sim.counts("weap"), 1)
                    self.assertGreater(sim.counts("harv"), 0)
                    self.assertGreater(sim.counts("e1"), 0)
                    self.assertGreater(sum(sim.counts(x) for x in ("1tnk", "ftrk", "apc", "jeep")), 0)
                    buildings = [item for _, cmd, item in sim.history if cmd == "build"]
                    self.assertEqual(buildings[:4], ["powr", "proc", "barr" if soviet else "tent", "proc"]
                                     if far else ["powr", "barr" if soviet else "tent", "proc", "proc"])
                    self.assertEqual(buildings[4:6], ["powr", "weap"])
                    self.assertEqual(c.stats["unconfirmed_expiries"], 0)


if __name__ == "__main__":
    unittest.main()
