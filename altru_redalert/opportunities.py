"""Choose limited raids using observed targets and expiring threat memory.

These are conservative estimates for choosing a raid, not a combat simulator.
The caller owns squad allocation, emergencies, order submission and withdrawal.
"""

from dataclasses import dataclass, replace
from heapq import heappop, heappush
from math import ceil

from .ground_routes import GroundRoutes
from .model import distance, living, number, pos
from .tactics import damage_rate, health, kind, speed, weapon_range


MOBILE_MEMORY = 20.
STATIC_MEMORY = 90.
MAX_SEARCH = 7000
DECISION_CACHE_SECONDS = 1.
TARGET_VALUES = {'mcv': 2800., 'harv': 1700., 'proc': 1800.,
                 'weap': 1500., 'powr': 500., 'apwr': 900., 'e6': 600.}


@dataclass(frozen=True)
class RaidOpportunity:
    target: dict
    path: tuple
    waypoint: tuple
    score: float
    travel_seconds: float
    kill_seconds: float
    risk: float


def _known_threats(view, squad, contacts):
    """Deduplicate visible actors; memory can add hazards, never targets."""
    current = {a['id']: a for a in view.enemies + view.enemy_buildings
               if living(a) and pos(a) is not None}
    structures = {a['id'] for a in view.enemy_buildings}
    known = [(a, 1., a['id'] in structures) for a in current.values()]
    for uid, entry in (contacts or {}).items():
        if uid in current or not isinstance(entry, (list, tuple)) or len(entry) != 3:
            continue
        actor, seen, static = entry
        if not living(actor) or pos(actor) is None:
            continue
        age = max(0., view.now - number(seen, -1e6))
        ttl = STATIC_MEMORY if static else MOBILE_MEMORY
        if age >= ttl:
            continue
        actor = dict(actor)
        # An old power outage is not evidence that a hidden tower remains off.
        if static and age > 5:
            actor.pop('powered', None)
            actor.pop('disabled', None)
        known.append((actor, max(.35, 1. - age / ttl), bool(static)))
    result = []
    samples = {kind(a): a for a in squad}.values()
    for actor, confidence, static in known:
        dps = max((damage_rate(view, actor, a) for a in samples), default=0.)
        reach = max((weapon_range(view, actor, a) for a in samples), default=0.)
        if dps > 0 and reach > 0:
            result.append((actor, confidence, static, dps, reach))
    return result


def _route_risk(view, routes, threats, total_hp):
    risk, blocked = {}, set()
    for actor, confidence, static, dps, reach in threats:
        center = pos(actor)
        radius = min(18., reach + (1. if static else min(4., speed(view, actor) * 2.)))
        extent = ceil(radius)
        for x in range(center[0] - extent, center[0] + extent + 1):
            for y in range(center[1] - extent, center[1] + extent + 1):
                cell = (x, y)
                if routes.available and cell not in routes.cells:
                    continue
                d = distance(cell, center)
                if d > radius:
                    continue
                if static:
                    # A small economic raid should not trade tanks for towers.
                    blocked.add(cell)
                else:
                    rate = dps * confidence / total_hp
                    risk[cell] = risk.get(cell, 0.) + rate * (1. if d <= reach else .65)
    return risk, blocked


def _length(path):
    return sum(distance(a, b) for a, b in zip(path, path[1:]))


def _actor_key(actor):
    # Exact coordinates avoid reusing a safe waypoint after either side moves.
    return (actor['id'], kind(actor), number(actor.get('x')), number(actor.get('y')),
            number(actor.get('hp'), 100), actor.get('powered'), actor.get('disabled'))


