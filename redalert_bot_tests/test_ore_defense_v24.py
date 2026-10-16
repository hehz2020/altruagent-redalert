import unittest

from altru_redalert.combat import Military
from altru_redalert.core import validate_order
from altru_redalert.economy import Economy
from altru_redalert.model import View, distance
from redalert_bot_tests.test_adversarial import actor, snapshot


def economy_view(now=300, cash=5000, enemies=(), harvs=4, towers=(), place=()):
    buildings = [actor(1, "fact", 14, 20), actor(2, "powr", 10, 24),
                 actor(3, "tent", 14, 14), actor(4, "proc", 20, 20),
                 actor(5, "weap", 14, 28), actor(6, "proc", 20, 32),
                 actor(7, "fix", 10, 32)] + list(towers)
    units = [actor(20 + i, "harv", 26, 20 + i) for i in range(harvs)]
    units += [actor(40 + i, "2tnk", 40, 20 + i) for i in range(6)]
    units += [actor(60 + i, "e1", 40, 30 + i) for i in range(6)]
    rows = [["."] * 96 for _ in range(96)]
    for x in range(27, 32):
        for y in range(18, 23):
            rows[y - 4][x - 4] = "$"
    cfg = {"rules": {"maps": {"scenario-map": {
        "layout": {"origin": [4, 4], "rows": ["".join(r) for r in rows]}}},
        "units": {"2tnk": {"cost": 850, "queue": "Vehicle", "build_time_s": 20.4}},
        "buildings": {
            "pbox": {"cost": 400, "power": 0, "queue": "Defense", "build_time_s": 12},
            "gun": {"cost": 600, "power": -40, "queue": "Defense", "build_time_s": 15},
            "ftur": {"cost": 600, "power": -40, "queue": "Defense", "build_time_s": 15},
            "tsla": {"cost": 1500, "power": -80, "queue": "Defense", "build_time_s": 35}}}}
    raw = snapshot(now, buildings=buildings, units=units, cash=cash, enemies=enemies,
                   build=["pbox", "gun", "ftur", "tsla"], train=["2tnk", "harv"],
                   production=[{"item": item, "queue": "Defense", "ready": True} for item in place])
    raw["observation"]["base_center"] = [14, 20]
    return View(raw, cfg)


def build_orders(policy, view):
    return [intent.order for intent in policy.propose(view) if intent.order["cmd"] == "build"]


