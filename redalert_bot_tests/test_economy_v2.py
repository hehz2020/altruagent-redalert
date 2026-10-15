import unittest

from altru_redalert.economy import Economy, _reserved
from altru_redalert.core import validate_order
from altru_redalert.model import View


def actor(uid, kind, x=12, y=12, **extra):
    return {"id": uid, "type": kind, "x": x, "y": y, "hp": 100, "idle": True, **extra}


def config(with_map=False):
    result = {"rules": {"units": {
        "e3": {"cost": 300, "build_time_s": 7.2, "queue": "Infantry"},
        "2tnk": {"cost": 850, "build_time_s": 20.4, "queue": "Vehicle"},
        "arty": {"cost": 850, "build_time_s": 20.4, "queue": "Vehicle"},
        "mcv": {"cost": 2000, "build_time_s": 40, "queue": "Vehicle"},
    }, "buildings": {
        "dome": {"cost": 1500, "build_time_s": 36, "power": -40, "queue": "Building"},
        "fix": {"cost": 1200, "build_time_s": 28.8, "power": -30, "queue": "Building"},
    }}}
    if with_map:
        rows = [["."] * 120 for _ in range(70)]
        for cx, cy in ((16, 15), (42, 38), (90, 15)):
            for x in range(cx - 2, cx + 3):
                for y in range(cy - 2, cy + 3):
                    rows[y][x] = "$"
            rows[cy][cx] = "M"
        result["rules"]["maps"] = {"test": {"bounds": [0, 0, 120, 70],
            "layout": {"origin": [0, 0], "rows": ["".join(row) for row in rows]}}}
    return result


def view(seconds=300, *, cash=3000, units=None, buildings=None, train=(), build=(),
         production=(), enemies=(), pending=(), place=None, deploy=None, remaining=900, with_map=False):
    if buildings is None:
        buildings = [actor(1, "fact", 10, 10), actor(2, "powr"), actor(3, "tent"),
                     actor(4, "proc", 14, 10), actor(5, "weap"), actor(6, "proc", 17, 10), actor(7, "fix")]
    if units is None:
        units = [actor(i, "harv") for i in range(20, 24)] + [actor(i, "e1") for i in range(30, 33)]
    legal = {"train": list(train), "build": list(build), "enemy_base": [100, 10]}
    if place is not None:
        legal["place"] = place
    if deploy is not None:
        legal["deploy"] = deploy
    raw = {"state_version": int(seconds * 25), "map": {"id": "test", "bounds": [0, 0, 120, 70]},
           "time": {"game_seconds": seconds, "remaining_seconds": remaining}, "legal_actions": legal,
           "limits": {"max_train_count": 10}, "observation": {
               "base_center": [10, 10], "tick": int(seconds * 25), "units": units, "buildings": buildings,
               "production": list(production), "visible_enemies": list(enemies),
               "economy": {"cash": cash, "ore": 0, "power_provided": 400, "power_drained": 120}}}
    return View(raw, config(with_map), list(pending))


def orders(v, policy=None, command=None):
    result = [x.order for x in (policy or Economy()).propose(v)]
    return [o for o in result if command is None or o["cmd"] == command]


