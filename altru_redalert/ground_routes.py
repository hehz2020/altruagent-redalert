from collections import OrderedDict, deque
from heapq import heappop, heappush
from math import isfinite

from .model import pos


PASSABLE = frozenset(".,=_$*S")
MAX_CELLS = 65536
FIELD_CACHE_LIMIT = 4
TARGET_CACHE_LIMIT = 32
_STEPS = ((0, -1, 10), (-1, 0, 10), (1, 0, 10), (0, 1, 10),
          (-1, -1, 14), (1, -1, 14), (-1, 1, 14), (1, 1, 14))


def _signature(view):
    map_info = getattr(view, "map_info", None)
    layout = map_info.get("layout") if isinstance(map_info, dict) else None
    if not isinstance(layout, dict):
        return None
    rows, origin, bounds = layout.get("rows"), layout.get("origin"), getattr(view, "bounds", None)
    if (not isinstance(rows, (list, tuple)) or not rows
            or any(not isinstance(row, str) for row in rows)
            or not rows[0] or any(len(row) != len(rows[0]) for row in rows)
            or len(rows) * len(rows[0]) > MAX_CELLS
            or not isinstance(origin, (list, tuple)) or len(origin) != 2
            or not isinstance(bounds, (list, tuple)) or len(bounds) != 4
            or any(isinstance(n, bool) or not isinstance(n, int) for n in (*origin, *bounds))
            or bounds[2] <= 0 or bounds[3] <= 0):
        return None
    return (getattr(view, "map_id", None), tuple(bounds), tuple(origin), tuple(rows))


class GroundRoutes:


    def __init__(self, view):
        self.signature = _signature(view)
        self.cells = frozenset()
        self._component = {}
        self._members = []
        self._fields = OrderedDict()
        self._targets = OrderedDict()
        if self.signature is None:
            return
        _, bounds, origin, rows = self.signature
        bx, by, width, height = bounds
        self.cells = frozenset(
            (origin[0] + x, origin[1] + y)
            for y, row in enumerate(rows) for x, char in enumerate(row)
            if char in PASSABLE and bx <= origin[0] + x < bx + width
            and by <= origin[1] + y < by + height)
        unseen = set(self.cells)
        for start in sorted(self.cells):
            if start not in unseen:
                continue
            unseen.remove(start)
            index = len(self._members)
            members, pending = [start], deque([start])
            self._component[start] = index
            while pending:
                current = pending.popleft()
                for neighbor, _ in self._neighbors(current):
                    if neighbor in unseen:
                        unseen.remove(neighbor)
                        self._component[neighbor] = index
                        members.append(neighbor)
                        pending.append(neighbor)
            self._members.append(tuple(members))

    @property
    def available(self):

        return bool(self.cells)

    def matches(self, view):
        return self.signature == _signature(view)

    def _neighbors(self, point):
        x, y = point
        for dx, dy, cost in _STEPS:
            neighbor = (x + dx, y + dy)
            if neighbor not in self.cells:
                continue
            if dx and dy and ((x + dx, y) not in self.cells or (x, y + dy) not in self.cells):
                continue
            yield neighbor, cost

    def reachable(self, start, goal):

        start, goal = pos(start), pos(goal)
        index = self._component.get(start)
        return index is not None and self._component.get(goal) == index

    def _project(self, index, goal):
        key = (index, goal)
        if key in self._targets:
            self._targets.move_to_end(key)
            return self._targets[key]
        if self._component.get(goal) == index:
            target = goal
        else:
            target = min(self._members[index], key=lambda p:
                         ((p[0] - goal[0]) ** 2 + (p[1] - goal[1]) ** 2, p[1], p[0]))
        self._targets[key] = target
        if len(self._targets) > TARGET_CACHE_LIMIT:
            self._targets.popitem(last=False)
        return target

    def _build_field(self, target):
        costs, next_cell, pending = {target: 0}, {}, [(0, target)]
        while pending:
            cost, current = heappop(pending)
            if costs[current] != cost:
                continue
            for neighbor, step in self._neighbors(current):
                candidate = cost + step
                if candidate < costs.get(neighbor, float("inf")):
                    costs[neighbor] = candidate
                    next_cell[neighbor] = (current, step)
                    heappush(pending, (candidate, neighbor))
        return costs, next_cell

    def path(self, start, goal):
        start, goal = pos(start), pos(goal)
        if start not in self._component or goal is None:
            return []
        target = self._project(self._component[start], goal)
        if target not in self._fields:
            self._fields[target] = self._build_field(target)
            if len(self._fields) > FIELD_CACHE_LIMIT:
                self._fields.popitem(last=False)
        self._fields.move_to_end(target)
        _, following = self._fields[target]
        result = [start]
        while result[-1] in following:
            result.append(following[result[-1]][0])
        return result

    def waypoint(self, start, goal, distance_cells=6):

        start, goal = pos(start), pos(goal)
        if (start not in self._component or goal is None
                or isinstance(distance_cells, bool) or not isinstance(distance_cells, (int, float))
                or not isfinite(distance_cells) or distance_cells <= 0):
            return None
        target = self._project(self._component[start], goal)
        if start == target:
            return list(start)
        budget = distance_cells * 10
        if budget >= 14 * (len(self._members[self._component[start]]) - 1):
            return list(target)
        if target not in self._fields:
            self._fields[target] = self._build_field(target)
            if len(self._fields) > FIELD_CACHE_LIMIT:
                self._fields.popitem(last=False)
        self._fields.move_to_end(target)
        costs, route = self._fields[target]
        if costs[start] <= budget:
            return list(target)
        current, used = start, 0
        while current in route:
            following, step = route[current]
            if used + step > budget:
                break
            current, used = following, used + step
        return list(current)