class OreProtectionScenarios(unittest.TestCase):
    def test_single_scout_does_not_recall_distant_attack_army(self):
        army = [actor(i, "2tnk", 75 + i % 3, 70 + i // 3) for i in range(10, 25)]
        hauler = actor(30, "harv", 50, 50)
        raider = actor(100, "e1", 53, 50)
        v = View(snapshot(300, units=army + [hauler], buildings=[actor(1, "proc", 12, 12)],
                          enemies=[raider]))
        self.assertEqual(Military()._defense(v, army, [raider]), ([], set()))

    def test_close_anti_infantry_intercepts_without_recalling_tank_army(self):
        army = [actor(i, "2tnk", 55 + i % 3, 55 + i // 3) for i in range(10, 25)]
        escort = actor(31, "apc", 27, 22)
        army.append(escort)
        hauler = actor(30, "harv", 28, 20)
        raider = actor(100, "e1", 31, 20)
        v = View(snapshot(300, units=army + [hauler], buildings=[actor(1, "proc", 22, 20)],
                          enemies=[raider]))
        intents, defenders = Military()._defense(v, army, [raider])
        self.assertEqual(defenders, {31})
        self.assertTrue(intents)
        self.assertTrue(all(validate_order(intent.order, v) for intent in intents))

    def test_remote_ore_raid_assigns_at_most_a_small_detachment(self):
        army = [actor(i, "2tnk", 49 + i % 3, 48 + i // 3) for i in range(10, 25)]
        hauler = actor(30, "harv", 50, 50)
        enemies = [actor(100 + i, "3tnk", 54, 49 + i) for i in range(5)]
        v = View(snapshot(300, units=army + [hauler], buildings=[actor(1, "proc", 12, 12)],
                          enemies=enemies))
        _, defenders = Military()._defense(v, army, enemies)
        self.assertLessEqual(len(defenders), 3)

    def test_major_attack_on_refinery_can_recall_main_army(self):
        army = [actor(i, "2tnk", 55 + i % 3, 50 + i // 3) for i in range(10, 25)]
        enemies = [actor(100 + i, "3tnk", 18, 12 + i % 3) for i in range(8)]
        v = View(snapshot(300, units=army, buildings=[actor(1, "proc", 12, 12)], enemies=enemies))
        _, defenders = Military()._defense(v, army, enemies)
        self.assertGreater(len(defenders), 6)

    def test_working_pillbox_handles_rifle_without_mobile_recall(self):
        army = [actor(10, "2tnk", 24, 20)]
        raider = actor(100, "e1", 29, 20)
        buildings = [actor(1, "proc", 22, 20), actor(2, "pbox", 26, 22)]
        v = View(snapshot(300, units=army + [actor(30, "harv", 27, 20)],
                          buildings=buildings, enemies=[raider]))
        self.assertEqual(Military()._defense(v, army, [raider]), ([], set()))
        buildings[1]["powered"] = False
        v = View(snapshot(300, units=army + [actor(30, "harv", 27, 20)],
                          buildings=buildings, enemies=[raider]))
        self.assertEqual(Military()._defense(v, army, [raider])[1], {10})

    def test_scout_harvester_cannot_trigger_defense(self):
        v = economy_view(enemies=[actor(100, "harv", 23, 20)])
        self.assertEqual(build_orders(Economy(), v), [])
        army = [u for u in v.units if u["type"] == "2tnk"]
        self.assertEqual(Military()._defense(v, army, v.enemies), ([], set()))


class StaticOreDefenseScenarios(unittest.TestCase):
    def test_persistent_single_rifle_raid_gets_pillbox_but_transient_scout_does_not(self):
        policy = Economy()
        raid = [actor(100, "e1", 29, 23)]
        self.assertEqual(build_orders(policy, economy_view(enemies=raid)), [])
        first = build_orders(policy, economy_view(306, enemies=raid))
        self.assertEqual(first, [])
        result = build_orders(policy, economy_view(312, enemies=raid))
        self.assertEqual(result, [{"cmd": "build", "item": "pbox"}])

    def test_armored_ore_raid_gets_anti_tank_turret(self):
        raid = [actor(100 + i, "2tnk", 29, 23 + i) for i in range(2)]
        v = economy_view(enemies=raid)
        result = build_orders(Economy(), v)
        self.assertEqual(result, [{"cmd": "build", "item": "gun"}])

    def test_turret_does_not_consume_last_harvester_recovery(self):
        raid = [actor(100 + i, "2tnk", 24, 20 + i) for i in range(2)]
        v = economy_view(cash=1700, enemies=raid, harvs=0)
        result = [i.order for i in Economy().propose(v)]
        self.assertIn({"cmd": "train", "item": "harv"}, result)
        self.assertFalse(any(o["cmd"] == "build" for o in result))

    def test_turret_keeps_money_for_live_vehicle_production(self):
        raid = [actor(100 + i, "2tnk", 24, 20 + i) for i in range(2)]
        v = economy_view(cash=1300, enemies=raid)
        result = [i.order for i in Economy().propose(v)]
        self.assertFalse(any(o["cmd"] == "build" for o in result))
        self.assertTrue(any(o["cmd"] == "train" and o["item"] == "2tnk" for o in result))

    def test_pillbox_and_reserved_opening_tank_share_real_budget(self):
        policy = Economy()
        raid = [actor(100, "e1", 29, 23)]
        for now in (300, 306, 312):
            v = economy_view(now, cash=1650, enemies=raid)
            v.units = [u for u in v.units if u["type"] != "2tnk" or u["id"] < 42]
            result = [i.order for i in policy.propose(v)]
        self.assertIn({"cmd": "build", "item": "pbox"}, result)
        self.assertIn({"cmd": "train", "item": "2tnk"}, result)
        spent = sum(v.cost(o["item"]) * o.get("count", 1)
                    for o in result if o["cmd"] in {"build", "train"})
        self.assertLessEqual(spent, 1650)

    def test_recent_armored_raids_keep_anti_tank_choice_after_contact_lost(self):
        policy = Economy()
        raid = [actor(100, "2tnk", 29, 23)]
        for now in (300, 306, 312):
            build_orders(policy, economy_view(now, cash=500, enemies=raid))
        self.assertEqual(build_orders(policy, economy_view(320)), [{"cmd": "build", "item": "gun"}])

    def test_hard_two_tower_cap_survives_large_raid(self):
        towers = [actor(70, "pbox", 24, 16), actor(71, "gun", 24, 26)]
        raid = [actor(100 + i, "2tnk", 27, 20 + i % 3) for i in range(9)]
        policy = Economy()
        for now in (300, 306, 312, 320):
            self.assertEqual(build_orders(policy, economy_view(now, enemies=raid, towers=towers)), [])

    def test_existing_pillbox_does_not_block_anti_tank_response(self):
        policy = Economy()
        tower = [actor(70, "pbox", 27, 26)]
        raid = [actor(100 + i, "2tnk", 29, 23 + i) for i in range(2)]
        for now in (300, 306):
            self.assertEqual(build_orders(policy, economy_view(now, enemies=raid, towers=tower)), [])
        self.assertEqual(build_orders(policy, economy_view(312, enemies=raid, towers=tower)),
                         [{"cmd": "build", "item": "gun"}])

    def test_misplaced_turret_does_not_count_as_ore_coverage(self):
        policy = Economy()
        tower = [actor(70, "gun", 10, 18)]
        raid = [actor(100 + i, "2tnk", 29, 23 + i) for i in range(2)]
        for now in (300, 306, 312):
            result = build_orders(policy, economy_view(now, enemies=raid, towers=tower))
        self.assertEqual(result, [{"cmd": "build", "item": "gun"}])

    def test_effective_turret_coverage_does_not_buy_redundant_second_tower(self):
        policy = Economy()
        tower = [actor(70, "gun", 27, 26)]
        raid = [actor(100 + i, "2tnk", 29, 23 + i) for i in range(2)]
        for now in (300, 306, 312, 324):
            self.assertEqual(build_orders(policy, economy_view(now, enemies=raid, towers=tower)), [])

    def test_second_tower_correction_still_requires_large_free_budget(self):
        policy = Economy()
        tower = [actor(70, "pbox", 27, 26)]
        raid = [actor(100 + i, "2tnk", 29, 23 + i) for i in range(2)]
        for now in (300, 306, 312, 324):
            self.assertEqual(build_orders(policy, economy_view(now, cash=2300, enemies=raid, towers=tower)), [])

    def test_ground_turret_does_not_block_repeated_air_raid_response(self):
        policy = Economy()
        tower = [actor(70, "gun", 27, 26)]
        raid = [actor(100 + i, "yak", 29, 23 + i) for i in range(2)]
        for now in (300, 306, 312, 318, 324):
            v = economy_view(now, enemies=raid, towers=tower)
            v.catalog["yak"] = {"queue": "Aircraft", "speed": 4.35,
                                "weapon": {"weapon": "ChainGun.Yak", "range_cells": 5, "damage": 4000}}
            v.catalog["agun"] = {"cost": 800, "power": -50, "queue": "Defense", "build_time_s": 24}
            v.legal["build"].append("agun")
            result = build_orders(policy, v)
        self.assertEqual(result, [{"cmd": "build", "item": "agun"}])

    def test_tower_placement_leaves_ore_and_refinery_lane_clear_and_retries(self):
        policy = Economy()
        raid = [actor(100 + i, "2tnk", 29, 23 + i) for i in range(2)]
        self.assertTrue(build_orders(policy, economy_view(enemies=raid)))
        destinations = []
        for now in (320, 324, 328):
            v = economy_view(now, enemies=raid, place=["gun"])
            placements = [i.order for i in policy.propose(v) if i.order["cmd"] == "place"]
            self.assertEqual(len(placements), 1)
            p = placements[0]["at"]
            destinations.append(tuple(p))
            self.assertEqual(validate_order(placements[0], v), placements[0])
            self.assertNotIn(tuple(p), policy._map.resources)
            self.assertGreaterEqual(distance(p, (20, 20)), 4)
            self.assertFalse(20 <= p[0] <= 31 and 18 <= p[1] <= 22)
        self.assertGreater(len(set(destinations)), 1)

    def test_no_placement_on_impassable_or_ore_only_surroundings(self):
        policy = Economy()
        raid = [actor(100 + i, "2tnk", 29, 23 + i) for i in range(2)]
        v = economy_view(enemies=raid)
        v.map_info["layout"]["rows"] = ["$" * 96 for _ in range(96)]
        self.assertEqual(build_orders(policy, v), [])
