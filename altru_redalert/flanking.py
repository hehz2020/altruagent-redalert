from heapq import heappop, heappush
from math import ceil, hypot

from .model import distance, living, pos
from .tactics import damage_rate, health, weapon_range, weapons


MAX_SEARCH = 16000
ROUTE_LIFETIME = 16.
MOBILE_MEMORY = 20.
STATIC_MEMORY = 90.


def _length(path):
    return sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:]))


def _clear_segment(routes, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    steps = max(abs(dx), abs(dy))
    point = start
    for i in range(1, steps + 1):
        following = (round(start[0] + dx * i / steps), round(start[1] + dy * i / steps))
        if following != point and following not in dict(routes._neighbors(point)):
            return False
        point = following
    return True


class FlankPlanner:
    def __init__(self):
        self.navigation = None
        self.goal = None
        self.path = []
        self.cursor = 0
        self.created = -1000.
        self.progress_at = -1000.
        self.progress_origin = None
        self.threat_keys = set()
        self.searches = 0
        self.flanking = False
        self.blocked_until = {}

    def _threats(self, view, army, contacts):
        visible = {a['id']: a for a in view.enemies + view.enemy_buildings
                   if living(a) and pos(a) is not None}
        static_ids = {a['id'] for a in view.enemy_buildings}
        known = [(a, 1., a['id'] in static_ids) for a in visible.values()]
        for uid, (a, seen, building) in contacts.items():
            ttl = STATIC_MEMORY if building else MOBILE_MEMORY
            age = max(0., view.now - seen)
            if uid not in visible and living(a) and pos(a) is not None and age < ttl:
                known.append((a, max(.25, 1. - age / ttl), building))
        samples = {}
        for a in army:
            samples.setdefault(str(a.get('type', '')).lower(), a)
        total_health = max(5000., sum(health(view, a) for a in army))
        result = []
        for a, confidence, building in known:
            if not weapons(view, a):
                continue
            rate = max((damage_rate(view, a, b) for b in samples.values()), default=0.)
            radius = max((weapon_range(view, a, b) for b in samples.values()), default=0.)
            if rate <= 0 or radius <= 0:
                continue
            radius = min(15., radius + (1.5 if building else 3.))
            weight = min(12., 100. * rate / total_health) * confidence
            result.append((a['id'], pos(a), radius, weight))
        return result

    def _risk_map(self, routes, threats):
        risk = {}
        for _, (x, y), radius, weight in threats:
            extent = ceil(radius)
            for yy in range(y - extent, y + extent + 1):
                for xx in range(x - extent, x + extent + 1):
                    point = (xx, yy)
                    d = hypot(xx - x, yy - y)
                    if point in routes.cells and d < radius:
                        risk[point] = risk.get(point, 0.) + weight * min(1., (radius - d) / 2.)
        return risk

    def _search(self, routes, direct, risk):
        self.searches += 1
        start, target = direct[0], direct[-1]
        shortest = _length(direct)
        limit = min(shortest * 1.7 + 4., shortest + 32.)
        best = {start: 0.}
        lengths = {start: 0.}
        previous = {}
        pending = [(distance(start, target), 0., start)]
        expanded = 0
        while pending and expanded < MAX_SEARCH:
            _, cost, point = heappop(pending)
            if cost != best.get(point):
                continue
            expanded += 1
            if point == target:
                path = [target]
                while path[-1] != start:
                    path.append(previous[path[-1]])
                return list(reversed(path))
            for neighbor, step in routes._neighbors(point):
                step = step / 10.
                length = lengths[point] + step
                if length + distance(neighbor, target) > limit:
                    continue
                candidate = cost + step * (1. + .5 * (risk.get(point, 0.) + risk.get(neighbor, 0.)))
                if candidate < best.get(neighbor, float('inf')):
                    best[neighbor] = candidate
                    lengths[neighbor] = length
                    previous[neighbor] = point
                    heappush(pending, (candidate + distance(neighbor, target), candidate, neighbor))
        return direct

    def _risk(self, path, risks):
        return sum(distance(a, b) * .5 * (risks.get(a, 0.) + risks.get(b, 0.))
                   for a, b in zip(path, path[1:]))

    def _choose(self, routes, start, goal, threats):
        direct = routes.path(start, goal)
        if len(direct) < 2 or not threats:
            self.flanking = False
            return direct
        risks = self._risk_map(routes, threats)
        direct_risk = self._risk(direct, risks)
        if direct_risk < 5.:
            self.flanking = False
            return direct
        alternative = self._search(routes, direct, risks)
        extra = _length(alternative) - _length(direct)
        saved = direct_risk - self._risk(alternative, risks)
        self.flanking = saved > max(4., extra * 1.2) and saved > direct_risk * .2
        return alternative if self.flanking else direct

    def waypoint(self, view, routes, army, start, goal, contacts, step=6.):
        if not routes.available:
            return None
        start, goal = pos(start), pos(goal)
        if start not in routes.cells or goal is None:
            return None
        threats = self._threats(view, army, contacts)
        keys = {(uid, point[0] // 4, point[1] // 4) for uid, point, _, _ in threats}
        target_changed = self.goal is None or distance(goal, self.goal) > 5
        fresh = (self.navigation is not routes or target_changed or not self.path)
        if self.navigation is not routes or target_changed:
            self.blocked_until.clear()
            self.progress_origin = None
        near_path = self.path[self.cursor:min(len(self.path), self.cursor + 22)]
        obstructed = any((uid, point[0] // 4, point[1] // 4) not in self.threat_keys
                         and weight > .5 and any(distance(point, cell) < radius for cell in near_path)
                         for uid, point, radius, weight in threats)
        if self.progress_origin is None or distance(start, self.progress_origin) >= 3:
            self.progress_origin, self.progress_at = start, view.now
        stalled = (view.now - self.progress_at >= 12. and self.path
                   and distance(start, self.path[-1]) > 3)
        self.blocked_until = {cell: expiry for cell, expiry in self.blocked_until.items()
                              if expiry > view.now}
        if stalled and self.cursor + 3 < len(self.path):
            blocked = self.path[self.cursor + 3]
            if distance(blocked, goal) > 6:
                self.blocked_until[blocked] = view.now + 24.
        threats += [(('blocked', cell), cell, 2.5, 6.) for cell in self.blocked_until]
        if (fresh or view.now - self.created >= ROUTE_LIFETIME
                or (obstructed and view.now - self.created >= 3.) or stalled):
            self.path = self._choose(routes, start, goal, threats)
            self.navigation, self.goal = routes, goal
            self.created, self.cursor = view.now, 0
            self.threat_keys = keys
            if fresh or stalled:
                self.progress_origin, self.progress_at = start, view.now
        if not self.path:
            return None
        end = min(len(self.path), self.cursor + 24)
        adjacent = [i for i in range(self.cursor, end) if distance(start, self.path[i]) <= 3
                    and _clear_segment(routes, start, self.path[i])]
        if not adjacent:
            self.created = -1000.
            return routes.waypoint(start, self.path[self.cursor], distance_cells=step)
        self.cursor = min(adjacent, key=lambda i: (distance(start, self.path[i]), -i))
        current = self.cursor
        used = distance(start, self.path[current])
        while current + 1 < len(self.path):
            increment = distance(self.path[current], self.path[current + 1])
            if used + increment > step:
                break
            current += 1
            used += increment
        return list(self.path[current])
