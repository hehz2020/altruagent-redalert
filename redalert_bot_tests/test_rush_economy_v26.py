"""Opening economy must fund visible defense without inventing refunds."""
import unittest

from altru_redalert.core import validate_order
from altru_redalert.economy import Economy, _reserved
from redalert_bot_tests.test_economy_v2 import actor, view


def opening(now=160, cash=2200, *, enemies=(), production=(), pending=(), harvs=2,
            rifles=4, escort=False, factory=True):
    buildings = [actor(1, 'fact', 10, 10), actor(2, 'powr', 10, 14),
                 actor(3, 'tent', 10, 6), actor(4, 'proc', 14, 10),
                 actor(6, 'proc', 17, 10)]
    if factory:
        buildings.append(actor(5, 'weap', 12, 16))
    units = [actor(20 + i, 'harv', 20, 14 + i) for i in range(harvs)]
    units += [actor(30 + i, 'e1', 12, 11 + i) for i in range(rifles)]
    if escort:
        units.append(actor(50, 'jeep', 18, 12))
    v = view(now, cash=cash, units=units, buildings=buildings,
             train=['e1', 'e3', 'harv', 'jeep'] if factory else ['e1', 'e3'],
             build=['powr', 'proc', 'weap', 'fix', 'pbox'], enemies=enemies,
             production=production, pending=pending)
    v.catalog['pbox'] = {'cost': 400, 'power': 0, 'queue': 'Defense', 'build_time_s': 12}
    v.catalog['jeep']['build_time_s'] = 12
    return v


def rush(x=40):
    # 23 cells from the outer refinery: outside the old 18-cell danger radius.
    return [actor(90 + i, 'e1' if i < 3 else 'e3', x, 10 + i) for i in range(4)]


def orders(policy, v):
    result = [intent.order for intent in policy.propose(v)]
    assert all(validate_order(order, v) == order for order in result)
    return result