def _decision_key(view, squad, contacts, routes):
    visible = {a['id']: a for a in view.enemies + view.enemy_buildings
               if living(a) and pos(a) is not None}
    static_ids = {a['id'] for a in view.enemy_buildings}
    remembered = []
    kinds = {kind(a) for a in squad + list(visible.values())}
    for uid, entry in (contacts or {}).items():
        if uid in visible or not isinstance(entry, (list, tuple)) or len(entry) != 3:
            continue
        actor, seen, static = entry
        if not living(actor) or pos(actor) is None:
            continue
        seen = number(seen, -1e6)
        age = max(0., view.now - seen)
        if age >= (STATIC_MEMORY if static else MOBILE_MEMORY):
            continue
        kinds.add(kind(actor))
        # Age may decay confidence safely for a second, but expiry and the
        # end of a recently observed power outage invalidate immediately.
        remembered.append((uid, _actor_key(actor), seen, bool(static), bool(static and age > 5)))
    return (view.map_id, view.bounds, routes.signature, tuple(_actor_key(a) for a in squad),
            tuple((_actor_key(a), a['id'] in static_ids) for a in visible.values()),
            tuple(remembered), tuple((k, repr(view.spec(k))) for k in sorted(kinds)))


def _search(routes, start, target, reach, risks, blocked, max_length, budget=None):
    """Find a firing position without walking through remembered tower fire."""
    if start in blocked:
        return []
    if budget is None:
        budget = [MAX_SEARCH]
    best, previous, lengths = {start: 0.}, {}, {start: 0.}
    pending = [(max(0., distance(start, target) - reach), 0., start)]
    while pending and budget[0] > 0:
        _, cost, point = heappop(pending)
        if cost != best.get(point):
            continue
        budget[0] -= 1
        if distance(point, target) <= reach:
            path = [point]
            while path[-1] != start:
                path.append(previous[path[-1]])
            return list(reversed(path))
        for neighbor, step in routes._neighbors(point):
            if neighbor in blocked:
                continue
            step /= 10.
            length = lengths[point] + step
            if length + max(0., distance(neighbor, target) - reach) > max_length:
                continue
            candidate = cost + step * (1. + 80. * risks.get(neighbor, 0.))
            if candidate < best.get(neighbor, float('inf')):
                best[neighbor], previous[neighbor], lengths[neighbor] = candidate, point, length
                heuristic = max(0., distance(neighbor, target) - reach)
                heappush(pending, (candidate + heuristic, candidate, neighbor))
    return []


def _straight(start, target, reach):
    steps = max(abs(start[0] - target[0]), abs(start[1] - target[1]))
    path = [start]
    for i in range(1, steps + 1):
        if distance(path[-1], target) <= reach:
            break
        cell = (round(start[0] + (target[0] - start[0]) * i / steps),
                round(start[1] + (target[1] - start[1]) * i / steps))
        if cell != path[-1]:
            path.append(cell)
    return path


