import unittest
from unittest.mock import patch

from altru_redalert.ground_routes import GroundRoutes
from altru_redalert.model import View, distance
from altru_redalert.opportunities import RaidOpportunities, _search
from redalert_bot_tests.test_adversarial import actor, snapshot
from redalert_bot_tests.test_tank_cohesive_v3 import mapped


class EconomicRaidOpportunities(unittest.TestCase):
    def setUp(self):
        self.squad = [actor(i, '2tnk', 20, 40 + i % 2) for i in range(1, 4)]
        self.planner = RaidOpportunities()

    def view(self, *, now=400, enemies=(), buildings=(), rows=None, squad=None, remaining=800):
        return mapped(snapshot(now, units=self.squad if squad is None else squad,
                               enemies=enemies, enemy_buildings=buildings,
                               remaining=remaining), rows)

    def test_exposed_expansion_is_chosen_over_nearby_turret_covered_main(self):
        main = actor(100, 'proc', 42, 40)
        expansion = actor(101, 'proc', 45, 65)
        view = self.view(buildings=[main, actor(102, 'gun', 42, 40), expansion])
        choice = self.planner.choose(view, self.squad)
        self.assertIsNotNone(choice)
        self.assertEqual(choice.target['id'], expansion['id'])
        self.assertLessEqual(distance(self.squad[0], choice.waypoint), 7.)
        self.assertGreater(min(distance(p, (42, 40)) for p in choice.path), 7.5)

    def test_visible_moving_mcv_is_more_valuable_than_equally_exposed_harvester(self):
        mcv = actor(100, 'mcv', 45, 40, activity='Move')
        harvester = actor(101, 'harv', 45, 42)
        choice = self.planner.choose(self.view(enemies=[harvester, mcv]), self.squad)
        self.assertEqual(choice.target['id'], 100)
        self.assertLess(choice.kill_seconds, 15.)

    def test_safe_flank_avoids_visible_tower_on_direct_route(self):
        view = self.view(enemies=[actor(100, 'harv', 55, 40)],
                         buildings=[actor(101, 'gun', 37, 40)])
        routes = GroundRoutes(view)
        choice = self.planner.choose(view, self.squad, routes=routes)
        self.assertIsNotNone(choice)
        self.assertGreater(min(distance(p, (37, 40)) for p in choice.path), 7.5)
        self.assertTrue(all(b in dict(routes._neighbors(a))
                            for a, b in zip(choice.path, choice.path[1:])))
        self.assertLessEqual(distance(choice.path[-1], choice.target), 4.15)

    def test_remembered_tower_blocks_only_crossing_then_expires(self):
        rows = ['~' * 96 for _ in range(96)]
        rows[40 - 4] = '.' * 96
        squad = [{**a, 'y': 40} for a in self.squad]
        memory = {102: (actor(102, 'gun', 35, 40), 400, True)}
        target = actor(100, 'harv', 50, 40)
        early = self.view(now=410, enemies=[target], rows=rows, squad=squad)
        late = self.view(now=491, enemies=[target], rows=rows, squad=squad)
        self.assertIsNone(self.planner.choose(early, squad, memory))
        self.assertIsNotNone(self.planner.choose(late, squad, memory))

    def test_recent_mobile_guard_memory_expires_without_creating_permanent_wall(self):
        target = actor(100, 'harv', 40, 40)
        memory = {200 + i: (actor(200 + i, '3tnk', 40, 40), 400, False)
                  for i in range(8)}
        self.assertIsNone(self.planner.choose(self.view(now=405, enemies=[target]),
                                             self.squad, memory))
        self.assertIsNotNone(self.planner.choose(self.view(now=421, enemies=[target]),
                                                self.squad, memory))

    def test_target_memory_and_guessed_enemy_base_are_not_attack_candidates(self):
        memory = {100: (actor(100, 'harv', 40, 40), 399, False),
                  101: (actor(101, 'proc', 50, 40), 399, True)}
        self.assertIsNone(self.planner.choose(self.view(), self.squad, memory))

    def test_mobile_target_across_disconnected_land_is_not_chased(self):
        rows = ['.' * 30 + '~' * 10 + '.' * 56 for _ in range(96)]
        view = self.view(enemies=[actor(100, 'mcv', 45, 40)], rows=rows)
        self.assertIsNone(self.planner.choose(view, self.squad))

    def test_armed_response_near_target_prevents_raid_even_outside_current_range(self):
        target = actor(100, 'harv', 40, 40)
        guards = [actor(200 + i, '3tnk', 40, 49) for i in range(8)]
        view = self.view(enemies=[target] + guards)
        self.assertIsNone(self.planner.choose(view, self.squad))

    def test_emergency_blocks_economic_diversion(self):
        view = self.view(enemies=[actor(100, 'mcv', 30, 40)])
        self.assertIsNone(self.planner.choose(view, self.squad, emergency=True))
        self.assertIsNotNone(self.planner.choose(view, self.squad))

    def test_disabled_visible_and_anti_air_towers_do_not_block_ground_raid(self):
        view = self.view(enemies=[actor(100, 'harv', 40, 40)], buildings=[
            actor(101, 'gun', 32, 40, powered=False), actor(102, 'sam', 33, 40)])
        self.assertIsNotNone(self.planner.choose(view, self.squad))

    def test_old_tower_power_outage_is_not_assumed_to_continue_in_fog(self):
        rows = ['~' * 96 for _ in range(96)]
        rows[40 - 4] = '.' * 96
        squad = [{**a, 'y': 40} for a in self.squad]
        memory = {102: (actor(102, 'gun', 35, 40, powered=False), 400, True)}
        view = self.view(now=410, enemies=[actor(100, 'harv', 50, 40)], rows=rows)
        self.assertIsNone(self.planner.choose(view, squad, memory))

    def test_visible_contact_replaces_stale_position_without_double_counting(self):
        memory = {102: (actor(102, 'gun', 35, 40), 400, True)}
        view = self.view(now=410, enemies=[actor(100, 'harv', 45, 40)],
                         buildings=[actor(102, 'gun', 90, 90)])
        choice = self.planner.choose(view, self.squad, memory)
        self.assertIsNotNone(choice)
        self.assertLess(max(p[1] for p in choice.path), 43)

    def test_unarmed_or_ineffective_squad_does_not_start_long_harvester_chase(self):
        squad = [actor(1, 'harv', 20, 40), actor(2, 'e1', 20, 40)]
        self.assertIsNone(self.planner.choose(self.view(enemies=[actor(100, 'harv', 40, 40)],
                                                       squad=squad), squad))

    def test_insufficient_remaining_time_does_not_start_new_raid(self):
        view = self.view(enemies=[actor(100, 'harv', 55, 40)], remaining=20)
        self.assertIsNone(self.planner.choose(view, self.squad))

    def test_dispersed_raiders_must_regroup_before_being_counted_as_one_force(self):
        squad = [self.squad[0], {**self.squad[1], 'x': 55}]
        view = self.view(enemies=[actor(100, 'harv', 60, 40)], squad=squad)
        self.assertIsNone(self.planner.choose(view, squad))

    def test_missing_layout_allows_short_observed_raid_but_not_long_unverified_route(self):
        near = View(snapshot(400, units=self.squad, enemies=[actor(100, 'harv', 40, 40)]))
        far = View(snapshot(400, units=self.squad, enemies=[actor(100, 'harv', 70, 40)]))
        self.assertIsNotNone(self.planner.choose(near, self.squad))
        self.assertIsNone(self.planner.choose(far, self.squad))

    def test_success_cache_reuses_search_for_one_second_but_returns_current_actor(self):
        target = actor(100, 'harv', 45, 40)
        with patch('altru_redalert.opportunities._search', wraps=_search) as search:
            first = self.planner.choose(self.view(now=400, enemies=[target]), self.squad)
            current = {**target, 'activity': 'HarvestResource'}
            second = self.planner.choose(self.view(now=400.8, enemies=[current]), self.squad)
            self.assertEqual(search.call_count, 1)
            self.assertEqual(second.path, first.path)
            self.assertIs(second.target, current)
            self.planner.choose(self.view(now=401, enemies=[target]), self.squad)
            self.assertEqual(search.call_count, 2)

    def test_impossible_route_result_is_cached_too(self):
        rows = ['~' * 96 for _ in range(96)]
        rows[40 - 4] = '.' * 96
        squad = [{**a, 'y': 40} for a in self.squad]
        target, guard = actor(100, 'harv', 50, 40), actor(102, 'gun', 35, 40)
        with patch('altru_redalert.opportunities._search', wraps=_search) as search:
            for now in (400, 400.2, 400.4, 400.6, 400.8):
                view = self.view(now=now, enemies=[target], buildings=[guard], rows=rows)
                self.assertIsNone(self.planner.choose(view, squad))
            self.assertEqual(search.call_count, 1)

    def test_new_tower_invalidates_success_cache_immediately(self):
        target = actor(100, 'harv', 45, 40)
        self.assertIsNotNone(self.planner.choose(self.view(enemies=[target]), self.squad))
        updated = self.view(now=400.2, enemies=[target], buildings=[actor(102, 'gun', 45, 40)])
        self.assertIsNone(self.planner.choose(updated, self.squad))

    def test_guard_movement_invalidates_success_cache_immediately(self):
        target = actor(100, 'harv', 45, 40)
        before = self.view(enemies=[target], buildings=[actor(102, 'gun', 90, 90)])
        self.assertIsNotNone(self.planner.choose(before, self.squad))
        after = self.view(now=400.2, enemies=[target], buildings=[actor(102, 'gun', 45, 40)])
        self.assertIsNone(self.planner.choose(after, self.squad))

    def test_squad_damage_or_loss_invalidates_search_cache_immediately(self):
        target = actor(100, 'harv', 45, 40)
        with patch('altru_redalert.opportunities._search', wraps=_search) as search:
            self.planner.choose(self.view(enemies=[target]), self.squad)
            wounded = [{**self.squad[0], 'hp': 99}] + self.squad[1:]
            self.planner.choose(self.view(now=400.2, enemies=[target], squad=wounded), wounded)
            survivors = wounded[:2]
            self.planner.choose(self.view(now=400.4, enemies=[target], squad=survivors), survivors)
            self.assertEqual(search.call_count, 3)

    def test_disappeared_target_is_never_returned_from_cache(self):
        self.assertIsNotNone(self.planner.choose(self.view(enemies=[actor(100, 'harv', 45, 40)]),
                                                self.squad))
        self.assertIsNone(self.planner.choose(self.view(now=400.2), self.squad))

    def test_memory_expiry_invalidates_negative_cache_before_one_second(self):
        rows = ['~' * 96 for _ in range(96)]
        rows[40 - 4] = '.' * 96
        squad = [{**a, 'y': 40} for a in self.squad]
        memory = {102: (actor(102, 'gun', 35, 40), 400, True)}
        target = actor(100, 'harv', 50, 40)
        before = self.view(now=489.8, enemies=[target], rows=rows)
        after = self.view(now=490.2, enemies=[target], rows=rows)
        self.assertIsNone(self.planner.choose(before, squad, memory))
        self.assertIsNotNone(self.planner.choose(after, squad, memory))

    def test_squad_movement_recomputes_waypoint_instead_of_reusing_stale_arrival(self):
        target = actor(100, 'harv', 45, 40)
        with patch('altru_redalert.opportunities._search', wraps=_search) as search:
            before = self.planner.choose(self.view(enemies=[target]), self.squad)
            moved = [{**a, 'x': a['x'] + 5} for a in self.squad]
            after = self.planner.choose(self.view(now=400.2, enemies=[target], squad=moved), moved)
            self.assertEqual(search.call_count, 2)
            self.assertNotEqual(after.waypoint, before.waypoint)

    def test_target_movement_recomputes_route_immediately(self):
        with patch('altru_redalert.opportunities._search', wraps=_search) as search:
            self.planner.choose(self.view(enemies=[actor(100, 'harv', 45, 40)]), self.squad)
            moved = actor(100, 'harv', 45, 41)
            choice = self.planner.choose(self.view(now=400.2, enemies=[moved]), self.squad)
            self.assertEqual(search.call_count, 2)
            self.assertIs(choice.target, moved)

    def test_search_budget_is_shared_across_targets_and_exhaustion_returns_no_partial_route(self):
        targets = [actor(100 + i, 'proc', 65, 25 + 3 * i) for i in range(12)]
        view = self.view(buildings=targets)
        routes = GroundRoutes(view)
        with patch('altru_redalert.opportunities.MAX_SEARCH', 10), \
                patch.object(routes, '_neighbors', wraps=routes._neighbors) as neighbors, \
                patch('altru_redalert.opportunities._search', wraps=_search) as search:
            choice = self.planner.choose(view, self.squad, routes=routes)
            self.assertIsNone(choice)
            self.assertEqual(search.call_count, 1)
            self.assertLessEqual(neighbors.call_count, 10)

    def test_budget_exhaustion_retains_only_an_already_validated_safe_opportunity(self):
        nearby = actor(100, 'harv', 22, 40)
        distant = actor(101, 'mcv', 70, 40)
        view = self.view(enemies=[nearby, distant])
        routes = GroundRoutes(view)
        with patch('altru_redalert.opportunities.MAX_SEARCH', 3), \
                patch.object(routes, '_neighbors', wraps=routes._neighbors) as neighbors:
            choice = self.planner.choose(view, self.squad, routes=routes)
            self.assertIsNotNone(choice)
            self.assertEqual(choice.target['id'], nearby['id'])
            self.assertLessEqual(distance(choice.path[-1], nearby), 4.15)
            self.assertTrue(all(cell in routes.cells for cell in choice.path))
            self.assertTrue(all(b in dict(routes._neighbors(a))
                                for a, b in zip(choice.path, choice.path[1:])))
            self.assertLessEqual(neighbors.call_count, 3)


if __name__ == '__main__':
    unittest.main()
