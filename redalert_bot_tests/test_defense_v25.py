import unittest

from altru_redalert.combat import Military
from altru_redalert.core import validate_order
from altru_redalert.model import View, distance
from redalert_bot_tests.test_adversarial import actor, snapshot


def defense_view(now, army, miners, enemies=(), buildings=None):
    if buildings is None:
        buildings = [actor(1, "proc", 22, 20)]
    return View(snapshot(now, units=army + miners, buildings=buildings, enemies=enemies))


class DefenseAllocationScenarios(unittest.TestCase):
    def setUp(self):
        self.main = [actor(i, "2tnk", 70 + i % 3, 65 + i // 3) for i in range(10, 25)]
        self.guard = actor(31, "apc", 27, 22)
        self.army = self.main + [self.guard]
        self.miners = [actor(30, "harv", 28, 20)]
        self.raider = actor(100, "e1", 31, 20)

    def defend(self, policy, view, army):
        intents, assigned = policy._defense(view, army, view.enemies)
        self.assertTrue(all(validate_order(intent.order, view) for intent in intents))
        ids = [uid for intent in intents for uid in intent.order.get("units", [])]
        self.assertEqual(len(ids), len(set(ids)), "a defender must receive only one role")
        policy.mark_sent([intent.order for intent in intents], view.now)
        return [intent.order for intent in intents], assigned

    def test_two_mine_attacks_receive_separate_nearby_escorts(self):
        army = self.army + [actor(32, "apc", 27, 38)]
        miners = self.miners + [actor(33, "harv", 28, 40)]
        enemies = [self.raider, actor(101, "e1", 31, 40)]
        buildings = [actor(1, "proc", 22, 20), actor(2, "proc", 22, 40)]
        v = defense_view(300, army, miners, enemies, buildings)
        orders, assigned = self.defend(Military(), v, army)
        self.assertEqual(assigned, {31, 32})
        intercepts = {tuple(order["to"]) for order in orders if order["cmd"] == "attack_move"}
        self.assertEqual(intercepts, {(31, 20), (31, 40)})

    def test_one_raid_threatening_two_miners_is_not_counted_twice(self):
        army = self.army + [actor(32, "apc", 27, 26)]
        miners = self.miners + [actor(33, "harv", 28, 24)]
        v = defense_view(300, army, miners, [actor(100, "e1", 31, 22)])
        _, assigned = self.defend(Military(), v, army)
        self.assertEqual(len(assigned), 1)

    def test_adjacent_mine_posts_do_not_overwrite_each_others_guards(self):
        policy = Military()
        army = self.main + [actor(31, "apc", 29, 19), actor(32, "apc", 29, 29)]
        miners = [actor(30, "harv", 28, 20), actor(33, "harv", 28, 28)]
        enemies = [actor(100, "e1", 35, 17), actor(101, "e1", 35, 31)]
        buildings = [actor(1, "proc", 22, 24)]
        current = defense_view(300, army, miners, enemies, buildings)
        self.assertEqual(self.defend(policy, current, army)[1], {31, 32})
        fog = defense_view(302, army, miners, buildings=buildings)
        orders, assigned = self.defend(policy, fog, army)
        self.assertEqual(assigned, {31, 32})
        self.assertEqual(len(orders), 2)
        self.assertTrue(all(order["cmd"] == "move" for order in orders))
        self.assertNotEqual(orders[0]["to"], orders[1]["to"])

    def test_disappearance_cancels_chase_and_keeps_short_mine_road_guard(self):
        policy = Military()
        first = defense_view(300, self.army, self.miners, [self.raider])
        _, first_ids = self.defend(policy, first, self.army)
        moved = self.main + [actor(31, "apc", 35, 20)]
        fog = defense_view(302, moved, self.miners)
        orders, assigned = self.defend(policy, fog, moved)
        self.assertEqual(assigned, first_ids)
        self.assertTrue(orders)
        self.assertTrue(all(order["cmd"] == "move" for order in orders))
        self.assertTrue(all(distance(order["to"], (26, 20)) <= 1 for order in orders))
        # An observation without an enemy must not extend the 18-second lease.
        self.defend(policy, defense_view(317, moved, self.miners), moved)
        self.assertEqual(self.defend(policy, defense_view(318, moved, self.miners), moved),
                         ([], set()))

    def test_visible_raider_retreating_outside_asset_leash_is_not_chased(self):
        policy = Military()
        self.defend(policy, defense_view(300, self.army, self.miners, [self.raider]), self.army)
        moved = self.main + [actor(31, "apc", 36, 20)]
        away = defense_view(302, moved, self.miners, [actor(100, "e1", 46, 20)])
        orders, assigned = self.defend(policy, away, moved)
        self.assertEqual(assigned, {31})
        self.assertTrue(orders)
        self.assertTrue(all(order["cmd"] == "move" and order["to"][0] < 30 for order in orders))

    def test_returning_raider_keeps_existing_escort_without_recalling_main(self):
        policy = Military()
        self.defend(policy, defense_view(300, self.army, self.miners, [self.raider]), self.army)
        self.defend(policy, defense_view(302, self.army, self.miners), self.army)
        army = self.army + [actor(32, "apc", 28, 22)]
        returned = defense_view(306, army, self.miners, [self.raider])
        _, assigned = self.defend(policy, returned, army)
        self.assertEqual(assigned, {31})

    def test_new_threat_can_reassign_a_guard_from_an_inactive_post(self):
        policy = Military()
        self.defend(policy, defense_view(300, self.army, self.miners, [self.raider]), self.army)
        miners = self.miners + [actor(33, "harv", 28, 36)]
        enemies = [actor(101, "e1", 31, 36)]
        current = defense_view(302, self.army, miners, enemies)
        orders, assigned = self.defend(policy, current, self.army)
        self.assertEqual(assigned, {31})
        self.assertTrue(any(order["cmd"] == "attack_move" and order["to"][1] > 30
                            for order in orders))
        self.assertFalse(any(order["cmd"] == "move" and order["to"][1] == 20
                             for order in orders))

    def test_dead_guards_or_absent_assets_cannot_keep_a_post(self):
        for missing in ("guard", "assets"):
            with self.subTest(missing=missing):
                policy = Military()
                self.defend(policy, defense_view(300, self.army, self.miners, [self.raider]), self.army)
                army = self.main if missing == "guard" else self.army
                miners = self.miners if missing == "guard" else []
                buildings = None if missing == "guard" else [actor(2, "proc", 70, 70)]
                view = defense_view(302, army, miners, buildings=buildings)
                self.assertEqual(self.defend(policy, view, army), ([], set()))
                self.assertFalse(policy.defense_posts)

    def test_multiple_scouts_cannot_take_the_whole_attack_army(self):
        sites = (15, 30, 45, 60, 75, 90)
        army = self.main + [actor(40 + i, "apc", 25, y) for i, y in enumerate(sites)]
        miners = [actor(60 + i, "harv", 26, y) for i, y in enumerate(sites)]
        enemies = [actor(100 + i, "e1", 29, y) for i, y in enumerate(sites)]
        view = defense_view(300, army, miners, enemies, [actor(1, "proc", 12, 12)])
        _, assigned = self.defend(Military(), view, army)
        self.assertGreater(len(assigned), 1)
        self.assertLessEqual(len(assigned), 6)
        self.assertLess(len(assigned), len(army) / 2)

    def test_new_effective_tower_releases_mobile_post(self):
        policy = Military()
        self.defend(policy, defense_view(300, self.army, self.miners, [self.raider]), self.army)
        buildings = [actor(1, "proc", 22, 20), actor(2, "pbox", 28, 22)]
        view = defense_view(302, self.army, self.miners, [self.raider], buildings)
        self.assertEqual(self.defend(policy, view, self.army), ([], set()))
        self.assertFalse(policy.defense_posts)


if __name__ == "__main__":
    unittest.main()
