from copy import deepcopy
from pathlib import Path
import struct
import sys

import pytest

from adapter import ROOT, SeatAdapter, StaticData, mini, pb


@pytest.fixture(scope='module')
def static():
    return StaticData(ROOT / 'OpenRA', 'sidestep')


def observation():
    obs = pb.GameObservation(tick=1, episode_id='test', map_info=pb.RlMapInfo(width=98,height=98,map_name='Sidestep'),
        economy=pb.RlEconomy(cash=5000,power_provided=100), available_production=['powr','tent','proc','e1'])
    obs.units.add(actor_id=10,type='mcv',cell_x=23,cell_y=44,hp_percent=1,is_idle=True,current_activity='Idle',stance=3)
    return obs


def test_static_engine_matches_public_guide(static):
    assert static.catalog['powr']['cost'] == 300
    assert static.catalog['powr']['build_time_s'] == 7.2
    assert static.catalog['proc']['cost'] == 1400
    assert static.catalog['proc']['build_time_s'] == 33.6
    assert static.catalog['weap']['cost'] == 2000
    assert static.catalog['harv']['cost'] == 1100
    assert static.catalog['harv']['build_time_s'] == 26.4
    assert static.catalog['2tnk']['queue'] == 'Vehicle'
    assert static.catalog['gun']['queue'] == 'Defense'
    assert 'reload_seconds' not in static.catalog['tsla']['weapon']
    assert static.map['bounds'] == [1,1,96,96]
    assert static.map['spawns'] == [[23,44],[74,53]]
    assert static.map_diagnostics['unknown_terrain_cells'] == 0


@pytest.mark.parametrize('name,bounds', [('trapped',[1,1,97,97]),('shadowfiend-ii',[1,1,83,90]),('v25_development_1.oramap',[1,1,96,96])])
def test_public_maps(name,bounds):
    static = StaticData(ROOT / 'OpenRA',name)
    assert static.map['bounds'] == bounds
    assert static.map_diagnostics['unknown_terrain_cells'] == 0
    assert len(static.map['spawns']) == 2
    assert len(static.map['layout']['rows']) == bounds[3]
    assert all(len(row) == bounds[2] for row in static.map['layout']['rows'])


def test_observation_drops_spatial_and_enemy_extra_fields(static):
    obs = observation()
    obs.visible_enemies.add(actor_id=20,type='3tnk',cell_x=30,cell_y=40,hp_percent=.501,can_attack=True,speed=900)
    obs.visible_enemy_buildings.add(actor_id=21,type='tsla',cell_x=31,cell_y=40,hp_percent=.9,is_powered=False,is_producing=True,producing_item='powr')
    first = SeatAdapter(static).observation(obs)
    obs.spatial_map = bytes([255]) * 98*98*9*4
    obs.spatial_channels = 9
    second = SeatAdapter(static).observation(obs)
    assert first == second
    assert set(first['observation']['visible_enemies'][0]) == {'id','type','x','y','hp'}
    assert set(first['observation']['visible_enemy_buildings'][0]) == {'id','type','x','y','hp'}
    assert first['observation']['visible_enemies'][0]['hp'] == 50
    assert 'spatial_map' not in first
    assert first['observation']['units'][0]['act'] == 'Idle'
    assert first['observation']['units'][0]['stance'] == 'attack_anything'


def test_build_ready_and_queues(static):
    obs = observation()
    obs.production.add(queue_type='Building',item='proc',progress=1,remaining_ticks=0)
    obs.production.add(queue_type='Vehicle',item='harv',progress=.5,remaining_ticks=100)
    raw = SeatAdapter(static).observation(obs)
    assert raw['legal_actions']['place'] == ['proc']
    assert raw['legal_actions']['build'] == ['powr','proc','tent']
    assert raw['legal_actions']['train'] == ['e1']
    assert raw['observation']['production'][1]['remaining_s'] == 4


def test_event_reconstruction_obeys_own_view(static):
    adapter = SeatAdapter(static)
    obs = observation()
    adapter.observation(obs)
    obs.tick = 100
    obs.units[0].hp_percent=.9
    obs.units.add(actor_id=11,type='e1',hp_percent=1,cell_x=24,cell_y=44)
    raw = adapter.observation(obs)
    assert [e['kind'] for e in raw['observation']['events']] == ['under_attack','unit_created']
    obs.tick = 101
    obs.units[0].hp_percent=.8
    assert len(adapter.observation(obs)['observation']['events']) == 2
    obs.tick = 350
    obs.units[0].hp_percent=.7
    assert len(adapter.observation(obs)['observation']['events']) == 3


def test_command_expansion_and_guard_visibility(static):
    adapter = SeatAdapter(static)
    obs = observation()
    obs.units.add(actor_id=11,type='harv',hp_percent=1)
    obs.buildings.add(actor_id=12,type='fact',hp_percent=1,is_powered=True)
    obs.visible_enemies.add(actor_id=20,type='e1',hp_percent=1)
    raw = adapter.observation(obs)
    orders = [{'cmd':'harvest','units':[11],'to':[33,38]}, {'cmd':'train','item':'e1','count':3},
              {'cmd':'attack','units':[10],'target':20}, {'cmd':'place','item':'powr','at':[25,45]},
              {'cmd':'guard','units':[10],'target':11}, {'cmd':'set_stance','units':[10],'stance':'defend'}]
    commands = adapter.commands(orders,raw)
    assert len(commands) == 8
    assert (commands[0].action,commands[0].target_x,commands[0].target_y) == (pb.HARVEST,33,38)
    assert [x.action for x in commands[1:4]] == [pb.TRAIN]*3
    assert commands[4].target_actor_id == 20
    assert commands[5].action == pb.PLACE_BUILDING
    assert commands[-1].target_x == 2
    with pytest.raises(ValueError,match='target_not_visible'):
        adapter.commands([{'cmd':'attack','units':[10],'target':999}],raw)
    with pytest.raises(ValueError,match='not_owned'):
        adapter.commands([{'cmd':'move','units':[20],'to':[1,1]}],raw)


def test_repair_is_idempotent(static):
    adapter = SeatAdapter(static)
    obs = observation()
    obs.buildings.add(actor_id=12,type='fact',hp_percent=.7,is_repairing=True)
    raw = adapter.observation(obs)
    assert adapter.commands([{'cmd':'repair','building':12,'on':True}],raw) == []
    assert adapter.commands([{'cmd':'repair','building':12,'on':False}],raw)[0].action == pb.REPAIR


def test_no_automatic_attack_data_exposure(static):
    raw = SeatAdapter(static).observation(observation())
    assert raw['observation']['visible_enemies'] == []
    assert raw['observation']['visible_enemy_buildings'] == []
    assert raw['legal_actions']['attack'] == []
    assert raw['legal_actions']['enemy_base'] == [74,53]


def test_controller_smoke(static):
    sys.path.insert(0,str(ROOT/'policies/v24'))
    from altru_redalert.core import Controller
    adapter = SeatAdapter(static)
    controller = Controller()
    obs = observation()
    raw = adapter.observation(obs)
    orders = controller.decide(raw,static.config)
    commands = adapter.commands(orders,raw)
    assert commands[0].action == pb.DEPLOY
    controller.on_result(adapter.feedback(orders))
    obs.tick = 26
    del obs.units[:]
    obs.buildings.add(actor_id=12,type='fact',hp_percent=1,cell_x=23,cell_y=44,is_powered=True)
    raw = adapter.observation(obs)
    result = controller.decide(raw,static.config)
    assert any(o['cmd']=='build' and o['item']=='powr' for o in result['orders'])
