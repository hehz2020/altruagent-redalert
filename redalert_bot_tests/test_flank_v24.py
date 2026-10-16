import unittest
from unittest.mock import patch

from altru_redalert.combat import Military
from altru_redalert.core import validate_order
from altru_redalert.flanking import FlankPlanner, _length
from altru_redalert.ground_routes import GroundRoutes
from altru_redalert.model import View, distance
from redalert_bot_tests.test_adversarial import actor, snapshot
from redalert_bot_tests.test_tank_cohesive_v3 import mapped


class FlankRouteTests(unittest.TestCase):
    def setUp(self):
        self.army = [actor(i, '2tnk', 20, 40) for i in range(1, 7)]
        self.towers = [actor(100 + i, 'gun', 45, 37 + 3 * i) for i in range(3)]
        self.factory = actor(200, 'weap', 75, 40)

    def make_view(self, now=400, towers=None, rows=None):
        towers = self.towers if towers is None else towers
        return mapped(snapshot(now, units=self.army,
                               enemy_buildings=towers + [self.factory]), rows)

    def test_factory_target_and_reachable_flank_bypass_front_turrets(self):
        view = self.make_view()
        military = Military()
        military._remember(view, self.army)
        goal = military._goal(view, (20, 40))
        self.assertEqual(goal, (75, 40))
        point = military._march_point(view, self.army, goal)
        planner, routes = military.flank_planner, military.ground_routes
        direct = routes.path((20, 40), goal)
        self.assertTrue(planner.flanking)
        self.assertLessEqual(distance((20, 40), point), 6.)
        self.assertGreater(min(distance(cell, (45, 40)) for cell in planner.path), 9.)
        self.assertLessEqual(_length(planner.path), _length(direct) * 1.7 + 4.1)
        self.assertEqual(planner.path[-1], goal)
        self.assertTrue(all(b in dict(routes._neighbors(a))
                            for a, b in zip(planner.path, planner.path[1:])))
        self.assertTrue(all(validate_order(i.order, view) is not None
                            for i in military.propose(view)))

    def test_route_is_sticky_for_small_enemy_movement_and_reuses_search(self):
        military = Military()
        view = self.make_view()
        military._march_point(view, self.army, (75, 40))
        initial = list(military.flank_planner.path)
        with patch.object(military.flank_planner, '_choose', wraps=military.flank_planner._choose) as choose:
            for tick in range(1, 20):
                moved = [{**tower, 'x': tower['x'] + tick % 2} for tower in self.towers]
                current = self.make_view(400 + tick * .25, towers=moved)
                military._march_point(current, self.army, (75, 40))
            self.assertEqual(choose.call_count, 0)
        self.assertEqual(military.flank_planner.path, initial)

    def test_new_enemy_army_on_selected_flank_triggers_replan(self):
        military = Military()
        view = self.make_view()
        military._march_point(view, self.army, (75, 40))
        planner = military.flank_planner
        prior = list(planner.path)
        location = prior[16]
        blockers = [actor(300 + i, '3tnk', *location) for i in range(12)]
        updated = mapped(snapshot(404, units=self.army, enemies=blockers,
                                  enemy_buildings=self.towers + [self.factory]))
        military._march_point(updated, self.army, (75, 40))
        self.assertEqual(planner.created, 404)
        self.assertNotEqual(planner.path, prior)
        self.assertGreater(min(distance(cell, location) for cell in planner.path), 5.)

    def test_one_cell_choke_does_not_invent_path_through_water(self):
        rows = ['~' * 96 for _ in range(96)]
        rows[40 - 4] = '.' * 96
        military = Military()
        view = self.make_view(rows=rows)
        military._march_point(view, self.army, (75, 40))
        self.assertTrue(military.flank_planner.path)
        self.assertTrue(all(y == 40 for x, y in military.flank_planner.path))
        self.assertEqual(military.flank_planner.path[-1], (75, 40))
        self.assertFalse(military.flank_planner.flanking)

    def test_disconnected_target_is_projected_to_own_component(self):
        rows = ['.' * 40 + '~' + '.' * 55 for _ in range(96)]
        military = Military()
        view = self.make_view(rows=rows)
        military._march_point(view, self.army, (75, 40))
        self.assertTrue(all(x < 44 for x, y in military.flank_planner.path))
        self.assertTrue(military.ground_routes.reachable((20, 40), military.flank_planner.path[-1]))

    def test_unseen_mobile_contact_expires_and_does_not_become_permanent_wall(self):
        planner = FlankPlanner()
        view = self.make_view(towers=[])
        enemy = actor(300, '3tnk', 45, 40)
        contacts = {300: (enemy, 395, False)}
        threats = planner._threats(view, self.army, contacts)
        self.assertEqual([x[0] for x in threats], [300])
        self.assertEqual(planner._threats(self.make_view(416, towers=[]), self.army, contacts), [])

    def test_noncombat_and_antiair_towers_do_not_force_ground_flanks(self):
        military = Military()
        harmless = [actor(100, 'sam', 45, 40), actor(101, 'proc', 50, 40)]
        view = self.make_view(towers=harmless)
        military._march_point(view, self.army, (75, 40))
        self.assertFalse(military.flank_planner.flanking)
        self.assertEqual({y for x, y in military.flank_planner.path}, {40})

    def test_stalled_route_tries_a_short_local_alternative(self):
        military = Military()
        military._march_point(self.make_view(towers=[]), self.army, (75, 40))
        prior = list(military.flank_planner.path)
        military._march_point(self.make_view(413, towers=[]), self.army, (75, 40))
        planner = military.flank_planner
        self.assertTrue(planner.blocked_until)
        self.assertNotEqual(planner.path, prior)
        self.assertLess(_length(planner.path), _length(prior) + 8.)

    def test_changed_map_discards_old_path_without_crossing_new_wall(self):
        military = Military()
        military._march_point(self.make_view(towers=[]), self.army, (75, 40))
        previous = military.flank_planner.navigation
        rows = ['.' * 25 + '~' + '.' * 70 for _ in range(96)]
        military._march_point(self.make_view(401, towers=[], rows=rows), self.army, (75, 40))
        self.assertIsNot(military.flank_planner.navigation, previous)
        self.assertTrue(all(x < 29 for x, y in military.flank_planner.path))


