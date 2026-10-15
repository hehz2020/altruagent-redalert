"""Tactical contracts: meaningful scenarios, not claimed win-rate evidence."""
import unittest

from altru_redalert.combat import Military
from altru_redalert.core import validate_order
from altru_redalert.model import View, distance
from altru_redalert.tactics import damage_rate, force_ratio, health, weapon_range
from redalert_bot_tests.test_adversarial import actor, snapshot


class WeaponMatchupTests(unittest.TestCase):
    def test_rocket_ground_arm_is_not_replaced_by_runtime_aa_arm(self):
        cfg = {'rules': {'units': {'e3': {'weapon': {'weapon': 'RedEye',
                'range_cells': 7.5, 'damage': 2400}}}}}
        v = View(snapshot(), cfg)
        rocket, tank, air = actor(1, 'e3'), actor(2, '3tnk'), actor(3, 'yak')
        self.assertEqual(weapon_range(v, rocket, tank), 5.)
        self.assertEqual(weapon_range(v, rocket, air), 7.5)
        self.assertGreater(damage_rate(v, rocket, tank), damage_rate(v, actor(4, 'e1'), tank) * 10)

    def test_rifle_and_flak_target_suitability(self):
        v = View(snapshot())
        rifle, flak, air = actor(1, 'e1'), actor(2, 'ftrk'), actor(3, 'yak')
        self.assertEqual(damage_rate(v, rifle, air), 0)
        self.assertGreater(damage_rate(v, flak, air), 0)
        self.assertGreater(damage_rate(v, flak, rifle), 0)

    def test_armor_changes_preferred_target(self):
        v = View(snapshot())
        rifle, rocket = actor(1, 'e1'), actor(2, 'e3')
        infantry, tank = actor(3, 'e1'), actor(4, '3tnk')
        self.assertGreater(damage_rate(v, rifle, infantry), damage_rate(v, rifle, tank))
        self.assertGreater(damage_rate(v, rocket, tank), damage_rate(v, rocket, infantry))

    def test_runtime_range_damage_and_health_override_matching_fallback(self):
        v = View(snapshot(), {'rules': {'units': {'1tnk': {'hp': 100000,
                 'weapon': {'weapon': '25mm', 'range_cells': 2., 'damage': 100}}}}})
        tank, target = actor(1, '1tnk'), actor(2, '3tnk')
        tank['hp'] = 50
        self.assertEqual(health(v, tank), 50000)
        self.assertEqual(weapon_range(v, tank, target), 2.)
        self.assertEqual(damage_rate(v, tank, target, at_distance=3.), 0.)
        self.assertGreater(damage_rate(v, tank, target, at_distance=1.), 0.)

    def test_artillery_has_minimum_range_and_disabled_defense_no_damage(self):
        v = View(snapshot())
        gun, target = actor(1, 'arty'), actor(2, 'e1')
        self.assertEqual(damage_rate(v, gun, target, at_distance=2.), 0.)
        self.assertGreater(damage_rate(v, gun, target, at_distance=10.), 0.)
        tower = actor(3, 'tsla', powered=False)
        self.assertEqual(damage_rate(v, tower, target), 0.)

    def test_distant_reinforcements_do_not_immediately_win_local_fight(self):
        v = View(snapshot())
        close = [actor(i, '1tnk', 30, 30) for i in range(1, 4)]
        distant = [actor(i, '3tnk', 90, 90) for i in range(10, 30)]
        enemy = [actor(i, '3tnk', 35, 30) for i in range(40, 45)]
        self.assertLess(force_ratio(v, close + distant, enemy), .8)

    def test_projected_tower_counterfire_prevents_false_safe_assault(self):
        v = View(snapshot())
        tanks = [actor(i, '1tnk', 30, 30) for i in range(1, 7)]
        towers = [actor(i, 'tsla', 50, 30) for i in range(100, 106)]
        self.assertGreater(force_ratio(v, tanks, towers, horizon=30), 1.)
        self.assertLess(force_ratio(v, tanks, towers, horizon=30, projected=True), .6)

    def test_projected_tower_does_not_gain_range_against_artillery(self):
        v = View(snapshot())
        guns = [actor(i, 'arty', 30, 30) for i in range(1, 7)]
        towers = [actor(i, 'tsla', 50, 30) for i in range(100, 106)]
        self.assertGreater(force_ratio(v, guns, towers, horizon=30, projected=True), 5.)