class RaidOpportunities:
    def __init__(self):
        self.routes = None
        self._cache_key = None
        self._cache_when = -1e6
        self._cache_choice = None

    def choose(self, view, squad, contacts=None, *, routes=None, emergency=False):
        """Return a current visible opportunity, or None if the raid is unsafe.

        Pass only the proposed raiders, never the whole army. With no terrain
        layout this evaluates a short geometric approach; connectivity cannot
        be certified, so distant targets are left to normal scouting/navigation.
        """
        if emergency:
            return None
        squad = [a for a in squad if living(a) and pos(a) is not None
                 and speed(view, a) > 0]
        if not squad:
            return None
        # A dispersed group is not one force; regroup it before assigning a raid.
        center = (sum(pos(a)[0] for a in squad) / len(squad),
                  sum(pos(a)[1] for a in squad) / len(squad))
        if any(distance(a, center) > 10 for a in squad):
            return None
        start = pos(min(squad, key=lambda a: distance(a, center)))
        if routes is None or not routes.matches(view):
            if self.routes is None or not self.routes.matches(view):
                self.routes = GroundRoutes(view)
            routes = self.routes
        if routes.available and start not in routes.cells:
            return None
        key = _decision_key(view, squad, contacts, routes)
        age = view.now - self._cache_when
        if key == self._cache_key and 0 <= age < DECISION_CACHE_SECONDS:
            choice = self._cache_choice
            if choice is None:
                return None
            if choice.travel_seconds + choice.kill_seconds + 6 < view.remaining:
                # Return this observation's actor, not a retained actor record.
                target = next(a for a in view.enemies + view.enemy_buildings
                              if a['id'] == choice.target['id'])
                return replace(choice, target=target)
        total_hp = max(1., sum(health(view, a) for a in squad))
        pace = min(speed(view, a) for a in squad)
        threats = _known_threats(view, squad, contacts)
        risks, blocked = _route_risk(view, routes, threats, total_hp)
        targets = [a for a in view.enemies + view.enemy_buildings
                   if living(a) and pos(a) is not None and kind(a) in TARGET_VALUES]
        targets.sort(key=lambda a: (-TARGET_VALUES[kind(a)] / (12. + distance(start, a)), a['id']))
        opportunities = []
        # One decision shares a deterministic work cap across every candidate.
        # If it is exhausted, retain only a fully checked earlier opportunity;
        # otherwise normal army behavior continues without an economic raid.
        search_budget = [MAX_SEARCH]
        for target in targets[:12]:
            if routes.available and search_budget[0] <= 0:
                break
            point = pos(target)
            shooters = [a for a in squad if damage_rate(view, a, target) > 0]
            if not shooters:
                continue
            reach = min(weapon_range(view, a, target) for a in shooters) - .6
            rate = sum(damage_rate(view, a, target) for a in shooters)
            kill_seconds = health(view, target) / max(1., rate)
            if reach <= 0 or kill_seconds > 30:
                continue
            # Do not turn projection onto our bank into a cross-map chase.
            if routes.available and point in routes.cells and not routes.reachable(start, point):
                continue
            maximum = min(70., distance(start, point) * 1.55 + 8.)
            if routes.available:
                extent = ceil(reach)
                firing_cells = ((x, y)
                                for x in range(point[0] - extent, point[0] + extent + 1)
                                for y in range(point[1] - extent, point[1] + extent + 1))
                if not any(cell not in blocked and routes.reachable(start, cell)
                           and distance(cell, point) <= reach for cell in firing_cells):
                    continue
                path = _search(routes, start, point, reach, risks, blocked, maximum, search_budget)
            else:
                if distance(start, point) > 24:
                    continue
                path = _straight(start, point, reach)
                if any(cell in blocked for cell in path):
                    path = []
            if not path:
                continue
            length = _length(path)
            travel = length / pace
            if travel + kill_seconds + 6 >= view.remaining:
                continue
            transit_risk = sum(distance(a, b) / pace *
                               max(risks.get(a, 0.), risks.get(b, 0.))
                               for a, b in zip(path, path[1:]))
            endpoint = path[-1]
            firing_risk = 0.
            for guard, confidence, static, dps, guard_range in threats:
                gap = max(0., distance(guard, endpoint) - guard_range)
                if static:
                    exposure = kill_seconds if gap <= 1. else 0.
                else:
                    # Nearby guards can intercept during the kill, including
                    # guards just beyond their current weapon radius.
                    exposure = max(0., kill_seconds - gap / max(.1, speed(view, guard)))
                firing_risk += dps * confidence * exposure / total_hp
            risk = transit_risk + firing_risk
            if firing_risk > .16 or risk > .20:
                continue
            value = TARGET_VALUES[kind(target)]
            value *= .7 + .3 * min(1., number(target.get('hp'), 100) / 100.)
            score = value * (1. - min(.8, risk * 3.)) / (12. + travel + kill_seconds)
            travelled, waypoint = 0., path[0]
            for a, b in zip(path, path[1:]):
                travelled += distance(a, b)
                if travelled > 6.:
                    break
                waypoint = b
            opportunities.append(RaidOpportunity(target, tuple(path), waypoint, score,
                                                  travel, kill_seconds, risk))
        choice = max(opportunities, key=lambda o: (o.score, -o.target['id']), default=None)
        # One entry bounds memory and also remembers expensive negative results.
        self._cache_key, self._cache_when, self._cache_choice = key, view.now, choice
        return choice
