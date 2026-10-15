"""Combo regressions for reachable bounds and unified tower disengagement."""
import unittest

from altru_redalert.combat import Military
from altru_redalert.core import validate_order
from altru_redalert.model import View, distance
from redalert_bot_tests.test_adversarial import actor, snapshot


def mapped(raw, rows=None):
    rows = rows if rows is not None else ['.' * 96 for _ in range(96)]
    return View(raw, {'rules': {'maps': {'scenario-map': {'layout': {
        'origin': [4, 4], 'rows': rows}}}}})


class TankCohesiveTests(unittest.TestCase):
    def test_short_march_follows_route_around_water_instead_of_opposite_bank(self):
        # A vertical river has its only bridge far south. Euclidean six-cell
        # bounds point east onto the other bank, while the reachable route
        # starts south on the current bank.
        rows = ['.' * 96 for _ in range(96)]
        for y in range(4, 45):
            row = list(rows[y - 4])
            row[33 - 4] = '~'
            rows[y - 4] = ''.join(row)
        army = [actor(i, 'e1', 30, 30) for i in range(1, 7)]
        army += [actor(20, '3tnk', 31, 30)]
        view = mapped(snapshot(400, units=army), rows)
        military = Military()
        orders = military._cohesive_advance(view, army, army, (60, 30))
        self.assertTrue(orders)
        goal = orders[0].order['to']
        self.assertLess(goal[0], 33)
        self.assertGreater(goal[1], 30)
        self.assertTrue(military.ground_routes.reachable((30, 30), goal))
        self.assertLessEqual(distance((30, 30), goal), 7)

    def test_new_layout_invalidates_cached_geometric_bound_immediately(self):
        army = [actor(i, 'e1', 30, 30) for i in range(1, 7)]
        military = Military()
        raw = snapshot(400, units=army)
        original = military._cohesive_advance(View(raw), army, army, (60, 30))[0].order['to']
        self.assertGreater(original[0], 33)
        rows = ['.' * 96 for _ in range(96)]
        for y in range(4, 45):
            row = list(rows[y - 4])
            row[33 - 4] = '~'
            rows[y - 4] = ''.join(row)
        mapped_view = mapped(snapshot(400.2, units=army), rows)
        updated = military._cohesive_advance(mapped_view, army, army, (60, 30))[0].order['to']
        self.assertLess(updated[0], 33)
        self.assertGreater(updated[1], 30)

    def test_standoff_cancels_previously_focused_tanks_and_moves_infantry_together(self):
        tanks = [{**actor(i, '3tnk', 45, 30 + i % 2), 'idle': False} for i in range(1, 4)]
        army = tanks + [actor(i, 'e1', 37, 30 + i % 2) for i in range(10, 18)]
        towers = [actor(i, 'tsla', 50, 28 + i % 5) for i in range(100, 103)]
        view = mapped(snapshot(400, units=army, enemy_buildings=towers))
        military = Military()
        military.mark_sent([{'cmd': 'attack', 'units': [1, 2, 3], 'target': 100}], 399)
        orders = military.propose(view)
        self.assertEqual(military.mode, 'standoff')
        line = [i.order for i in orders if any(uid in i.order.get('units', []) for uid in (1, 2, 3))]
        self.assertTrue(line)
        self.assertEqual({uid for o in line for uid in o['units'] if uid in (1, 2, 3)}, {1, 2, 3})
        self.assertTrue(all(o['cmd'] == 'move' and o['to'][0] < 40 for o in line))
        self.assertFalse(any(i.order['cmd'] == 'attack' for i in orders))
        self.assertTrue(all(validate_order(i.order, view) is not None for i in orders))

    def test_at_safe_point_old_direct_attack_is_still_cancelled(self):
        view = mapped(snapshot(400, units=[{**actor(1, '3tnk', 35, 30), 'idle': False}]))
        military = Military()
        military.mark_sent([{'cmd': 'attack', 'units': [1], 'target': 100}], 399)
        orders = military._orders(view, view.units, 'move', (35, 30), 'squad-standoff',
                                  94, arrival=.75, interrupt=True)
        self.assertEqual([i.order for i in orders], [{'cmd': 'move', 'units': [1], 'to': [35, 30]}])

    def test_standoff_does_not_cancel_independent_home_defense(self):
        army = [actor(i, '3tnk', 45, 30 + i % 2) for i in range(1, 4)]
        army += [actor(i, 'e1', 37, 30 + i % 2) for i in range(10, 18)]
        army += [actor(40, 'ftrk', 14, 12), actor(41, 'e1', 14, 13)]
        towers = [actor(i, 'tsla', 50, 28 + i % 5) for i in range(100, 103)]
        view = mapped(snapshot(400, units=army, enemy_buildings=towers,
                               buildings=[actor(90, 'proc', 12, 12)],
                               enemies=[actor(500, 'e1', 16, 12)]))
        orders = Military().propose(view)
        self.assertTrue(any(i.order['cmd'] == 'attack' and i.order['target'] == 500
                            and 40 in i.order['units'] for i in orders))
        self.assertTrue(any(i.order['cmd'] == 'move' and 1 in i.order['units'] for i in orders))

    def test_standoff_keeps_safe_artillery_firing(self):
        tanks = [actor(i, '3tnk', 45, 30 + i % 2) for i in range(1, 4)]
        army = tanks + [actor(i, 'e1', 37, 30 + i % 2) for i in range(10, 18)]
        army += [actor(30, 'arty', 40, 30)]
        towers = [actor(i, 'tsla', 50, 28 + i % 5) for i in range(100, 104)]
        view = mapped(snapshot(400, units=army, enemy_buildings=towers))
        orders = Military().propose(view)
        self.assertTrue(any(i.order['cmd'] == 'move' and 1 in i.order['units'] for i in orders))
        self.assertTrue(any(i.order['cmd'] == 'attack' and 30 in i.order['units'] for i in orders))


if __name__ == '__main__':
    unittest.main()
