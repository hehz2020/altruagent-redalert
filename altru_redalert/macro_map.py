"""Static public-map planning, with no hidden-world or spectator access.

The resource symbols describe the initial map, not current ore amounts. They
are only siting hints: harvest orders without coordinates let the engine find
currently available resources. Reachability ignores dynamic actor occupancy.
"""
from collections import deque
from .model import distance, pos


class MacroMap:
    def __init__(self, view):
        layout = view.map_info.get("layout", {})
        self.rows = layout.get("rows", []) if isinstance(layout, dict) else []
        self.origin = pos(layout.get("origin")) if isinstance(layout, dict) else None
        self.bounds = view.bounds
        self.resources = set()
        self.mines = set()
        if self.origin and isinstance(self.rows, list):
            for y, row in enumerate(self.rows):
                if not isinstance(row, str):
                    continue
                for x, char in enumerate(row):
                    cell = (self.origin[0] + x, self.origin[1] + y)
                    if char in "$*M":
                        self.resources.add(cell)
                    if char == "M":
                        self.mines.add(cell)
        self.clusters = []
        unseen = set(self.resources)
        while unseen:
            seed = min(unseen)
            unseen.remove(seed)
            cells, pending = [seed], [seed]
            while pending:
                x, y = pending.pop()
                # One-cell gaps belong to the same field, but separate nearby
                # fields remain separate candidate expansion sites.
                for dx in range(-2, 3):
                    for dy in range(-2, 3):
                        cell = (x + dx, y + dy)
                        if cell in unseen:
                            unseen.remove(cell)
                            pending.append(cell)
                            cells.append(cell)
            center = (round(sum(p[0] for p in cells) / len(cells)),
                      round(sum(p[1] for p in cells) / len(cells)))
            self.clusters.append((center, len(cells), any(p in self.mines for p in cells)))
        self._paths = {}

    def char(self, point):
        if self.origin is None or not isinstance(self.rows, list):
            return None
        x, y = point[0] - self.origin[0], point[1] - self.origin[1]
        if 0 <= y < len(self.rows) and isinstance(self.rows[y], str) and 0 <= x < len(self.rows[y]):
            return self.rows[y][x]
        return None

    def clear(self, point):
        if self.bounds is None:
            return False
        x, y, w, h = self.bounds
        return (x <= point[0] < x + w and y <= point[1] < y + h
                and self.char(point) in {".", ",", "=", "_", "$", "*", "S"})

    def distances(self, start):
        """Cardinal ground reachability is conservative around tight corners."""
        start = pos(start)
        if start in self._paths:
            return self._paths[start]
        if start is None or not self.resources:
            return {}
        candidates = [(start[0] + x, start[1] + y) for y in range(-3, 4) for x in range(-3, 4)]
        candidates = [p for p in candidates if self.clear(p)]
        if not candidates:
            return {}
        source = min(candidates, key=lambda p: (distance(start, p), p))
        result, frontier = {source: 0}, deque([source])
        while frontier:
            p = frontier.popleft()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                q = (p[0] + dx, p[1] + dy)
                if q not in result and self.clear(q):
                    result[q] = result[p] + 1
                    frontier.append(q)
        if len(self._paths) >= 6:
            self._paths.clear()
        self._paths[start] = result
        return result

    def expansion(self, view, blocked=()):
        anchors = [pos(b) for b in view.buildings if b.get("type") in {"fact", "proc"} and pos(b)]
        if not anchors or not view.base:
            return None
        paths = self.distances(view.base)
        threats = [pos(e) for e in view.enemies + view.enemy_buildings if pos(e)]
        candidates = []
        for center, size, regrows in self.clusters:
            if size < 5 and not regrows:
                continue
            if min(distance(center, a) for a in anchors) < 20:
                continue
            if any(distance(center, p) < 16 for p in blocked):
                continue
            if any(distance(center, p) < 20 for p in threats):
                continue
            # Stay on our half until there is a separate offensive-expansion
            # policy. This is a conservative prior, not knowledge through fog.
            if view.enemy_base and distance(center, view.enemy_base) < distance(center, view.base) + 8:
                continue
            sites = []
            for dx in range(-9, 10):
                for dy in range(-9, 10):
                    cell = (center[0] + dx, center[1] + dy)
                    if not 5 <= distance(cell, center) <= 9 or cell not in paths:
                        continue
                    # The actual yard site, not only its ore field, must be
                    # outside existing refinery coverage. Otherwise macro
                    # could consider this expansion already served and omit
                    # the follow-up refinery it reserved money to build.
                    if any(distance(cell, anchor) < 18 for anchor in anchors):
                        continue
                    # Approximate the MCV yard footprint with clearance around
                    # its center. Actual legality remains the engine's decision.
                    if not all(self.clear((cell[0] + x, cell[1] + y))
                               and (cell[0] + x, cell[1] + y) not in self.resources
                               for x in range(-1, 2) for y in range(-1, 3)):
                        continue
                    sites.append((paths[cell] + distance(cell, view.base) * .2, cell))
            if sites:
                route, site = min(sites)
                score = route - min(size, 80) * .25 - (8 if regrows else 0)
                candidates.append((score, site))
        return min(candidates)[1] if candidates else None
