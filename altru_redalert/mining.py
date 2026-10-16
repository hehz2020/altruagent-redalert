from collections import deque
from math import hypot

from .model import Intent, distance, number, pos
from .tactics import damage_rate, health, weapons


class MiningManager:
    def __init__(self):
        self.units = {}
        self._map = None
        self._offered = {}
        self._issued = {}

    def _signature(self, order):
        return order.get("cmd"), tuple(order["to"]) if "to" in order else None

    def _offer(self, uid, order, now, **changes):
        state = self.units[uid]
        before = {key: (key in state, state.get(key)) for key in changes}
        state.update(changes)
        self._offered[uid] = (self._signature(order), now, before)

    def _restore(self, uid, before):
        state = self.units.get(uid)
        if state is None:
            return
        for key, (present, value) in before.items():
            if present:
                state[key] = value
            else:
                state.pop(key, None)

    def mark_sent(self, orders, now):
        sent = {(uid, self._signature(order)) for order in orders
                for uid in order.get("units", [])}
        for uid, (signature, proposed_at, before) in self._offered.items():
            if proposed_at != now:
                continue
            if (uid, signature) in sent:
                self._issued[uid] = (signature, now, before)
            else:
                self._restore(uid, before)
        self._offered.clear()

    def mark_failed(self, order, sent_at):
        signature = self._signature(order)
        for uid in order.get("units", []):
            issued = self._issued.get(uid)
            state = self.units.get(uid)
            if (issued and issued[:2] == (signature, sent_at)
                    and state and state.get("command_at") == sent_at):
                self._restore(uid, issued[2])
                self._issued.pop(uid, None)

    def _risk(self, v, unit, point, threats, cover, horizon=8):
        target = {**unit, "x": point[0], "y": point[1]}
        loss = 0.
        for enemy in threats:
            rate = damage_rate(v, enemy, target,
                               at_distance=distance(pos(enemy), point), horizon=2)
            if rate <= 0:
                continue
            support = sum(damage_rate(v, ally, enemy,
                                      at_distance=distance(pos(ally), pos(enemy)))
                          for ally in cover if distance(pos(ally), point) <= 10)
            duration = min(horizon, 1.5 + health(v, enemy) / support) if support > 0 else horizon
            loss += rate * duration
        return loss / max(1., health(v, unit))

    def _distances(self, start):
        if self._map.resources or self._map.origin is None:
            return self._map.distances(start)
        choices = [(start[0] + dx, start[1] + dy) for dx in range(-3, 4)
                   for dy in range(-3, 4) if self._map.clear((start[0] + dx, start[1] + dy))]
        if not choices:
            return {}
        source = min(choices, key=lambda p: (distance(start, p), p))
        distances, pending = {source: 0}, deque([source])
        while pending:
            point = pending.popleft()
            if distances[point] >= 40:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                neighbor = point[0] + dx, point[1] + dy
                if neighbor not in distances and self._map.clear(neighbor):
                    distances[neighbor] = distances[point] + 1
                    pending.append(neighbor)
        return distances

    def _path(self, start, target, paths):
        start, target = tuple(start), tuple(target)
        if self._map.origin is None:
            steps = max(1, int(distance(start, target)))
            return [(round(start[0] + (target[0] - start[0]) * i / steps),
                     round(start[1] + (target[1] - start[1]) * i / steps))
                    for i in range(steps + 1)]
        if target not in paths:
            return []
        route = [target]
        while paths[route[-1]] > 0:
            x, y = route[-1]
            choices = [(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                       if paths.get((x + dx, y + dy)) == paths[route[-1]] - 1]
            if not choices:
                return []
            route.append(min(choices))
        return list(reversed(route))

    def _refuge(self, v, unit, threats, cover, refs, risk):
        start = pos(unit)
        anchors = [pos(b) for b in refs]
        anchors += [pos(b) for b in v.buildings if weapons(v, b) and pos(b)]
        anchors += [pos(a) for a in cover if distance(pos(a), start) <= 14]
        if not anchors and v.base:
            anchors = [v.base]
        paths = self._distances(start)
        candidates = []
        nearest = min(threats, key=lambda e: distance(pos(e), start), default=None)
        for anchor in sorted(set(anchors), key=lambda p: distance(start, p))[:12]:
            offsets = [(0, 0), (-4, 0), (4, 0), (0, -4), (0, 4)]
            if nearest:
                dx, dy = anchor[0] - pos(nearest)[0], anchor[1] - pos(nearest)[1]
                length = max(1., hypot(dx, dy))
                offsets.insert(0, (round(dx * 4 / length), round(dy * 4 / length)))
            for dx, dy in offsets:
                target = v.ground_point((anchor[0] + dx, anchor[1] + dy))
                if target is None or not 2 < distance(start, target) <= 24:
                    continue
                if any(distance(target, pos(b)) < 2 for b in v.buildings):
                    continue
                path = self._path(start, target, paths)
                if not path or len(path) > 36:
                    continue
                ending = self._risk(v, unit, target, threats, cover)
                if ending >= max(.025, risk * .75):
                    continue
                sampled = path[::2] + [path[-1]]
                exposure = [self._risk(v, unit, p, threats, cover) for p in sampled]
                if max(exposure) > max(.25, risk * 1.2):
                    continue
                candidates.append((ending * 100 + len(path) + sum(exposure) * 3,
                                   tuple(target)))
        return list(min(candidates)[1]) if candidates else None

    def _ore(self, v, unit, threats, cover, refs, reserved, delivery_limit=28):
        if not refs or not self._map.resources:
            return None, False
        paths = self._map.distances(pos(unit))
        refinery_paths = [self._map.distances(pos(ref)) for ref in refs]
        candidates = []
        for point in self._map.resources:
            outbound = paths.get(point)
            inbound = min((p.get(point, 10000) for p in refinery_paths), default=10000)
            if outbound is None or outbound > 40 or inbound > delivery_limit:
                continue
            crowding = sum(max(0., 4 - distance(point, used)) for used in reserved)
            candidates.append((outbound + inbound * 1.8 + crowding * 3, point))
        cells = set()
        blocked = False
        for _, point in sorted(candidates):
            cell = (point[0] // 3, point[1] // 3)
            if cell in cells:
                continue
            cells.add(cell)
            if len(cells) > 64:
                break
            route = self._path(pos(unit), point, paths)
            if any(self._risk(v, unit, p, threats, cover) >= .18
                   for p in route[::2] + [point]):
                blocked = True
                continue
            ref_index = min(range(len(refs)), key=lambda i: refinery_paths[i].get(point, 10000))
            delivery = self._path(pos(refs[ref_index]), point, refinery_paths[ref_index])
            if any(self._risk(v, unit, p, threats, cover) >= .18
                   for p in delivery[::2] + [point]):
                blocked = True
                continue
            return list(point), False
        return None, blocked

    def _delivering(self, unit, refs):
        activity = str(unit.get("act", unit.get("activity", unit.get("state", "")))).lower()
        if activity != "findanddeliverresources" and any(
                word in activity for word in ("unload", "deliver", "return", "dock")):
            return True
        if any(number(unit.get(key)) > 0 for key in ("cargo", "carried_resources", "ore", "load")):
            return True
        return not unit.get("idle") and any(distance(pos(unit), pos(ref)) < 3 for ref in refs)

    def propose(self, v, macro_map):
        self._map = macro_map
        self._offered = {}
        harvesters = [u for u in v.units if u.get("type") == "harv" and pos(u)]
        live = {u["id"] for u in harvesters}
        self.units = {uid: state for uid, state in self.units.items()
                      if uid in live and state["seen"] <= v.now}
        self._issued = {uid: issued for uid, issued in self._issued.items()
                        if uid in self.units and issued[1] <= v.now}
        refs = [b for b in v.buildings if b.get("type") == "proc" and pos(b)]
        threats = [e for e in v.enemies + v.enemy_buildings if pos(e) and weapons(v, e)]
        cover = [a for a in v.units + v.buildings if pos(a) and weapons(v, a)]
        reserved = [state["target"] for state in self.units.values()
                    if state.get("target") and v.now - state.get("restored_at", 0) < 20]
        reserved += [pos(u) for u in harvesters if not u.get("idle")
                     and not self._delivering(u, refs)
                     and any((pos(u)[0] + dx, pos(u)[1] + dy) in self._map.resources
                             for dx in (-1, 0, 1) for dy in (-1, 0, 1))]
        orders = []
        for unit in harvesters:
            uid, hp = unit["id"], number(unit.get("hp"), 100)
            state = self.units.setdefault(uid, {"hp": hp, "seen": v.now,
                "retreat": False, "command_at": -100., "danger_at": -100.,
                "last_damage": -100., "restore_tries": 0})
            elapsed = v.now - state["seen"]
            damage = max(0., state["hp"] - hp)
            if damage > 0:
                state["last_damage"] = v.now
            previous_point = state.get("point")
            state.update(hp=hp, seen=v.now, point=pos(unit))
            risk = self._risk(v, unit, pos(unit), threats, cover)
            dangerous = risk >= .20 or (0 < elapsed <= 8 and damage >= 8)
            if dangerous:
                state.update(retreat=True, danger_at=v.now)
                if v.now - state["command_at"] >= 4:
                    target = self._refuge(v, unit, threats, cover, refs, risk)
                    if target:
                        order = {"cmd": "move", "units": [uid], "to": target}
                        self._offer(uid, order, v.now, command_at=v.now, escape_target=target)
                        orders.append(Intent(order,
                                             priority=97, cooldown=4, key=f"harv-escape:{uid}"))
                continue
            restoring = state["retreat"]
            if restoring and (v.now - state["danger_at"] < 3 or risk >= .10):
                continue
            if self._delivering(unit, refs):
                continue
            outward = False
            if not restoring and not unit.get("idle"):
                nearest = min(refs, key=lambda b: distance(pos(unit), pos(b)), default=None)
                anchor = state.get("outward_anchor")
                if nearest:
                    returning = previous_point and distance(pos(unit), pos(nearest)) < (
                        distance(previous_point, pos(nearest)) - .5)
                    if (anchor is None or anchor[2] != nearest["id"]
                            or not 0 <= v.now - anchor[1] <= 6 or returning):
                        anchor = (pos(unit), v.now, nearest["id"])
                        state["outward_anchor"] = anchor
                outward = bool(nearest and anchor and 0 < v.now - anchor[1] <= 6
                               and not state.get("far_redirected")
                               and distance(pos(unit), pos(nearest)) >= 22
                               and distance(pos(unit), pos(nearest))
                                   >= distance(anchor[0], pos(nearest)) + 2)
                if not outward:
                    continue
            if v.now - state["command_at"] < (4 if restoring else 12):
                continue
            recent = v.now - state.get("restored_at", -100) < 60
            exhausted = recent and state["restore_tries"] >= 2
            target, blocked = self._ore(v, unit, threats, cover, refs, reserved,
                                        18 if outward else 28)
            if blocked:
                continue
            if exhausted:
                target = None
            if outward and target is None:
                continue
            if target is None and threats and self._map.resources:
                local = [p for p, _, _ in self._map.clusters
                         if distance(pos(unit), p) <= 40
                         and any(distance(pos(ref), p) <= 28 for ref in refs)]
                if any(self._risk(v, unit, p, threats, cover) >= .18 for p in local):
                    continue
            order = {"cmd": "harvest", "units": [uid]}
            if target:
                order["to"] = target
                reserved.append(target)
            changes = dict(retreat=False, command_at=v.now, target=target,
                           restored_at=v.now, restore_tries=state["restore_tries"] + 1 if recent else 1,
                           escape_target=None)
            if outward:
                changes["far_redirected"] = True
            self._offer(uid, order, v.now, **changes)
            orders.append(Intent(order, priority=84 if restoring else 82,
                                 cooldown=4, key=f"harvest:{uid}"))
        return orders