class ProductionBudgetTests(unittest.TestCase):
    def test_late_public_configuration_restores_map_planning(self):
        policy = Economy()
        initial = view(with_map=False)
        policy.propose(initial)
        self.assertFalse(policy._map.resources)
        configured = view(with_map=True)
        policy.propose(configured)
        self.assertTrue(policy._map.resources)
        self.assertTrue(policy._map.clusters)
        self.assertIsNotNone(policy._ore(configured))
        cached_map = policy._map
        policy.propose(view(with_map=True))
        self.assertIs(policy._map, cached_map)

    def test_count_progress_and_ready_head_reserve_all_unpaid_items(self):
        v = view(production=[{"item": "e1", "queue": "Infantry", "count": 5, "progress": .5},
                             {"item": "2tnk", "queue": "Vehicle", "count": 2, "ready": True}],
                 pending=[{"cmd": "train", "item": "e1", "count": 2}])
        self.assertEqual(_reserved(v), 450 + 850 + 200)

    def test_batch_bridges_slow_observations_without_overspending(self):
        v = view(train=["e1", "2tnk"])
        v.units.extend(actor(50 + i, "2tnk") for i in range(6))
        result = orders(v, command="train")
        self.assertLessEqual(sum(v.cost(o["item"]) * o.get("count", 1) for o in result), v.funds)
        self.assertTrue(all(validate_order(o, v) == o for o in result))
        rifle = next(o for o in result if o["item"] == "e1")
        tank = next(o for o in result if o["item"] == "2tnk")
        self.assertGreaterEqual(rifle.get("count", 1), 5)
        self.assertEqual(tank.get("count"), 2)

    def test_queued_tail_is_not_spent_twice(self):
        v = view(cash=1000, train=["e1", "2tnk"],
                 production=[{"queue": "Vehicle", "item": "2tnk", "count": 2, "progress": .5}])
        self.assertEqual(orders(v, command="train"), [])

    def test_unaffordable_medium_tank_does_not_block_a_light_tank(self):
        v = view(cash=1075, train=["2tnk", "1tnk", "e1", "e3"])
        v.units.extend(actor(50 + i, "2tnk") for i in range(6))
        result = orders(v, command="train")
        self.assertLessEqual(sum(v.cost(o["item"]) * o.get("count", 1) for o in result), v.funds)
        self.assertTrue(all(validate_order(o, v) == o for o in result))
        self.assertIn({"cmd": "train", "item": "1tnk"}, result)
        self.assertNotIn({"cmd": "train", "item": "2tnk"}, result)

    def test_uncertain_train_blocks_additional_queue_orders(self):
        v = view(train=["e1"], pending=[{"cmd": "train", "item": "e1", "count": 8}])
        self.assertEqual(orders(v, command="train"), [])

    def test_batch_obeys_server_count_limit_and_end_clock(self):
        v = view(train=["e1"], remaining=17)
        v.raw["limits"]["max_train_count"] = 2
        result = orders(v, command="train")
        self.assertEqual(result, [{"cmd": "train", "item": "e1", "count": 2}])

    def test_missing_match_end_time_does_not_crash_batching(self):
        v = view(train=["e1"])
        v.remaining = float("inf")
        self.assertTrue(orders(v, command="train"))

    def test_ready_vehicle_never_receives_place_order(self):
        for legal in (None, [], ["2tnk"]):
            v = view(production=[{"queue": "Vehicle", "item": "2tnk", "ready": True}], place=legal)
            self.assertEqual(orders(v, command="place"), [])

    def test_authoritative_empty_place_overrules_ready_building(self):
        v = view(production=[{"queue": "Building", "item": "powr", "ready": True}], place=[])
        self.assertEqual(orders(v, command="place"), [])

    def test_air_threat_trains_rocket_cover_without_a_radar(self):
        v = view(train=["e1", "e3"], enemies=[actor(90, "yak", 35, 15)])
        self.assertEqual(orders(v, command="train")[0]["item"], "e3")

    def test_screened_army_adds_artillery_without_spamming_it(self):
        units = [actor(i, "harv") for i in range(20, 24)]
        units += [actor(i, "e1") for i in range(30, 40)]
        units += [actor(i, "2tnk") for i in range(50, 56)]
        result = orders(view(units=units, train=["arty", "2tnk"]), command="train")
        self.assertEqual(result, [{"cmd": "train", "item": "arty"}])
        units.append(actor(60, "arty"))
        result = orders(view(units=units, train=["arty", "2tnk"]), command="train")
        self.assertEqual(result, [{"cmd": "train", "item": "arty"}])
        units.append(actor(61, "arty"))
        result = orders(view(units=units, train=["arty", "2tnk"]), command="train")
        self.assertEqual(result[0]["item"], "2tnk")
        self.assertFalse(any(o["item"] == "arty" for o in result))

    def test_lost_yard_saves_rebuild_cash_instead_of_spending_on_rifles(self):
        v = view(cash=1700, train=["mcv", "e1"])
        v.buildings = [b for b in v.buildings if b["type"] != "fact"]
        self.assertEqual(orders(v, command="train"), [])

    def test_sustained_cash_surplus_adds_vehicle_production_capacity(self):
        policy = Economy()
        v = view(cash=5000, build=["weap"])
        self.assertFalse(any(o.get("item") == "weap" for o in orders(v, policy, "build")))
        v.now += 30
        self.assertIn({"cmd": "build", "item": "weap"}, orders(v, policy, "build"))

    def test_harvester_retreat_takes_priority_over_idle_harvest(self):
        units = [actor(20, "harv", 30, 15, hp=50)]
        v = view(units=units, enemies=[actor(90, "2tnk", 33, 15)])
        result = orders(v)
        self.assertTrue(any(o["cmd"] == "move" and o["units"] == [20] for o in result))
        self.assertFalse(any(o["cmd"] == "harvest" for o in result))

    def test_last_harvester_loss_unblocks_one_queued_tank_per_fresh_view(self):
        units = [actor(i, "e1") for i in range(30, 40)]
        v = view(cash=1200, units=units, train=["harv", "2tnk", "e1"], build=["proc", "powr", "fix"],
                 production=[{"queue": "Vehicle", "item": "2tnk", "count": 2, "progress": .3}])
        policy = Economy()
        self.assertEqual(orders(v, policy), [{"cmd": "cancel", "item": "2tnk"}])
        v.production[0]["count"] = 1
        v.now += 15
        self.assertEqual(orders(v, policy), [{"cmd": "cancel", "item": "2tnk"}])
        v.production = []
        v.now += 15
        self.assertIn({"cmd": "train", "item": "harv"}, orders(v, policy))

    def test_income_recovery_does_not_cancel_affordable_combat_queue(self):
        units = [actor(i, "e1") for i in range(30, 40)]
        v = view(cash=4000, units=units, train=["harv", "2tnk"],
                 production=[{"queue": "Vehicle", "item": "2tnk", "count": 2, "progress": .3}])
        self.assertEqual(orders(v, command="cancel"), [])

    def test_income_recovery_does_not_cancel_or_respend_ambiguous_request(self):
        units = [actor(i, "e1") for i in range(30, 40)]
        for pending in ([{"cmd": "cancel", "item": "2tnk"}],
                        [{"cmd": "train", "item": "2tnk", "count": 2}]):
            v = view(cash=1200, units=units, train=["harv", "2tnk", "e1"], pending=pending,
                     production=[{"queue": "Vehicle", "item": "2tnk", "count": 2, "progress": .3}])
            self.assertEqual(orders(v), [])

    def test_refinery_recovery_is_preserved_while_competing_queue_is_cancelled(self):
        v = view(cash=1000, units=[], train=["harv", "2tnk"], production=[
            {"queue": "Building", "item": "proc", "progress": .8},
            {"queue": "Vehicle", "item": "2tnk", "count": 2, "progress": .3}])
        self.assertEqual(orders(v), [{"cmd": "cancel", "item": "2tnk"}])

    def test_yard_and_refinery_loss_preserves_queued_mcv_and_refinery_funds(self):
        v = view(cash=2500, units=[actor(i, "e1") for i in range(30, 40)], train=["mcv", "e1"],
                 production=[{"queue": "Vehicle", "item": "mcv", "progress": .8},
                             {"queue": "Vehicle", "item": "2tnk", "count": 2, "progress": 0}])
        v.buildings = [b for b in v.buildings if b["type"] not in {"fact", "proc"}]
        self.assertEqual(orders(v), [{"cmd": "cancel", "item": "2tnk"}])
        v.production = []
        v.funds = 3700
        result = orders(v, command="train")
        self.assertIn({"cmd": "train", "item": "mcv"}, result)
        self.assertLessEqual(sum(v.cost(o["item"]) * o.get("count", 1) for o in result), 2300)