class RoleControlTests(unittest.TestCase):
    def test_depleted_force_cannot_renew_pressure_commitment(self):
        for count in (1, 2):
            with self.subTest(survivors=count):
                military = Military()
                army = [actor(i, '1tnk', 30, 30) for i in range(1, 7)]
                first = military.propose(View(snapshot(300, units=army)))
                self.assertEqual(military.mode, 'pressure')
                military.mark_sent([i.order for i in first], 300)
                deadline = military.commit_until
                for now in range(301, 342):
                    orders = military.propose(View(snapshot(now, units=army[:count])))
                    self.assertEqual(military.commit_until, deadline)
                    if now >= deadline:
                        self.assertEqual(military.mode, 'regroup')
                        self.assertFalse(any(i.order.get('to') == [60, 30] for i in orders))
                    military.mark_sent([i.order for i in orders], now)

    def test_retreat_commitment_survives_fog_and_one_favorable_observation(self):
        own = [actor(i, '1tnk', 30, 30 + i % 2) for i in range(1, 7)]
        enemy = [actor(100 + i, '3tnk', 35, 30 + i % 2) for i in range(8)]
        for later_enemy in ([], [{**enemy[0], 'hp': 1}]):
            with self.subTest(later_enemy=later_enemy):
                military = Military()
                first = military.propose(View(snapshot(300, units=own, enemies=enemy)))
                self.assertEqual(military.mode, 'retreat')
                self.assertTrue(any(i.order['cmd'] == 'move' for i in first))
                military.mark_sent([i.order for i in first], 300)
                deadline = military.retreat_until
                for now in (300.2, 303, 306, deadline - .2):
                    orders = military.propose(View(snapshot(now, units=own, enemies=later_enemy)))
                    self.assertEqual(military.mode, 'retreat')
                    self.assertEqual(military.retreat_until, deadline)
                    self.assertFalse(any(i.order['cmd'] == 'attack_move' for i in orders))
                    military.mark_sent([i.order for i in orders], now)
                military.propose(View(snapshot(deadline + .2, units=own)))
                self.assertNotEqual(military.mode, 'retreat')

    def test_air_raid_does_not_recall_ground_only_army(self):
        own = [actor(i, '2tnk', 50 + i % 3, 48 + i // 3) for i in range(1, 10)]
        air = actor(100, 'yak', 18, 13)
        config = {'rules': {'units': {'yak': {'queue': 'Aircraft', 'speed': 4.35,
                  'weapon': {'weapon': 'ChainGun.Yak', 'range_cells': 5., 'damage': 4000}}}}}
        view = View(snapshot(400, units=own, buildings=[actor(90, 'proc', 12, 13)],
                             enemies=[air]), config)
        military = Military()
        orders, defenders = military._defense(view, own, [air])
        self.assertEqual(defenders, set())
        self.assertEqual(orders, [])
        advances = [i.order for i in military.propose(view) if i.order['cmd'] == 'attack_move']
        self.assertTrue(advances)
        self.assertTrue(all(i['to'] != [air['x'], air['y']] for i in advances))

    def test_air_raid_assigns_aa_without_dragging_ground_only_tanks(self):
        own = [actor(i, '2tnk', 16, 13) for i in range(1, 10)]
        own += [actor(20, 'ftrk', 23, 13), actor(21, 'e3', 23, 14)]
        air = actor(100, 'yak', 18, 13)
        config = {'rules': {'units': {'yak': {'queue': 'Aircraft', 'speed': 4.35,
                  'weapon': {'weapon': 'ChainGun.Yak', 'range_cells': 5., 'damage': 4000}}}}}
        view = View(snapshot(400, units=own, buildings=[actor(90, 'proc', 12, 13)],
                             enemies=[air]), config)
        orders, defenders = Military()._defense(view, own, [air])
        self.assertTrue(defenders)
        self.assertTrue(defenders <= {20, 21})
        self.assertTrue(all(validate_order(i.order, view) is not None for i in orders))

    def test_siege_gun_leaves_out_of_range_fixed_point_and_fires(self):
        tanks = [actor(i, '2tnk', 80, 48 + i) for i in range(1, 5)]
        gun = actor(10, 'arty', 76, 50)
        towers = [actor(100 + i, 'tsla', 90 + i % 2, 48 + i // 2) for i in range(8)]
        military = Military()
        view = View(snapshot(400, units=tanks + [gun], enemy_buildings=towers))
        first = military.propose(view)
        gun_moves = [i.order for i in first if 10 in i.order.get('units', [])
                     and i.order['cmd'] in {'move', 'attack_move'}]
        self.assertEqual(len(gun_moves), 1)
        point = gun_moves[0]['to']
        self.assertNotEqual(point, [gun['x'], gun['y']])
        self.assertTrue(any(damage_rate(view, gun, t, at_distance=distance(point, t)) > 0
                            for t in towers))
        self.assertTrue(all(damage_rate(view, t, gun, at_distance=distance(point, t)) == 0
                            for t in towers))
        military.mark_sent([i.order for i in first], 400)
        gun.update(x=point[0], y=point[1])
        second = military.propose(View(snapshot(404, units=tanks + [gun], enemy_buildings=towers)))
        self.assertTrue(any(i.order['cmd'] == 'attack' and 10 in i.order['units'] for i in second))

    def test_siege_position_rejects_visible_counterfire(self):
        gun = actor(10, 'v2rl', 70, 50)
        tower = actor(100, 'tsla', 90, 50)
        defender = actor(101, 'arty', 85, 50)
        view = View(snapshot(400, units=[gun], enemies=[defender], enemy_buildings=[tower]))
        self.assertIsNone(Military()._siege_position(view, gun, [tower, defender]))

    def test_late_map_layout_rebuilds_sweep_without_losing_contacts(self):
        raw = snapshot(300, units=[actor(1, '1tnk', 12, 12)])
        military = Military()
        military._prepare_sweep(View(raw))
        before = list(military.sweep)
        military.memories[99] = ((50, 50), 290)
        # Only a small ground island is reachable once the actual map arrives.
        rows = ['.' * 20 + '~' * 76 for _ in range(20)] + ['~' * 96 for _ in range(76)]
        config = {'rules': {'maps': {'scenario-map': {'layout': {
                  'origin': [4, 4], 'rows': rows}}}}}
        military._prepare_sweep(View(raw, config))
        self.assertNotEqual(before, military.sweep)
        self.assertTrue(all(4 <= x < 24 and 4 <= y < 24 for x, y in military.sweep))
        self.assertEqual(military.memories[99], ((50, 50), 290))

    def test_missing_or_malformed_layout_uses_bounded_sweep(self):
        raw = snapshot(300, units=[actor(1, '1tnk', 12, 12)])
        for layout in ({'origin': None, 'rows': None}, {'origin': 'bad', 'rows': 'bad'}):
            with self.subTest(layout=layout):
                military = Military()
                view = View(raw, {'rules': {'maps': {'scenario-map': {'layout': layout}}}})
                military._prepare_sweep(view)
                self.assertTrue(military.sweep)
                self.assertTrue(all(view.clamp(point) == list(point) for point in military.sweep))

    def test_main_army_stands_off_known_tower_wall_before_entering_range(self):
        own = [actor(i, '1tnk', 30, 30) for i in range(1, 7)]
        towers = [actor(i, 'tsla', 50, 30) for i in range(100, 106)]
        v = View(snapshot(300, units=own, enemy_buildings=towers))
        orders = Military().propose(v)
        # Unified standoff must cancel focused pursuit, so all six tanks use
        # a plain Move rather than an attack-move that can reacquire the wall.
        advances = [i.order for i in orders if i.order['cmd'] == 'move']
        self.assertTrue(advances)
        self.assertTrue(all(i['to'][0] <= 40 for i in advances))
        self.assertEqual({uid for order in advances for uid in order['units']}, set(range(1, 7)))
        self.assertFalse(any(i.order['cmd'] in {'attack', 'attack_move'} for i in orders))

    def test_small_raid_does_not_recall_entire_main_army(self):
        own = [actor(i, '1tnk', 15 + i % 3, 14) for i in range(1, 16)]
        foe = actor(100, 'e1', 19, 14)
        v = View(snapshot(300, units=own, buildings=[actor(90, 'proc', 12, 12)], enemies=[foe]))
        orders, defending = Military()._defense(v, own, [foe])
        self.assertGreater(len(defending), 0)
        self.assertLess(len(defending), 5)
        self.assertTrue(orders)

    def test_local_fire_assigns_suitable_targets_and_never_chases(self):
        own = [actor(1, 'e1', 20, 20), actor(2, 'e3', 20, 21)]
        enemies = [actor(100, 'e1', 24, 20), actor(101, '3tnk', 24, 21), actor(102, 'e1', 80, 80)]
        v = View(snapshot(300, units=own, enemies=enemies))
        orders, _ = Military()._local_fire(v, own, enemies)
        assignments = {uid: i.order['target'] for i in orders for uid in i.order['units']}
        self.assertEqual(assignments[1], 100)
        self.assertEqual(assignments[2], 101)
        self.assertNotIn(102, assignments.values())
        self.assertTrue(all(validate_order(i.order, v) is not None for i in orders))

    def test_focus_group_over_fifty_is_not_silently_truncated(self):
        own = [actor(i, '1tnk', 30, 30) for i in range(1, 76)]
        enemies = [actor(100, '3tnk', 34, 30)]
        v = View(snapshot(300, units=own, enemies=enemies))
        orders, engaged = Military()._local_fire(v, own, enemies)
        assigned = {uid for i in orders for uid in i.order['units']}
        self.assertEqual(assigned, {a['id'] for a in own})
        self.assertEqual(assigned, engaged)

    def test_slow_trapped_units_trade_instead_of_running_from_faster_enemy(self):
        own = [actor(1, 'e3', 30, 30), actor(2, 'e3', 30, 31)]
        enemies = [actor(100, '1tnk', 33, 30), actor(101, '1tnk', 33, 31)]
        v = View(snapshot(300, units=own, enemies=enemies))
        military = Military()
        military.retreat_until = 310
        military.withdraw_goal = (12, 12)
        orders = military._withdraw(v, own, enemies)
        self.assertTrue(any(i.order['cmd'] == 'attack' for i in orders))
        self.assertFalse(any(i.order['cmd'] == 'move' for i in orders))

    def test_fast_tanks_can_disengage_without_attack_overriding_move(self):
        own = [actor(1, '1tnk', 30, 30)]
        enemies = [actor(100, '3tnk', 33, 30)]
        v = View(snapshot(300, units=own, enemies=enemies))
        orders = Military()._withdraw(v, own, enemies)
        self.assertTrue(any(i.order['cmd'] == 'move' for i in orders))
        self.assertFalse(any(i.order['cmd'] == 'attack' for i in orders))

    def test_remembered_contact_cannot_generate_hidden_id_attack(self):
        own = [actor(i, '1tnk', 30, 30) for i in range(1, 7)]
        tower = actor(100, 'tsla', 50, 30)
        military = Military()
        military.propose(View(snapshot(300, units=own, enemy_buildings=[tower])))
        view = View(snapshot(310, units=own))
        orders = military.propose(view)
        self.assertIn(100, military.contacts)
        self.assertFalse(any(i.order.get('target') == 100 for i in orders))
        self.assertTrue(all(validate_order(i.order, view) is not None for i in orders))

    def test_mobile_memory_expires_without_a_new_sighting(self):
        own = [actor(1, '1tnk', 30, 30)]
        enemy = actor(100, '3tnk', 50, 30)
        military = Military()
        military._remember(View(snapshot(300, units=own, enemies=[enemy])), own)
        military._remember(View(snapshot(326, units=own)), own)
        self.assertNotIn(100, military.contacts)

    def test_pending_focus_fire_survives_idle_observation_during_engine_apply(self):
        own = [actor(i, '1tnk', 30, 30) for i in range(1, 7)]
        enemies = [actor(100, 'e1', 34, 30)]
        military = Military()
        first = military.propose(View(snapshot(300, units=own, enemies=enemies)))
        military.mark_sent([i.order for i in first], 300)
        # Fresh tick, but the server has not yet applied the pending attack.
        later = military.propose(View(snapshot(300.25, units=own, enemies=enemies)))
        self.assertFalse(any(i.order['cmd'] in {'move', 'attack_move', 'attack'} for i in later))

    def test_busy_focus_fire_is_not_cancelled_by_macro_order(self):
        own = [actor(i, '1tnk', 30, 30) for i in range(1, 7)]
        enemies = [actor(100, 'e1', 34, 30)]
        military = Military()
        first = military.propose(View(snapshot(300, units=own, enemies=enemies)))
        military.mark_sent([i.order for i in first], 300)
        for a in own:
            a.update(idle=False, act='Attack')
        later = military.propose(View(snapshot(303, units=own, enemies=enemies)))
        self.assertFalse(any(i.order['cmd'] in {'move', 'attack_move', 'attack'} for i in later))

    def test_unsupported_artillery_withdraws_when_a_tank_closes(self):
        own = [actor(1, 'arty', 30, 30)]
        foe = actor(100, '1tnk', 35, 30)
        v = View(snapshot(300, units=own, enemies=[foe]))
        orders, _ = Military()._support(v, own, (60, 30), [foe])
        self.assertTrue(any(i.order['cmd'] == 'move' for i in orders))
        self.assertFalse(any(i.order['cmd'] == 'attack' for i in orders))

    def test_artillery_keeps_firing_from_range_instead_of_walking_into_target(self):
        own = [actor(1, 'arty', 30, 30), actor(2, '2tnk', 35, 30)]
        foe = actor(100, 'pbox', 40, 30)
        v = View(snapshot(300, units=own, enemy_buildings=[foe]))
        orders, ids = Military()._support(v, own, (40, 30), [foe])
        self.assertEqual(ids, {1})
        self.assertTrue(any(i.order['cmd'] == 'attack' and i.order['target'] == 100 for i in orders))
        self.assertFalse(any(i.order['cmd'] == 'move' for i in orders))


if __name__ == '__main__':
    unittest.main()
