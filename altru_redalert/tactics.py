from dataclasses import dataclass
from math import sqrt

from .model import distance, number, pos

AIR = {'mig', 'yak', 'heli', 'hind', 'mh60', 'u2', 'badr', 'badr.bomber', 'tran'}
ARTILLERY = {'arty', 'v2rl'}
INFANTRY = {'e1', 'e2', 'e3', 'e4', 'e6', 'e7', 'dog', 'shok', 'medi', 'mech', 'spy', 'thf'}
DEFENSE = {'pbox', 'hbox', 'gun', 'ftur', 'tsla', 'agun', 'sam'}
HEAVY = {'1tnk', '2tnk', '3tnk', '4tnk', 'apc', 'harv', 'mcv', 'ctnk', 'stnk', 'ttnk'} | DEFENSE


@dataclass(frozen=True)
class Weapon:
    name: str
    range: float
    damage: float
    reload: float
    versus: tuple = (1., 1., 1., 1., 1.)
    burst: float = 1.
    minimum: float = 0.
    domain: str = 'ground'
    splash: float = 0.
    accuracy: float = 1.


MG = (1.5, .1, .3, .1, .1)
CANNON = (.3, .75, .75, 1.15, .5)
PROFILES = {
    'e1': (Weapon('M1Carbine', 5., 1000, .8, (1.5, .3, .4, .1, .1)),),
    'e2': (Weapon('Grenade', 4., 6000, 2.4, (.6, 1., .25, .25, 1.), splash=.4, accuracy=.8),),
    'e3': (Weapon('Dragon', 5., 5000, 2., (.1, .74, .34, 1., .5), minimum=.5),
           Weapon('RedEye', 7.5, 2400, 2., domain='air')),
    'e4': (Weapon('Flamer', 5., 1000, 2.6, (.7, .8, .4, .2, .1), burst=15, splash=.5, accuracy=.65),),
    'e7': (Weapon('Colt45', 7., 10000, .4, (1., 0., 0., 0., 0.)),),
    'dog': (Weapon('DogJaw', 1.5, 100000, 1., (1., 0., 0., 0., 0.)),),
    '1tnk': (Weapon('25mm', 4.75, 2500, .84, (.32, .52, 1.16, .48, .32)),),
    '2tnk': (Weapon('90mm', 4.75, 4000, 2., CANNON),),
    '3tnk': (Weapon('105mm', 4.75, 4000, 2.92, CANNON, burst=2),),
    '4tnk': (Weapon('120mm', 4.75, 6000, 3.72, (0., .75, .75, 1.15, .5), burst=2),
             Weapon('MammothTusk', 6.5, 5000, 2.52, (1., 0., 0., 0., 0.), burst=2),
             Weapon('MammothTusk', 6.5, 5000, 2.52, burst=2, domain='air')),
    'jeep': (Weapon('M60mg', 4., 1000, 1.52, MG, burst=5),),
    'apc': (Weapon('M60mg', 4., 1000, 1.52, MG, burst=5),),
    'ftrk': (Weapon('FLAK-23-AG', 6., 2000, .4, (.4, .1, .6, .1, .2)),
             Weapon('FLAK-23-AA', 8., 1200, .4, domain='air')),
    'arty': (Weapon('155mm', 12., 23000, 3.4, (.6, .4, .6, .25, .5), minimum=4., splash=.8, accuracy=.55),),
    'v2rl': (Weapon('SCUD', 10., 4500, 8.6, (.9, .75, .7, .4, 1.), burst=10, minimum=4., splash=.8, accuracy=.75),),
    'shok': (Weapon('PortaTesla', 6., 4500, 2.8, (10., .73, 1., .6, 1.)),),
    'ttnk': (Weapon('TTankZap', 7., 10000, 4.8, (10., 1., 1., 1., 1.)),),
    'gun': (Weapon('TurretGun', 6.5, 6000, 1.2, (.2, .5, .75, 1., .5)),),
    'tsla': (Weapon('TeslaZap', 7., 10000, 2.4, (10., .6, 1., 1., 1.)),),
    'pbox': (Weapon('Vulcan', 5., 1000, 1.6, (2., .5, .5, .2, .2), burst=6),),
    'hbox': (Weapon('Vulcan', 5., 1000, 1.6, (2., .5, .5, .2, .2), burst=6),),
    'ftur': (Weapon('FireballLauncher', 5., 10000, 2.8, (1., .6, .5, .25, .2), burst=2, splash=.7),),
    'agun': (Weapon('ZSU-23', 8., 900, .4, domain='air'),),
    'sam': (Weapon('Nike', 7.5, 4500, .6, domain='air'),),
}
DEFAULT_HP = {'e1': 5000, 'e2': 5000, 'e3': 4500, 'e4': 4000, 'dog': 1800,
              '1tnk': 23000, '2tnk': 46000, '3tnk': 60000, '4tnk': 90000,
              'jeep': 15000, 'ftrk': 15000, 'apc': 35000, 'arty': 10000,
              'v2rl': 20000, 'harv': 60000, 'mcv': 60000}