class ExpansionTests(unittest.TestCase):
    def setUp(self):
        self.units = [actor(i, "harv") for i in range(20, 24)]
        self.units += [actor(i, "e1") for i in range(30, 42)]
        self.units += [actor(i, "2tnk") for i in range(50, 53)]

    def test_safe_expansion_buys_mcv_and_keeps_refinery_money(self):
        v = view(cash=6000, units=self.units, train=["mcv", "e1"], with_map=True)
        result = orders(v, command="train")
        self.assertIn({"cmd": "train", "item": "mcv"}, result)
        self.assertLessEqual(sum(v.cost(o["item"]) * o.get("count", 1) for o in result), v.funds - 1700)

    def test_no_expansion_when_home_is_under_armored_attack(self):
        v = view(cash=6000, units=self.units, train=["mcv", "2tnk"], with_map=True,
                 enemies=[actor(90, "2tnk", 17, 15)])
        self.assertFalse(any(o.get("item") == "mcv" for o in orders(v, command="train")))

    def test_expansion_candidate_rejects_visible_danger(self):
        v = view(cash=6000, units=self.units, train=["mcv"], with_map=True,
                 enemies=[actor(90, "2tnk", 42, 38)])
        self.assertEqual(orders(v, command="train"), [])

    def test_static_disconnected_resource_field_is_not_an_expansion(self):
        v = view(cash=6000, units=self.units, train=["mcv"], with_map=True)
        layout = v.map_info["layout"]
        layout["rows"] = [r[:28] + "~" + r[29:] for r in layout["rows"]]
        self.assertEqual(orders(v, command="train"), [])

    def test_expansion_yard_is_outside_existing_refinery_coverage(self):
        v = view(cash=6000, units=self.units, train=["mcv"], with_map=True)
        rows = [["."] * 120 for _ in range(70)]
        for x in range(35, 40):
            for y in range(8, 13):
                rows[y][x] = "$"
        rows[10][37] = "M"
        v.map_info["layout"]["rows"] = ["".join(row) for row in rows]
        policy = Economy()
        policy._refresh(v)
        site = policy._map.expansion(v)
        self.assertIsNotNone(site)
        v.buildings.append(actor(80, "fact", *site))
        self.assertEqual(policy._unserved_yard(v), site)

    def test_expansion_mcv_moves_before_deploying_and_waits_in_transit(self):
        policy = Economy()
        v = view(units=self.units + [actor(80, "mcv")], with_map=True, deploy=[80])
        result = orders(v, policy)
        move = next(o for o in result if o["cmd"] == "move" and o["units"] == [80])
        self.assertGreater(distance_to_home(move["to"]), 20)
        self.assertFalse(any(o["cmd"] == "deploy" for o in result))
        v.units[-1].update(x=25, y=20, idle=False)
        v.now += 15
        self.assertFalse(any(o["cmd"] in {"move", "deploy"} and o.get("units") == [80]
                             for o in orders(v, policy)))
        v.units[-1].update(x=move["to"][0], y=move["to"][1], idle=True)
        v.now += 15
        self.assertIn({"cmd": "deploy", "units": [80]}, orders(v, policy))

    def test_illegal_deploy_moves_clear_instead_of_repeating_rejection(self):
        v = view(units=[actor(80, "mcv")], buildings=[], deploy=[])
        result = orders(v)
        self.assertFalse(any(o["cmd"] == "deploy" for o in result))
        self.assertTrue(any(o["cmd"] == "move" and o["units"] == [80] for o in result))

    def test_new_yard_gets_refinery_hint_at_the_new_location(self):
        v = view(with_map=True, build=["proc"], place=["proc"],
                 production=[{"queue": "Building", "item": "proc", "ready": True}])
        v.buildings.append(actor(80, "fact", 35, 35))
        order = orders(v, command="place")[0]
        self.assertEqual(order["item"], "proc")
        self.assertGreater(order["at"][0], 30)
        self.assertGreater(order["at"][1], 30)


def distance_to_home(point):
    return ((point[0] - 10) ** 2 + (point[1] - 10) ** 2) ** .5


if __name__ == "__main__":
    unittest.main()