class RushEconomyTests(unittest.TestCase):
    def test_first_screen_is_not_starved_by_factory_and_refinery_savings(self):
        v = opening(70, cash=2200, harvs=1, rifles=0, factory=False,
                    production=[{'item': 'proc', 'queue': 'Building', 'progress': .2}])
        result = orders(Economy(), v)
        self.assertIn({'cmd': 'train', 'item': 'e1', 'count': 4}, result)
        spent = sum(v.cost(o['item']) * o.get('count', 1) for o in result
                    if o['cmd'] in {'train', 'build'})
        self.assertLessEqual(spent, v.funds - _reserved(v))

    def test_four_rifle_screen_does_not_repeat_or_block_factory(self):
        v = opening(100, cash=2500, factory=False)
        result = orders(Economy(), v)
        self.assertIn({'cmd': 'build', 'item': 'weap'}, result)
        self.assertFalse(any(o['cmd'] == 'train' and o['item'] == 'e1' for o in result))

    def test_first_factory_gets_legal_escort_before_optional_depot_or_harvester(self):
        result = orders(Economy(), opening(cash=2800))
        self.assertIn({'cmd': 'train', 'item': 'jeep'}, result)
        self.assertFalse(any(o.get('item') in {'fix', 'harv'} for o in result))

    def test_factory_visibility_before_vehicle_queue_does_not_skip_escort(self):
        policy = Economy()
        placed = opening(155.76, cash=1900)
        placed.legal['train'] = ['e1', 'e3']
        first = orders(policy, placed)
        self.assertNotIn({'cmd': 'build', 'item': 'fix'}, first)
        # The next view enables the new Vehicle queue; retain any Infantry
        # commitment from the placement view rather than spending it twice.
        pending = [o for o in first if o['cmd'] == 'train']
        enabled = opening(156, cash=1900, pending=pending)
        second = orders(policy, enabled)
        self.assertIn({'cmd': 'train', 'item': 'jeep'}, second)
        self.assertFalse(any(o.get('item') in {'fix', 'harv'} for o in second))
        spent = sum(enabled.cost(o['item']) * o.get('count', 1) for o in second
                    if o['cmd'] in {'train', 'build'})
        self.assertLessEqual(spent, enabled.funds - _reserved(enabled))

    def test_unsupported_vehicle_queue_cannot_delay_depot_forever(self):
        policy = Economy()
        for now in (155, 157.99, 158):
            v = opening(now, cash=2200)
            v.legal['train'] = []
            result = orders(policy, v)
            if now < 158:
                self.assertNotIn({'cmd': 'build', 'item': 'fix'}, result)
            else:
                self.assertIn({'cmd': 'build', 'item': 'fix'}, result)

    def test_committed_third_miner_bypasses_factory_readiness_grace(self):
        v = opening(155, cash=2300, pending=[{'cmd': 'train', 'item': 'harv'}])
        v.legal['train'] = ['e1', 'e3']
        result = orders(Economy(), v)
        self.assertIn({'cmd': 'build', 'item': 'fix'}, result)
        spent = sum(v.cost(o['item']) * o.get('count', 1) for o in result
                    if o['cmd'] in {'train', 'build'})
        self.assertEqual(spent, v.funds - _reserved(v))

    def test_lost_and_rebuilt_factory_gets_a_new_bounded_readiness_window(self):
        policy = Economy()
        for now, factory, wait in ((155, True, True), (160, False, False),
                                   (165, True, True), (168, True, False)):
            v = opening(now, cash=2200, factory=factory)
            v.legal['train'] = []
            if not factory:
                v.legal['build'] = []
            result = orders(policy, v)
            if factory:
                self.assertEqual({'cmd': 'build', 'item': 'fix'} not in result, wait)

    def test_committed_third_miner_does_not_block_parallel_depot(self):
        for progress, cash in ((0, 2300), (.5, 1750)):
            with self.subTest(progress=progress):
                v = opening(140, cash=cash,
                            production=[{'item': 'harv', 'queue': 'Vehicle',
                                         'progress': progress}])
                result = orders(Economy(), v)
                self.assertIn({'cmd': 'build', 'item': 'fix'}, result)
                self.assertFalse(any(o['cmd'] == 'train' and o['item'] == 'jeep' for o in result))
                spent = sum(v.cost(o['item']) * o.get('count', 1) for o in result
                            if o['cmd'] in {'train', 'build'})
                self.assertLessEqual(spent, v.funds - _reserved(v))

    def test_screen_leaves_cash_for_needed_power_before_factory(self):
        v = opening(90, cash=300, harvs=1, rifles=0, factory=False)
        v.power_surplus = 20
        result = orders(Economy(), v)
        self.assertIn({'cmd': 'build', 'item': 'powr'}, result)
        self.assertFalse(any(o['cmd'] == 'train' for o in result))

    def test_urgent_tower_precedes_extra_screen_rifles_at_real_cost(self):
        v = opening(100, cash=800, rifles=0, factory=False, enemies=rush())
        v.catalog['pbox'].update(cost=600, power=-20, build_time_s=14.4)
        result = orders(Economy(), v)
        self.assertIn({'cmd': 'build', 'item': 'pbox'}, result)
        self.assertIn({'cmd': 'train', 'item': 'e1', 'count': 2}, result)
        spent = sum(v.cost(o['item']) * o.get('count', 1) for o in result
                    if o['cmd'] in {'train', 'build'})
        self.assertEqual(spent, 800)

    def test_missing_escort_option_does_not_block_legal_combat_vehicle(self):
        v = opening(200, cash=2000, rifles=10, enemies=rush())
        v.legal['train'] = ['e1', '1tnk']
        result = orders(Economy(), v)
        self.assertTrue(any(o['cmd'] == 'train' and o['item'] == '1tnk' for o in result))

    def test_visible_infantry_approach_funds_defense_before_damage(self):
        v = opening(enemies=rush())
        result = orders(Economy(), v)
        self.assertIn({'cmd': 'build', 'item': 'pbox'}, result)
        self.assertIn({'cmd': 'train', 'item': 'jeep'}, result)
        self.assertFalse(any(o.get('item') in {'fix', 'harv', 'proc'} for o in result))
        spent = sum(v.cost(o['item']) * o.get('count', 1) for o in result
                    if o['cmd'] in {'train', 'build'})
        self.assertLessEqual(spent, v.funds)

    def test_urgent_pillbox_does_not_wait_for_unrelated_tank_reserve(self):
        v = opening(cash=650, enemies=rush())
        result = orders(Economy(), v)
        self.assertIn({'cmd': 'build', 'item': 'pbox'}, result)
        spent = sum(v.cost(o['item']) * o.get('count', 1) for o in result
                    if o['cmd'] in {'train', 'build'})
        self.assertLessEqual(spent, 650)

    def test_optional_depot_cancellation_never_spends_an_assumed_refund(self):
        v = opening(cash=100, enemies=rush(),
                    production=[{'item': 'fix', 'queue': 'Building', 'progress': .5}])
        result = orders(Economy(), v)
        self.assertIn({'cmd': 'cancel', 'item': 'fix'}, result)
        self.assertFalse(any(o['cmd'] in {'build', 'train'} for o in result))

    def test_wait_for_cancel_reconciliation_before_more_spending(self):
        v = opening(cash=2200, enemies=rush(), pending=[{'cmd': 'cancel', 'item': 'fix'}],
                    production=[{'item': 'fix', 'queue': 'Building', 'progress': .5}])
        result = orders(Economy(), v)
        self.assertFalse(any(o['cmd'] in {'cancel', 'build', 'train'} for o in result))

    def test_cancelling_optional_depot_keeps_emergency_repairs_enabled(self):
        for pending in ([], [{'cmd': 'cancel', 'item': 'fix'}]):
            with self.subTest(pending=pending):
                v = opening(cash=5000, enemies=rush(), pending=pending,
                            production=[{'item': 'fix', 'queue': 'Building', 'progress': .4}])
                refinery = next(b for b in v.buildings if b['type'] == 'proc')
                refinery['hp'] = 25
                result = orders(Economy(), v)
                self.assertIn({'cmd': 'repair', 'building': refinery['id'], 'on': True}, result)
                self.assertFalse(any(o['cmd'] in {'build', 'train'} for o in result))

    def test_extra_harvester_cancel_preserves_two_working_harvesters(self):
        p = [{'item': 'harv', 'queue': 'Vehicle', 'progress': .2}]
        result = orders(Economy(), opening(enemies=rush(), production=p))
        self.assertIn({'cmd': 'cancel', 'item': 'harv'}, result)
        result = orders(Economy(), opening(enemies=rush(), production=p, harvs=1))
        self.assertNotIn({'cmd': 'cancel', 'item': 'harv'}, result)

    def test_essential_income_power_and_ready_or_nearly_complete_depot_are_kept(self):
        for item, queue, progress, ready, harvs in (
                ('harv', 'Vehicle', .1, False, 0),
                ('powr', 'Building', .1, False, 2),
                ('proc', 'Building', .1, False, 2),
                ('fix', 'Building', .9, False, 2),
                ('fix', 'Building', 1, True, 2)):
            with self.subTest(item=item, progress=progress, harvs=harvs):
                v = opening(enemies=rush(), harvs=harvs,
                            production=[{'item': item, 'queue': queue,
                                         'progress': progress, 'ready': ready}])
                self.assertNotIn({'cmd': 'cancel', 'item': item}, orders(Economy(), v))

    def test_single_enemy_or_remote_army_cannot_cancel_development(self):
        for enemies in ([actor(90, 'e1', 22, 10)], rush(70)):
            v = opening(enemies=enemies,
                        production=[{'item': 'fix', 'queue': 'Building', 'progress': .2}])
            self.assertFalse(any(o['cmd'] == 'cancel' for o in orders(Economy(), v)))

    def test_alert_expires_and_peaceful_depot_progress_resumes(self):
        policy = Economy()
        orders(policy, opening(160, enemies=rush()))
        held = orders(policy, opening(175, harvs=3, escort=True))
        self.assertNotIn({'cmd': 'build', 'item': 'fix'}, held)
        resumed = orders(policy, opening(186, harvs=3, escort=True))
        self.assertIn({'cmd': 'build', 'item': 'fix'}, resumed)


if __name__ == '__main__':
    unittest.main()