DEFAULT_SPEED = {'e1': 1.32, 'e2': 1.66, 'e3': 1.32, 'e4': 1.32, 'dog': 2.44,
                 '1tnk': 2.76, '2tnk': 1.76, '3tnk': 1.56, '4tnk': 1.05,
                 'jeep': 4., 'ftrk': 2.76, 'apc': 3.12, 'arty': 1.76, 'v2rl': 1.76}


def kind(actor):
    return str(actor.get('type', '')).lower()


def health(view, actor):
    base = max(1., number(view.spec(kind(actor)).get('hp'),
                          DEFAULT_HP.get(kind(actor), 40000 if kind(actor) in DEFENSE else 18000)))
    return base * max(.01, min(1., number(actor.get('hp'), 100) / 100))


def speed(view, actor):
    k = kind(actor)
    return max(0., number(view.spec(k).get('speed'), 0 if k in DEFENSE else DEFAULT_SPEED.get(k, 1.6)))


def armor(view, actor):
    value = view.spec(kind(actor)).get('armor')
    if isinstance(value, dict):
        value = value.get('type')
    if isinstance(value, str) and value.lower() in ('none', 'wood', 'light', 'heavy', 'concrete'):
        return ('none', 'wood', 'light', 'heavy', 'concrete').index(value.lower())
    k = kind(actor)
    if k in INFANTRY or view.queue(k) == 'Infantry':
        return 0
    if k in HEAVY:
        return 3
    if view.queue(k) in {'Building', 'Defense'} or actor in view.buildings + view.enemy_buildings:
        return 1
    return 2


def weapons(view, actor):
    if actor.get('powered') is False or actor.get('disabled') is True:
        return ()
    k = kind(actor)
    observed = view.spec(k).get('weapon')
    observed = observed if isinstance(observed, dict) else {}
    cache_key = (k, str(observed.get('weapon', '')),
                 number(observed.get('range_cells'), None),
                 number(observed.get('damage'), None),
                 number(observed.get('reload_seconds'), None))
    cached = view._weapon_profiles.get(cache_key)
    if cached is not None:
        return cached
    profiles = PROFILES.get(k, ())
    if not profiles and number(observed.get('damage')) > 0:
        profiles = (Weapon(str(observed.get('weapon', 'unknown')),
                           number(observed.get('range_cells'), 4.),
                           number(observed.get('damage')), 2.),)
    result = []
    for w in profiles:
        matches = str(observed.get('weapon', '')).lower() == w.name.lower()
        result.append(Weapon(w.name,
            max(0., number(observed.get('range_cells'), w.range)) if matches else w.range,
            max(0., number(observed.get('damage'), w.damage)) if matches else w.damage,
            max(.08, number(observed.get('reload_seconds'), w.reload)) if matches else w.reload,
            w.versus, w.burst, w.minimum, w.domain, w.splash, w.accuracy))
    result = tuple(result)
    view._weapon_profiles[cache_key] = result
    return result


