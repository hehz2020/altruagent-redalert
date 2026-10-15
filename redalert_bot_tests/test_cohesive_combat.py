"""Candidate C: concrete formation/range contracts, not a win-rate claim."""
import unittest

from altru_redalert.combat import Military
from altru_redalert.core import validate_order
from altru_redalert.model import View, distance
from redalert_bot_tests.test_adversarial import actor, snapshot


class CohesiveCombatTests(unittest.TestCase):
    def test_original_early_force_advances_without_racing_to_far_base(self):
        army = [actor(i, 'e1', 30 + i % 2, 30 + i % 3) for i in range(1, 10)]
        army.append(actor(20, 'ftrk', 31, 31))
        military = Military()
        view = View(snapshot(120, units=army))
        orders = military.propose(view)
        self.assertEqual(military.mode, 'pressure')
        truck = [i.order for i in orders if 20 in i.order.get('units', [])]
        self.assertEqual(len(truck), 1)
        self.assertEqual(truck[0]['cmd'], 'attack_move')
        self.assertGreater(truck[0]['to'][0], 31)
        self.assertLessEqual(distance(truck[0]['to'], (31, 31)), 7)
        self.assertTrue(all(validate_order(i.order, view) is not None for i in orders))

    def test_repeated_bounds_keep_progressing_with_the_infantry(self):
        military = Military()
        for now, x in ((120, 30), (124, 35), (128, 40)):
            army = [actor(i, 'e1', x, 30) for i in range(1, 10)] + [actor(20, 'ftrk', x + 5, 30)]
            view = View(snapshot(now, units=army))
            orders = military.propose(view)
            march = [i.order for i in orders if i.order['cmd'] == 'attack_move']
            self.assertTrue(march)
            self.assertTrue(all(x < o['to'][0] <= x + 7 for o in march))
            military.mark_sent([i.order for i in orders], now)

    def test_exposed_vehicle_moves_back_to_its_body_while_infantry_advances(self):
        army = [actor(i, 'e1', 30, 30 + i % 2) for i in range(1, 10)]
        army.append(actor(20, 'ftrk', 55, 30))
        enemy = [actor(100, 'e1', 59, 30)]
        military = Military()
        view = View(snapshot(150, units=army, enemies=enemy))
        orders = military.propose(view)
        truck = [i.order for i in orders if 20 in i.order.get('units', [])]
        self.assertEqual(len(truck), 1)
        self.assertEqual(truck[0]['cmd'], 'move')
        self.assertLess(truck[0]['to'][0], 40)
        self.assertTrue(any(i.order['cmd'] == 'attack_move' and i.order['to'][0] > 30
                            for i in orders))
        self.assertTrue(all(validate_order(i.order, view) is not None for i in orders))

    def test_flak_uses_range_edge_but_jeep_and_infantry_do_not_invent_one(self):
        for kind, should_kite in (('ftrk', True), ('jeep', False), ('e1', False)):
            with self.subTest(kind=kind):
                unit = actor(20, kind, 30, 30)
                enemy = actor(100, 'e1', 34, 30)
                view = View(snapshot(300, units=[unit], enemies=[enemy]))
                orders, reserved = Military()._screen_skirmish(view, [unit], [enemy], (60, 30))
                self.assertEqual(bool(orders), should_kite)
                self.assertEqual(bool(reserved), should_kite)
                if should_kite:
                    self.assertEqual(orders[0].order['cmd'], 'move')
                    self.assertGreater(distance(orders[0].order['to'], enemy), 5)
                    self.assertLessEqual(distance(orders[0].order['to'], enemy), 6)

    def test_distant_reinforcements_do_not_pull_front_group_home(self):
        army = [actor(i, 'e1', 45, 30) for i in range(1, 7)]
        army += [actor(i, 'e1', 12, 12) for i in range(10, 14)]
        self.assertEqual(Military()._body_center(army, (60, 30)), (45, 30))


if __name__ == '__main__':
    unittest.main()
