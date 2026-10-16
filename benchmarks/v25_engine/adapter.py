from __future__ import annotations

import argparse
from collections import Counter, deque
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import struct
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'generated'))
import rl_bridge_pb2 as pb


def mini(text):
    result = {}
    stack = [(-1, result)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith('#'):
            continue
        depth = len(raw) - len(raw.lstrip('\t'))
        line = raw.strip()
        key, sep, value = line.partition(':')
        if not sep:
            value = ''
        while stack[-1][0] >= depth:
            stack.pop()
        parent = stack[-1][1]
        node = parent.setdefault(key, {})
        if value.strip():
            node['_'] = value.strip()
        stack.append((depth, node))
    return result


def merge(a, b):
    out = deepcopy(a)
    for key, value in b.items():
        if key.startswith('-'):
            out.pop(key[1:], None)
        elif isinstance(value, dict):
            out[key] = merge(out.get(key, {}), value)
        else:
            out[key] = value
    return out


def value(node, key, default=''):
    return node.get(key, {}).get('_', default)


def ints(text):
    return [int(x.strip()) for x in text.split(',')]


def traits(node, prefix):
    return [v for k, v in node.items() if k.split('@')[0] == prefix]


def trait(node, prefix):
    return next(iter(traits(node, prefix)), {})


def cell_range(text):
    if not text:
        return 0.
    if 'c' in text:
        a, b = text.split('c', 1)
        return int(a or 0) + int(b or 0) / 1024
    return float(text) / 1024


class StaticData:
    def __init__(self, engine_root, map_name):
        self.root = Path(engine_root)
        self.map_name = Path(map_name).stem.lower()
        manifest = mini((self.root / 'mods/ra/mod.yaml').read_text())
        self.actor_nodes = self._load(manifest['Rules'])
        self.weapon_nodes = self._load(manifest['Weapons'])
        self.actor_cache = {}
        self.weapon_cache = {}
        units, buildings = {}, {}
        for name in self.actor_nodes:
            if name.startswith('^'):
                continue
            actor = self.actor(name)
            health = trait(actor, 'Health')
            build = trait(actor, 'Buildable')
            if not health or not trait(actor, 'Valued'):
                continue
            cost = int(value(trait(actor, 'Valued'), 'Cost', 0))
            queue = value(build, 'Queue').split(',')[0].strip()
            duration = int(value(build, 'BuildDuration', -1))
            duration = cost if duration == -1 else duration
            spec = {'cost': cost, 'hp': int(value(health, 'HP', 1)),
                    'armor': value(trait(actor, 'Armor'), 'Type', 'None'),
                    'power': int(value(trait(actor, 'Power'), 'Amount', 0)),
                    'speed': int(value(trait(actor, 'Mobile'), 'Speed', 0)) * 25 / 1024,
                    'build_time_s': duration * int(value(build, 'BuildDurationModifier', 60)) / 2500,
                    'queue': queue,
                    'prerequisites': [p.strip() for p in value(build, 'Prerequisites').split(',') if p.strip()]}
            weapons = traits(actor, 'Armament')
            if weapons:
                weapon_name = value(weapons[0], 'Weapon')
                weapon = self.weapon(weapon_name)
                damages = [float(value(w, 'Damage', 0)) for w in traits(weapon, 'Warhead')]
                spec['weapon'] = {'weapon': weapon_name, 'damage': max(damages, default=0),
                                  'range_cells': cell_range(value(weapon, 'Range'))}
            (buildings if traits(actor, 'Building') else units)[name.lower()] = spec
        self.map = self._map()
        self.config = {'rules': {'units': units, 'buildings': buildings,
                                 'maps': {self.map_name: self.map}}}
        self.catalog = {**units, **buildings}

    def _load(self, section):
        result = {}
        for path in section:
            if '|' not in path:
                continue
            mod, relative = path.split('|', 1)
            nodes = mini((self.root / 'mods' / mod / relative).read_text())
            for name, node in nodes.items():
                result[name.lower()] = merge(result.get(name.lower(), {}), node)
        return result

    def _resolve(self, name, nodes, cache, ancestors=()):
        name = name.lower()
        if name in cache:
            return cache[name]
        if name in ancestors:
            raise ValueError('inheritance cycle ' + name)
        node = nodes.get(name, {})
        result = {}
        for key, val in node.items():
            if key.split('@')[0] == 'Inherits':
                result = merge(result, self._resolve(val['_'], nodes, cache, ancestors + (name,)))
        result = merge(result, {k: v for k, v in node.items() if k.split('@')[0] != 'Inherits'})
        cache[name] = result
        return result

    def actor(self, name):
        return self._resolve(name, self.actor_nodes, self.actor_cache)

    def weapon(self, name):
        return self._resolve(name, self.weapon_nodes, self.weapon_cache)

    def _map(self):
        files = {p.stem.lower(): p for p in (self.root / 'mods/ra/maps').glob('*.oramap')}
        path = files[self.map_name]
        with zipfile.ZipFile(path) as z:
            meta = mini(z.read('map.yaml').decode())
            data = z.read('map.bin')
        width, height = ints(value(meta, 'MapSize'))
        bounds = ints(value(meta, 'Bounds'))
        fmt, bw, bh = struct.unpack_from('<BHH', data)
        if (bw, bh) != (width, height):
            raise ValueError('map dimensions differ')
        if fmt == 1:
            tile_offset, resource_offset = 5, 5 + 3 * width * height
        elif fmt == 2:
            tile_offset, _, resource_offset = struct.unpack_from('<III', data, 5)
        else:
            raise ValueError('unsupported map format')
        ts = mini((self.root / 'mods/ra/tilesets' / (value(meta, 'Tileset').lower() + '.yaml')).read_text())
        templates = {int(value(t, 'Id')): t for t in ts['Templates'].values()}
        chars = {'Water': '~', 'River': '~', 'Rock': '^', 'Tree': 'T', 'Wall': '#', 'Ore': '$', 'Gems': '*'}
        rows = [['.' for _ in range(width)] for _ in range(height)]
        unknown = 0
        for x in range(width):
            for y in range(height):
                idx = x * height + y
                tile, sub = struct.unpack_from('<HB', data, tile_offset + 3 * idx)
                if sub == 255:
                    sub = x % 4 + y % 4 * 4
                template = templates.get(tile, {})
                terrain = value(template.get('Tiles', {}), str(sub))
                if not terrain and template:
                    terrain = value(template.get('Tiles', {}), '0')
                if not terrain:
                    unknown += 1
                rows[y][x] = chars.get(terrain, '.')
                if resource_offset:
                    kind, density = struct.unpack_from('<BB', data, resource_offset + 2 * idx)
                    if density:
                        rows[y][x] = '$' if kind == 1 else '*' if kind == 2 else rows[y][x]
        spawns = []
        for actor in meta.get('Actors', {}).values():
            kind = actor.get('_', '').lower()
            if not value(actor, 'Location'):
                continue
            x, y = ints(value(actor, 'Location'))
            if kind == 'mpspawn':
                spawns.append([x, y])
                rows[y][x] = 'S'
            elif kind in {'mine', 'gmine'}:
                rows[y][x] = 'M'
            else:
                info = self.actor(kind)
                building = trait(info, 'Building')
                footprint = value(building, 'Footprint', 'x').split()
                symbol = 'T' if kind.startswith(('tc', 't0', 't1')) else '#'
                if building:
                    for dy, row in enumerate(footprint):
                        for dx, char in enumerate(row):
                            if char not in ('_', '=') and 0 <= y + dy < height and 0 <= x + dx < width:
                                rows[y + dy][x + dx] = symbol
        x, y, w, h = bounds
        self.map_diagnostics = {'unknown_terrain_cells': unknown, 'source_sha256': hashlib.sha256(data).hexdigest()}
        return {'id': self.map_name, 'width': width, 'height': height, 'bounds': bounds,
                'spawns': spawns, 'layout': {'origin': [x, y],
                    'rows': [''.join(row[x:x+w]) for row in rows[y:y+h]]}}


class SeatAdapter:
    def __init__(self, static, faction='england', enemy_faction='russia', seconds_limit=1200):
        self.static = static
        self.faction = faction
        self.enemy_faction = enemy_faction
        self.seconds_limit = seconds_limit
        self.powered_down = set()
        self.previous = None
        self.events = deque(maxlen=20)
        self.seq = 0
        self.attacked = {}
        self.enemy_seen = set()

    def _actor(self, actor, building=False, own=False):
        kind = actor.type.lower()
        result = {'id': actor.actor_id, 'type': kind, 'x': actor.cell_x, 'y': actor.cell_y,
                  'hp': int(actor.hp_percent * 100 + .5)}
        if 'husk' in kind or 'wreck' in kind:
            result['wreck'] = True
        if own and building:
            result.update(powered=actor.is_powered, powered_down=actor.actor_id in self.powered_down,
                          repairing=actor.is_repairing, producing=actor.producing_item or None,
                          rally=[actor.rally_x, actor.rally_y] if actor.rally_x >= 0 and actor.rally_y >= 0 else None)
        elif own:
            result.update(act=actor.current_activity or None, idle=actor.is_idle,
                          stance=('hold_fire', 'return_fire', 'defend', 'attack_anything')[min(3, max(0, actor.stance))])
        return result

    def _event(self, tick, kind, actor=None, **extra):
        self.seq += 1
        row = {'seq': self.seq, 'tick': tick, 'kind': kind, **extra}
        if actor:
            row.update({k: actor[k] for k in ('id', 'type', 'x', 'y')})
        self.events.append(row)

    def observation(self, obs):
        units = [self._actor(a, own=True) for a in obs.units]
        buildings = [self._actor(a, building=True, own=True) for a in obs.buildings]
        enemies = [self._actor(a) for a in obs.visible_enemies]
        enemy_buildings = [self._actor(a, building=True) for a in obs.visible_enemy_buildings]
        production = [{'queue': p.queue_type, 'item': p.item.lower(), 'progress': p.progress,
                       'remaining_s': p.remaining_ticks / 25, 'paused': p.paused,
                       'ready': p.remaining_ticks <= 0 and p.progress >= .999} for p in obs.production]
        economy = {k: getattr(obs.economy, k) for k in ('cash', 'ore', 'power_provided', 'power_drained', 'resource_capacity')}
        economy['harvesters'] = obs.economy.harvester_count
        military = {k: getattr(obs.military, k) for k in ('kills_cost', 'deaths_cost', 'assets_value', 'army_value', 'units_killed', 'units_lost', 'buildings_killed', 'buildings_lost')}
        candidates = [a for a in buildings if a['type'] == 'fact']
        if candidates:
            base = [candidates[0]['x'], candidates[0]['y']]
        else:
            candidates = buildings or [a for a in units if not a.get('wreck')]
            base = [round(sum(a[k] for a in candidates) / len(candidates)) for k in ('x', 'y')] if candidates else None
        own = {a['id']: a for a in units + buildings if not a.get('wreck')}
        ready = {p['item'] for p in production if p['ready'] and p['queue'] in ('Building', 'Defense')}
        low = economy['power_drained'] > economy['power_provided']
        if self.previous:
            previous_actors = self.previous['actors']
            building_ids = {a['id'] for a in buildings}
            for ident, actor in own.items():
                old = previous_actors.get(ident)
                if old is None:
                    self._event(obs.tick, 'building_created' if ident in building_ids else 'unit_created', actor)
                elif actor['hp'] < old['hp'] and obs.tick - self.attacked.get(ident, -10000) >= 250:
                    self._event(obs.tick, 'under_attack', actor)
                    self.attacked[ident] = obs.tick
            for ident in previous_actors.keys() - own.keys():
                self._event(obs.tick, 'building_lost' if ident in self.previous['building_ids'] else 'unit_lost', previous_actors[ident])
            for name in ready - self.previous['ready']:
                self._event(obs.tick, 'production_ready', type=name)
            if low != self.previous['low']:
                self._event(obs.tick, 'low_power' if low else 'power_restored')
        for actor in enemies + enemy_buildings:
            if actor['id'] not in self.enemy_seen:
                self._event(obs.tick, 'enemy_spotted', actor)
                self.enemy_seen.add(actor['id'])
        self.previous = {'actors': own, 'building_ids': {a['id'] for a in buildings}, 'ready': ready, 'low': low}
        self.powered_down.intersection_update(own)
        available = sorted(set(x.lower() for x in obs.available_production))
        legal = {'build': [x for x in available if self.static.catalog.get(x, {}).get('queue') in ('Building', 'Defense')],
                 'train': [x for x in available if self.static.catalog.get(x, {}).get('queue') not in ('Building', 'Defense')],
                 'place': sorted(ready), 'deploy': [a['id'] for a in units if a['type'] == 'mcv'],
                 'repair': [a['id'] for a in buildings if a['hp'] < 100 and not a['repairing']],
                 'harvesters': [a['id'] for a in units if a['type'] == 'harv'],
                 'idle_units': [a['id'] for a in units if a['idle'] and not a.get('wreck')],
                 'attack': [a['id'] for a in enemies + enemy_buildings if not a.get('wreck')],
                 'production_buildings': [{'id': a['id'], 'type': a['type']} for a in buildings if a['type'] in ('fact','tent','barr','weap','hpad','afld','spen','syrd')]}
        if base and self.static.map['spawns']:
            legal['enemy_base'] = max(self.static.map['spawns'], key=lambda p: (p[0]-base[0])**2+(p[1]-base[1])**2)
        view = {'tick': obs.tick, 'faction': self.faction, 'enemy_faction': self.enemy_faction,
                'base_center': base, 'economy': economy, 'military': military, 'units': units,
                'buildings': buildings, 'production': production, 'visible_enemies': enemies,
                'visible_enemy_buildings': enemy_buildings, 'available_production': available,
                'explored_percent': obs.explored_percent, 'events': list(self.events),
                'map': {k: self.static.map[k] for k in ('id','width','height','bounds')}}
        return {'game_type': 'red_alert', 'session_id': obs.episode_id or 'local', 'state_version': obs.tick,
                'phase': 'finished' if obs.done else 'playing', 'is_current_actor': not obs.done,
                'is_terminal': obs.done, 'observation': view, 'legal_actions': legal,
                'map': view['map'], 'time': {'game_seconds': obs.tick / 25,
                'remaining_seconds': max(0, self.seconds_limit - obs.tick / 25)},
                'limits': {'max_orders_per_batch': 20, 'max_units_per_order': 50,
                'max_train_count': 10, 'max_engine_commands_per_batch': 200}}

    def commands(self, orders, raw):
        if isinstance(orders, dict):
            orders = orders.get('orders', [])
        commands = []
        enums = {'move':pb.MOVE, 'attack_move':pb.ATTACK_MOVE, 'attack':pb.ATTACK,
                 'stop':pb.STOP, 'deploy':pb.DEPLOY, 'harvest':pb.HARVEST, 'guard':pb.GUARD,
                 'set_stance':pb.SET_STANCE, 'build':pb.BUILD, 'train':pb.TRAIN,
                 'place':pb.PLACE_BUILDING, 'cancel':pb.CANCEL_PRODUCTION,
                 'repair':pb.REPAIR, 'power_toggle':pb.POWER_DOWN, 'rally':pb.SET_RALLY_POINT,
                 'set_primary':pb.SET_PRIMARY, 'sell':pb.SELL}
        own_buildings = {a['id']: a for a in raw['observation']['buildings']}
        own_units = {a['id']: a for a in raw['observation']['units'] if not a.get('wreck')}
        visible_targets = {a['id'] for a in raw['observation']['visible_enemies'] + raw['observation']['visible_enemy_buildings'] if not a.get('wreck')}
        for order in orders or []:
            kind = order['cmd']
            ident = order.get('building', 0)
            if 'building' in order and ident not in own_buildings:
                raise ValueError('not_owned')
            if 'units' in order and any(i not in own_units and i not in own_buildings for i in order['units']):
                raise ValueError('not_owned')
            if kind == 'attack' and 'target' in order and order['target'] not in visible_targets:
                raise ValueError('target_not_visible')
            if kind == 'guard' and order['target'] not in own_units and order['target'] not in own_buildings:
                raise ValueError('not_owned')
            if kind == 'repair' and ident in own_buildings:
                if order.get('on', True) == own_buildings[ident]['repairing']:
                    continue
            if kind == 'power_toggle':
                want_on = order.get('on', True)
                if want_on == (ident not in self.powered_down):
                    continue
                if want_on:
                    self.powered_down.discard(ident)
                else:
                    self.powered_down.add(ident)
            x, y = order.get('to', order.get('at', [0,0]))
            if kind == 'set_stance':
                x = ('hold_fire','return_fire','defend','attack_anything').index(order['stance'])
            ids = order.get('units', [ident] * order.get('count', 1))
            for actor_id in ids:
                commands.append(pb.Command(action=enums[kind], actor_id=actor_id,
                    target_actor_id=order.get('target', 0), target_x=x, target_y=y,
                    item_type=order.get('item', ''), queued=order.get('queued', False)))
        return commands

    def feedback(self, orders):
        if isinstance(orders, dict):
            orders = orders.get('orders', [])
        return {'accepted': True, 'results': [{'index': i, 'status': 'ok', 'reason': 'no_feedback'}
                for i, _ in enumerate(orders or [])]}


class Bridge:
    def __init__(self, host):
        import grpc
        self.channel = grpc.insecure_channel(host, options=[('grpc.max_receive_message_length',64*1024*1024)])
        grpc.channel_ready_future(self.channel).result(timeout=60)
        self.state = self.channel.unary_unary('/openra.rl.RLBridge/GetState', request_serializer=pb.StateRequest.SerializeToString, response_deserializer=pb.GameState.FromString)
        self.advance = self.channel.unary_unary('/openra.rl.RLBridge/FastAdvance', request_serializer=pb.FastAdvanceRequest.SerializeToString, response_deserializer=pb.GameObservation.FromString)


def policy_hash(repo):
    root = Path(repo) / 'altru_redalert'
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*.py')):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b'\0')
        digest.update(path.read_bytes())
        digest.update(b'\0')
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True)
    parser.add_argument('--host', default='localhost:9999')
    parser.add_argument('--engine', default=str(ROOT / 'OpenRA'))
    parser.add_argument('--map', default='sidestep')
    parser.add_argument('--faction')
    parser.add_argument('--enemy-faction')
    parser.add_argument('--session-id', default='')
    parser.add_argument('--seconds', type=int, default=1200)
    parser.add_argument('--ticks', type=int, default=4)
    parser.add_argument('--output', required=True)
    parser.add_argument('--trace')
    args = parser.parse_args()
    source_hash = policy_hash(args.repo)
    sys.path.insert(0, str(Path(args.repo).resolve()))
    Controller = importlib.import_module('altru_redalert.core').Controller
    static = StaticData(args.engine, args.map)
    bridge = Bridge(args.host)
    state = bridge.state(pb.StateRequest(session_id=args.session_id), timeout=30)
    adapter = SeatAdapter(static, args.faction or state.player_faction, args.enemy_faction or state.enemy_faction, args.seconds)
    controller = Controller()
    started = time.monotonic()
    obs = bridge.advance(pb.FastAdvanceRequest(ticks=1, session_id=args.session_id), timeout=60)
    decisions = Counter()
    samples = []
    trace = open(args.trace, 'w') if args.trace else None
    try:
        while True:
            raw = adapter.observation(obs)
            if obs.done or obs.tick >= args.seconds * 25:
                break
            action = controller.decide(raw, static.config)
            orders = (action or {}).get('orders', [])
            decisions.update(o['cmd'] for o in orders)
            if trace:
                trace.write(json.dumps({'raw':raw,'action':action}, separators=(',',':'))+'\n')
            commands = adapter.commands(orders, raw)
            if orders:
                controller.on_result(adapter.feedback(orders))
            if not samples or obs.tick - samples[-1]['tick'] >= 750:
                sample = {'tick':obs.tick, 'cash':obs.economy.cash, 'ore':obs.economy.ore,
                          'army':obs.military.army_value, 'assets':obs.military.assets_value,
                          'kills_cost':obs.military.kills_cost, 'deaths_cost':obs.military.deaths_cost,
                          'units':dict(Counter(a.type for a in obs.units)), 'buildings':dict(Counter(a.type for a in obs.buildings))}
                samples.append(sample)
                print(json.dumps(sample), flush=True)
            obs = bridge.advance(pb.FastAdvanceRequest(ticks=min(args.ticks, args.seconds*25-obs.tick), commands=commands, session_id=args.session_id), timeout=120)
        report = {'result':obs.result, 'engine_done':obs.done, 'tick':obs.tick, 'seconds':obs.tick/25,
                  'elapsed_s':time.monotonic()-started, 'faction':adapter.faction,'enemy_faction':adapter.enemy_faction,
                  'policy_version':importlib.import_module('altru_redalert').__version__,
                  'policy_source_sha256':source_hash,
                  'source_unchanged_during_run':source_hash == policy_hash(args.repo),
                  'map':args.map,'military':raw['observation']['military'], 'economy':raw['observation']['economy'],
                  'samples':samples,'orders':dict(decisions),'controller_stats':dict(controller.stats),
                  'map_diagnostics':static.map_diagnostics}
        Path(args.output).write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k not in ('samples',)}),flush=True)
    finally:
        if trace:
            trace.close()
        bridge.channel.close()


if __name__ == '__main__':
    main()