def weapon_range(view, attacker, target=None):
    ws = weapons(view, attacker)
    if target is not None:
        domain = 'air' if kind(target) in AIR else 'ground'
        ws = [w for w in ws if w.domain == domain and w.versus[armor(view, target)] > 0]
    return max((w.range for w in ws), default=0.)


def damage_rate(view, attacker, target, *, at_distance=None, horizon=0.):

    domain = 'air' if kind(target) in AIR else 'ground'
    target_armor = armor(view, target)
    best = 0.
    for w in weapons(view, attacker):
        if w.domain != domain:
            continue
        participation = 1.
        if at_distance is not None:
            if at_distance < w.minimum:
                continue
            if at_distance > w.range:
                if horizon <= 0 or speed(view, attacker) <= 0:
                    continue
                travel = (at_distance - w.range) / speed(view, attacker)
                participation = max(0., 1. - travel / horizon)
        rate = w.damage * w.burst / w.reload * w.versus[target_armor] * w.accuracy
        rate = min(rate, health(view, target) * 2.)
        best = max(best, rate * participation)
    return best


def force_ratio(view, own, enemy, horizon=8., *, projected=False):

    if not own:
        return 0.
    if not enemy:
        return 10.
    own_armed = [a for a in own if weapons(view, a)]
    enemy_armed = [a for a in enemy if weapons(view, a)]
    if not enemy_armed:
        return 10.
    if not own_armed:
        return 0.

    def engagement_distance(a, b):
        current = distance(pos(a), pos(b))
        if not projected:
            return current
        own_range = weapon_range(view, a, b)
        if speed(view, a) > 0 and own_range > 0:
            if max(0., current - own_range) <= speed(view, a) * horizon:
                return min(current, own_range)
        elif speed(view, a) == 0 and speed(view, b) > 0:
            attacking_range = weapon_range(view, b, a)
            if (attacking_range > 0 and max(0., current - attacking_range)
                    <= speed(view, b) * horizon):
                return min(current, attacking_range)
        return current

    def totals(force, opponents):
        output = 0.
        available_health = 0.
        for a in force:
            distances = [engagement_distance(a, b) for b in opponents]
            rates = [damage_rate(view, a, b, at_distance=d, horizon=horizon)
                     for b, d in zip(opponents, distances)]
            best = max(rates, default=0.)
            if best <= 0:
                continue
            positive = sorted((r for r in rates if r > 0), reverse=True)
            output += .55 * best + .45 * sum(positive) / max(1, len(positive))
            nearest = min(distances)
            join = max(.15, 1. - max(0., nearest - weapon_range(view, a))
                       / max(1., speed(view, a) * horizon))
            available_health += health(view, a) * join
        return available_health, output

    oh, od = totals(own_armed, enemy_armed)
    eh, ed = totals(enemy_armed, own_armed)
    if od <= 0:
        return 0.
    if ed <= 0:
        return 10.
    return sqrt(max(.001, oh * od / max(1., eh * ed)))


def target_score(view, attacker, target, enemies=()):
    d = distance(pos(attacker), pos(target))
    rate = damage_rate(view, attacker, target, at_distance=d)
    if rate <= 0:
        return 0.
    armed = bool(weapons(view, target))
    strategic = 1.35 if kind(target) in {'arty', 'v2rl', 'harv', 'e6', 'mcv'} else 1.
    if not armed and kind(target) not in {'harv', 'e6', 'mcv'}:
        strategic *= .6
    finish = 1. + min(1., rate * 2. / health(view, target))
    splash = max((w.splash for w in weapons(view, attacker)), default=0.)
    cluster = sum(distance(pos(target), pos(e)) < 2.5 for e in enemies if e is not target)
    return rate * strategic * finish * (1. + splash * min(2, cluster)) / (1. + d / 15.)