class AssaultCommitmentTests(unittest.TestCase):
    def setUp(self):
        self.army = [actor(i, '2tnk', 46, 30 + i % 2) for i in range(1, 7)]
        self.factory = actor(200, 'weap', 60, 30)

    def current(self, now, count, army=None):
        enemies = [actor(100 + i, '2tnk', 57 + i % 2, 30 + i % 3) for i in range(count)]
        return View(snapshot(now, units=self.army if army is None else army,
                             enemies=enemies, enemy_buildings=[self.factory]))

    def test_favorable_attack_continues_through_small_guard_reinforcement(self):
        military = Military()
        military.propose(self.current(400, 5))
        self.assertEqual(military.mode, 'pressure')
        deadline = military.assault_until
        self.assertGreater(deadline, 400)
        military.propose(self.current(404, 7))
        self.assertEqual(military.mode, 'pressure')
        self.assertEqual(military.assault_until, deadline)

    def test_large_reinforcement_overrides_attack_commitment(self):
        military = Military()
        military.propose(self.current(400, 5))
        result = military.propose(self.current(404, 12))
        self.assertEqual(military.mode, 'retreat')
        self.assertEqual(military.assault_until, 0.)
        self.assertTrue(any(i.order['cmd'] == 'move' for i in result))

    def test_heavy_losses_invalidate_commitment_even_before_deadline(self):
        military = Military()
        military.propose(self.current(400, 5))
        military.propose(self.current(404, 5, self.army[:3]))
        self.assertEqual(military.mode, 'retreat')
        self.assertEqual(military.assault_until, 0.)

    def test_marginal_fight_does_not_renew_commitment_forever(self):
        military = Military()
        military.propose(self.current(400, 5))
        military.propose(self.current(419, 7))
        self.assertEqual(military.mode, 'standoff')
        self.assertLess(military.assault_until, 419)

    def test_back_attack_ignores_turrets_without_range_on_approach(self):
        army = [actor(i, '2tnk', 72, 40) for i in range(1, 4)]
        towers = [actor(100 + i, 'gun', 49, 38 + i) for i in range(5)]
        goal = (60, 40)
        view = View(snapshot(400, units=army, enemy_buildings=towers))
        military = Military()
        self.assertEqual(military._resistance(view, goal, towers, army), [])
        self.assertIsNone(military._assault_standoff(view, army, goal, towers))
        front = [{**a, 'x': 45} for a in army]
        self.assertTrue(military._resistance(view, goal, towers, front))
        self.assertIsNotNone(military._assault_standoff(view, front, goal, towers))


if __name__ == '__main__':
    unittest.main()
