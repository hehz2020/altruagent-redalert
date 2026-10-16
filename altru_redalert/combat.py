from collections import deque
from math import hypot, sqrt
from statistics import median

from .model import Intent, distance, living, pos
from .ground_routes import GroundRoutes
from .flanking import FlankPlanner
from .tactics import (ARTILLERY, damage_rate, force_ratio, health, speed,
                     target_score, weapon_range, weapons)


GROUND = {
    "e1", "e2", "e3", "e4", "e7", "shok", "dog", "jeep", "ftrk", "apc",
    "1tnk", "2tnk", "3tnk", "4tnk", "ttnk", "stnk", "ctnk", "arty", "v2rl",
}
NONCOMBAT = {
    "mcv", "harv", "e6", "medi", "mech", "spy", "thf", "mnly", "mgg",
    "dtrk", "lst", "ss", "msub", "dd", "ca", "pt", "mig", "yak", "heli",
    "hind", "mh60", "u2", "badr", "badr.bomber",
}
GROUND_DEFENSE = {"pbox", "hbox", "gun", "ftur", "tsla"}
AIR = {"mig", "yak", "heli", "hind", "mh60", "u2", "badr", "badr.bomber"}
MOBILE_FIRE = {"1tnk", "2tnk", "3tnk", "4tnk", "jeep", "ftrk", "stnk"}
OPENING_ARMOR_TARGET = 3
OPENING_ARMOR_DEADLINE = 360


def _kind(actor):
    return str(actor.get("type", "")).lower()


def _id(actor):
    value = actor.get("id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _hp(actor):
    try:
        return max(0.0, min(100.0, float(actor.get("hp", 100))))
    except (TypeError, ValueError):
        return 100.0


def _center(actors):
    points = [pos(a) for a in actors if pos(a) is not None]
    if not points:
        return None
    return (median(p[0] for p in points), median(p[1] for p in points))


class Military:


    def __init__(self):
        self.mode = "regroup"
        self.mode_since = 0.0
        self.retreat_until = 0.0
        self.scout_id = None
        self.scout_until = 0.0
        self.scout_goal = None
        self.scout_started = 0.0
        self.scout_index = 0
        self.scout_losses = 0
        self.memories = {}
        self.visited = {}
        self.sweep = []
        self.sweep_map = None
        self.sweep_layout = None
        self.army_goal = None
        self.goal_since = 0.0
        self.desired = {}
        self.contacts = {}
        self.withdraw_goal = None
        self.raid_ids = set()
        self.raid_until = 0.0
        self.commit_until = 0.0
        self.last_ratio = None
        self.march_goal = None
        self.march_destination = None
        self.march_updated = 0.
        self.ground_routes = None
        self.flank_planner = FlankPlanner()
        self.assault_goal = None
        self.assault_until = 0.
        self.assault_health = 0.
        self.assault_ratio = None

    def _combat(self, view, actor):
        kind = _kind(actor)
        if not living(actor) or _id(actor) is None or pos(actor) is None:
            return False
        if kind in NONCOMBAT or kind.endswith("husk"):
            return False
        if kind in GROUND:
            return True
        spec = view.spec(kind)
        return (view.queue(kind) in {"Infantry", "Vehicle"}
                and bool(spec.get("weapon")))

    def _value(self, view, actor, structure=False):
        kind = _kind(actor)
        fallback = 150 if kind.startswith("e") or kind == "dog" else 700
        value = (view.cost(kind) or fallback) * sqrt(max(0.15, _hp(actor) / 100))
        if structure:
            return value * (2.2 if kind == "tsla" else 1.6) if kind in GROUND_DEFENSE else 0
        if kind in {"harv", "mcv", "e6", "medi", "mech", "spy", "thf", "u2"}:
            return 0
        return value * (1.15 if kind in AIR else 1.0)

    def _strength(self, view, actors, point, radius=14):
        return sum(self._value(view, a, a in view.enemy_buildings)
                   for a in actors if pos(a) is not None and distance(pos(a), point) <= radius)

    def _set_mode(self, mode, now):
        if mode != self.mode:
            self.mode, self.mode_since = mode, now

    def mark_sent(self, orders, now):

        for order in orders:
            if order.get("cmd") == "attack" and "target" in order:
                signature = ("attack", order["target"])
            elif order.get("cmd") in {"move", "attack_move"} and "to" in order:
                signature = (order["cmd"], tuple(order["to"]))
            else:
                continue
            for uid in order.get("units", []):
                self.desired[uid] = (signature, now)

    def _orders(self, view, actors, cmd, point, role, priority=40, *, arrival=2.5,
                interrupt=False):
        target = view.ground_point(point) if point is not None else None
        if target is None:
            return []
        selected = []
        signature = (cmd, tuple(target))
        for actor in actors:
            uid = _id(actor)
            if uid is None or not living(actor):
                continue
            old = self.desired.get(uid)
            at_goal = pos(actor) is not None and distance(pos(actor), target) < arrival
            due = (old is None or old[0] != signature
                   or view.now - old[1] >= 18
                   or (actor.get("idle") and view.now - old[1] >= 3))
            replacing = interrupt and (old is None or old[0] != signature)
            if due and (not at_goal or cmd != "move" or replacing):
                selected.append(uid)
        return [Intent({"cmd": cmd, "units": selected[i:i + 50], "to": target},
                       priority=priority, cooldown=2.5,
                       key=f"military:{role}:{i // 50}")
                for i in range(0, len(selected), 50)]

    def _fallback(self, view, origin, enemies):
        nearest = min(enemies, key=lambda a: distance(pos(a), origin), default=None)
        threat = pos(nearest) if nearest else None
        if view.base is not None and distance(origin, view.base) > 8:
            if threat is None or distance(threat, view.base) > distance(threat, origin):
                return view.base
        if threat is not None:
            dx, dy = origin[0] - threat[0], origin[1] - threat[1]
            scale = 10 / max(1.0, hypot(dx, dy))
            return (origin[0] + dx * scale, origin[1] + dy * scale)
        return view.base or origin

    def _prepare_sweep(self, view):
        layout = view.map_info.get("layout", {})
        rows = layout.get("rows", []) if isinstance(layout, dict) else []
        origin = layout.get("origin", view.bounds[:2] if view.bounds else []) if isinstance(layout, dict) else []
        rows = rows if isinstance(rows, (list, tuple)) else []
        origin = origin if isinstance(origin, (list, tuple)) else []
        layout_signature = (view.bounds, tuple(origin), tuple(rows))
        if (self.sweep_map == view.map_id and self.sweep
                and self.sweep_layout == layout_signature):
            return
        self.sweep_map = view.map_id
        self.sweep_layout = layout_signature
        if not view.bounds:
            return
        x, y, w, h = view.bounds
        candidates = [(x + w * fx, y + h * fy)
                      for fy in (0.15, 0.38, 0.62, 0.85)
                      for fx in (0.15, 0.38, 0.62, 0.85)]
        reachable = None
        if rows and view.base is not None and isinstance(origin, (list, tuple)) and len(origin) == 2:
            passable = {(origin[0] + j, origin[1] + i)
                        for i, row in enumerate(rows) for j, char in enumerate(row)
                        if char in ".,=_$*S"}
            start = min(passable, key=lambda p: distance(p, view.base), default=None)
            if start is not None:
                reachable, queue = {start}, deque([start])
                while queue:
                    a, b = queue.popleft()
                    for cell in ((a + 1, b), (a - 1, b), (a, b + 1), (a, b - 1)):
                        if cell in passable and cell not in reachable:
                            reachable.add(cell)
                            queue.append(cell)
        self.sweep = []
        for candidate in candidates:
            point = view.ground_point(candidate)
            if reachable:
                point = min(reachable, key=lambda p: distance(p, candidate))
            if point is not None and tuple(point) not in self.sweep:
                self.sweep.append(tuple(point))
        if view.enemy_base is not None:
            self.sweep.sort(key=lambda p: distance(p, view.enemy_base))

    def _remember(self, view, army):
        current = {_id(e) for e in view.enemies + view.enemy_buildings}
        for e in view.enemies + view.enemy_buildings:
            if living(e) and pos(e) is not None:
                self.contacts[_id(e)] = (dict(e), view.now, e in view.enemy_buildings)
        for uid, (actor, seen, building) in list(self.contacts.items()):
            ttl = 180 if building else 25
            inspected = any(distance(pos(a), pos(actor)) < 3 for a in army)
            if view.now - seen > ttl or (uid not in current and inspected):
                del self.contacts[uid]
        for building in view.enemy_buildings:
            if living(building) and pos(building) is not None and _id(building) is not None:
                self.memories[_id(building)] = (pos(building), view.now)
        visible = {_id(b) for b in view.enemy_buildings}
        for uid, (point, when) in list(self.memories.items()):
            inspected = any(distance(pos(a), point) < 2 for a in army)
            if view.now - when > 300 or (uid not in visible and inspected):
                del self.memories[uid]
        for point in self.sweep:
            if any(distance(pos(a), point) < 5 for a in army):
                self.visited[point] = view.now

    def _goal(self, view, center):
        routes = self._navigation(view)
        army = [a for a in view.units if self._combat(view, a)]
        origin = pos(min(army, key=lambda a: distance(pos(a), center))) if army else center
        def accessible(point, target=None):
            if not routes.available or origin not in routes.cells:
                return True
            landing = routes.waypoint(origin, point, distance_cells=1e9)
            reach = max((weapon_range(view, a, target) for a in army), default=4.)
            return landing is not None and distance(landing, point) <= max(1., reach)
        visible = [b for b in view.enemy_buildings if living(b) and pos(b) is not None
                   and accessible(pos(b), b)]
        if visible:
            priorities = {"weap": 16, "proc": 14, "fact": 12, "barr": 7, "tent": 7,
                          "powr": 5, "apwr": 7, "dome": 4}
            def rank(building):
                value = distance(center, pos(building)) - priorities.get(_kind(building), 0)
                value += 16 if _kind(building) in GROUND_DEFENSE else 0
                if self.army_goal is not None and distance(pos(building), self.army_goal) <= 3:
                    value -= 5
                return value, _id(building)
            return pos(min(visible, key=rank))
        mcvs = [u for u in view.enemies if living(u) and _kind(u) == "mcv"
                and pos(u) is not None and accessible(pos(u), u)]
        if mcvs:
            return pos(min(mcvs, key=lambda u: distance(center, pos(u))))
        memories = [p for p, _ in self.memories.values() if accessible(p)]
        if memories:
            return min(memories, key=lambda p: distance(center, p))
        if view.enemy_base is not None and accessible(view.enemy_base):
            key = tuple(view.enemy_base)
            if distance(center, key) < 7:
                self.visited[key] = view.now
            if view.now - self.visited.get(key, -10000) > 180:
                return key
        if self.sweep:
            return min(self.sweep, key=lambda p: (self.visited.get(p, -10000), distance(center, p)))
        return view.enemy_base if accessible(view.enemy_base) else None

    def _scout(self, view, army, enemies):
        scout = next((a for a in army if _id(a) == self.scout_id), None)
        if self.scout_id is not None and scout is None:
            self.scout_losses += 1
            self.scout_id = None
            self.scout_until = view.now + 45
        if scout is None and view.now >= self.scout_until and self.scout_losses < 3:
            scout = next((a for a in army if _kind(a) == "e1" and _hp(a) > 65), None)
            self.scout_id = _id(scout) if scout else None
        if scout is None:
            return [], None
        location = pos(scout)
        threats = [e for e in enemies if self._value(view, e, e in view.enemy_buildings) > 0
                   and distance(pos(e), location) < 10]
        if threats:
            self.scout_until = view.now + 16
            self.scout_goal = None
            return self._orders(view, [scout], "move", self._fallback(view, location, threats),
                                "scout-retreat", 100), self.scout_id
        if view.now < self.scout_until:
            return [], self.scout_id
        reached = self.scout_goal is not None and distance(location, self.scout_goal) < 4
        if self.scout_goal is None or reached or view.now - self.scout_started > 35:
            if reached:
                self.visited[tuple(self.scout_goal)] = view.now
            if self.scout_index == 0 and view.enemy_base and view.base:
                dx, dy = view.base[0] - view.enemy_base[0], view.base[1] - view.enemy_base[1]
                norm = max(1.0, hypot(dx, dy))
                self.scout_goal = view.ground_point((view.enemy_base[0] + dx / norm * 12,
                                                     view.enemy_base[1] + dy / norm * 12))
            elif self.sweep:
                self.scout_goal = min(self.sweep, key=lambda p: (self.visited.get(p, -10000),
                                                               distance(location, p)))
            self.scout_started = view.now
            self.scout_index += 1
        return self._orders(view, [scout], "move", self.scout_goal, "scout", 50), self.scout_id

    def _attack_orders(self, view, assignments, role, priority=80):
        groups = {}
        for actor, target in assignments:
            uid, tid = _id(actor), _id(target)
            old = self.desired.get(uid)
            signature = ("attack", tid)
            if (old is None or old[0] != signature or view.now - old[1] >= 12
                    or (actor.get("idle") and view.now - old[1] >= 2)):
                groups.setdefault(tid, []).append(uid)
        return [Intent({"cmd": "attack", "units": ids, "target": tid},
                       priority=priority, cooldown=1.5, key=f"military:{role}:{tid}")
                for tid, ids in sorted(groups.items(), key=lambda pair: -len(pair[1]))[:6]]

    def _local_fire(self, view, army, enemies, role="fire", priority=80):

        assignments, committed, allocated = [], set(), {}
        for actor in sorted(army, key=lambda a: (-weapon_range(view, a), _id(a))):
            candidates = []
            for e in enemies:
                score = target_score(view, actor, e, enemies)
                if score <= 0:
                    continue
                overkill = allocated.get(_id(e), 0) / max(1., health(view, e))
                score /= 1. + max(0., overkill - .8) * 5
                if self.desired.get(_id(actor), (None,))[0] == ("attack", _id(e)):
                    score *= 1.2
                candidates.append((score, -_id(e), e))
            if not candidates:
                continue
            target = max(candidates, key=lambda entry: entry[:2])[2]
            assignments.append((actor, target))
            committed.add(_id(actor))
            allocated[_id(target)] = allocated.get(_id(target), 0) + damage_rate(view, actor, target) * 2.
        intents = self._attack_orders(view, assignments, role, priority)
        emitted = {uid for intent in intents for uid in intent.order["units"]}
        committed = { _id(a) for a, target in assignments if _id(a) in emitted
                      or (self.desired.get(_id(a), (None,))[0] == ("attack", _id(target))
                          and (not a.get("idle", False)
                               or view.now - self.desired[_id(a)][1] < 2)) }
        return intents, committed

    def _withdraw(self, view, army, enemies, role="retreat"):

        center = _center(army)
        if self.withdraw_goal is None or view.now >= self.retreat_until:
            self.withdraw_goal = self._fallback(view, center, enemies)
        movers, trapped = [], []
        shelters = [b for b in view.buildings if _kind(b) in GROUND_DEFENSE
                    and b.get("powered", True) and pos(b) is not None]
        for a in army:
            attackers = [e for e in enemies if damage_rate(view, e, a,
                at_distance=distance(pos(e), pos(a)), horizon=2) > 0]
            close = [e for e in attackers if distance(pos(e), pos(a)) <= weapon_range(view, e, a) + .5]
            refuge = any(distance(pos(a), pos(b)) < 7 for b in shelters)
            faster = not close or speed(view, a) > max(speed(view, e) for e in close) * 1.08
            if faster or refuge or _kind(a) in ARTILLERY or not any(
                    damage_rate(view, a, e, at_distance=distance(pos(a), pos(e))) > 0 for e in close):
                movers.append(a)
            else:
                trapped.append(a)
        orders = self._orders(view, movers, "move", self.withdraw_goal, role, 100)
        fire, engaged = self._local_fire(view, trapped, enemies, role + "-trade", 101)
        orders += fire
        orders += self._orders(view, [a for a in trapped if _id(a) not in engaged],
                               "move", self.withdraw_goal, role, 100)
        return orders

    def _defense(self, view, army, enemies):
        protected = [a for a in view.buildings + view.units
                     if _kind(a) in {"fact", "proc", "weap", "barr", "tent", "harv", "mcv"}
                     and living(a) and pos(a) is not None]
        incidents = []
        for asset in protected:
            attackers = [e for e in enemies if pos(e) is not None and
                         ((_kind(e) in {"e6", "thf"} and _kind(asset) != "harv"
                           and distance(pos(e), pos(asset)) < 6)
                          or (damage_rate(view, e, asset) > 0 and distance(pos(e), pos(asset))
                              <= max(8., weapon_range(view, e, asset) + 3.)))]
            if not attackers:
                continue
            fixed = _kind(asset) in {"fact", "proc", "weap", "barr", "tent"}
            emergency = fixed and (len(attackers) >= 4 or
                sum(self._value(view, e, e in view.enemy_buildings) for e in attackers) >= 2200)
            endangered = max(0., 100. - _hp(asset)) / 20.
            score = (20 if emergency else 0) + (5 if _kind(asset) == "harv" else 3)
            score += endangered + min(8, len(attackers))
            score -= min(distance(pos(e), pos(asset)) for e in attackers) * .3
            incidents.append((score, asset, attackers, emergency))
        if not incidents:
            return [], set()
        _, asset, threats, emergency = max(incidents, key=lambda entry: entry[0])
        target = min(threats, key=lambda e: distance(pos(e), pos(asset)))
        local = [e for e in enemies if pos(e) is not None and
                 (weapons(view, e) or _kind(e) in {"e6", "thf"})
                 and distance(pos(e), pos(target)) < 11]
        structures = [b for b in protected if _kind(b) != "harv" and b in view.buildings]
        remote = (_kind(asset) == "harv" and
                  min((distance(pos(asset), pos(b)) for b in structures), default=99) > 20)
        shelters = [b for b in view.buildings if weapons(view, b) and
                    any(damage_rate(view, b, e, at_distance=distance(pos(b), pos(e))) > 0
                        for e in local)]
        if (shelters and _hp(asset) >= 80 and force_ratio(view, shelters, local) >= 1.6
                and all(any(damage_rate(view, b, e,
                            at_distance=distance(pos(b), pos(e))) > 0 for b in shelters) for e in local)):
            return [], set()
        candidates = [a for a in army if any(damage_rate(view, a, e) > 0 for e in local)
                      and (emergency or distance(pos(a), pos(asset)) <= (22 if remote else 30))]
        candidates.sort(key=lambda a: distance(pos(a), pos(target)) / max(.4, speed(view, a))
                        + min((health(view, e) / max(1., damage_rate(view, a, e))
                               for e in local if damage_rate(view, a, e) > 0), default=1000) * .1)
        if not candidates:
            return [], set()
        cap = len(candidates) if emergency else min(3 if remote else 6, max(2, (len(army) + 2) // 3))
        defenders = []
        for a in candidates[:cap]:
            defenders.append(a)
            if force_ratio(view, defenders + shelters, local, horizon=16) >= 1.35:
                break
        ids = {_id(a) for a in defenders}
        center = _center(defenders)
        ratio = force_ratio(view, defenders + shelters, local)
        if ratio < .65 and any(distance(pos(a), pos(e)) < 9 for a in defenders for e in local):
            refuge = min(shelters, key=lambda b: distance(pos(b), center), default=None)
            if refuge is not None:
                return self._orders(view, defenders, "attack_move", pos(refuge),
                                    "defense-cover", 97), ids
            self.withdraw_goal = self._fallback(view, center, local)
            return self._withdraw(view, defenders, local, "defense-withdraw"), ids
        orders, engaged = self._local_fire(view, [a for a in defenders if _kind(a) not in ARTILLERY],
                                          local, "defense-fire", 96)
        guns, gun_ids = self._support(view, defenders, pos(target), local)
        orders += guns
        orders += self._orders(view, [a for a in defenders if _id(a) not in engaged | gun_ids],
                               "attack_move", pos(target), "defense", 95)
        return orders, ids

    def _raid(self, view, army, enemies):
        if len(army) < 14 or any(distance(pos(e), _center(army)) < 12 and weapons(view, e) for e in enemies):
            self.raid_ids.clear()
            return [], set()
        fast = [a for a in army if _kind(a) in {"1tnk", "2tnk", "3tnk", "stnk", "ctnk"}
                and _hp(a) >= 70]
        if len(fast) < 5:
            return [], set()
        targets = [e for e in enemies if _kind(e) in {"harv", "e6", "mcv"}]
        for target in sorted(targets, key=lambda e: distance(pos(e), _center(fast))):
            guards = [e for e in enemies if e is not target and weapons(view, e)
                      and distance(pos(e), pos(target)) < 13]
            if any(_kind(e) in GROUND_DEFENSE for e in guards):
                continue
            raiders = sorted(fast, key=lambda a: (_id(a) not in self.raid_ids,
                                                  distance(pos(a), pos(target))))[:3]
            if guards and force_ratio(view, raiders, guards, horizon=18) < 1.7:
                continue
            self.raid_ids = {_id(a) for a in raiders}
            orders, firing = self._local_fire(view, raiders, [target] + guards, "raid-fire", 75)
            orders += self._orders(view, [a for a in raiders if _id(a) not in firing],
                                   "attack_move", pos(target), "raid", 55)
            return orders, self.raid_ids
        self.raid_ids.clear()
        return [], set()

    def _siege_position(self, view, gun, enemies):

        visible_buildings = {_id(b) for b in view.enemy_buildings}
        targets = [e for e in enemies if _id(e) in visible_buildings
                   and damage_rate(view, gun, e) > 0]
        for target in sorted(targets, key=lambda e: distance(pos(gun), pos(e))):
            if distance(pos(gun), pos(target)) > weapon_range(view, gun, target) + 12:
                continue
            dx, dy = pos(gun)[0] - pos(target)[0], pos(gun)[1] - pos(target)[1]
            norm = hypot(dx, dy)
            if norm < 1:
                continue
            radius = weapon_range(view, gun, target) - .75
            point = view.ground_point((round(pos(target)[0] + radius * dx / norm),
                                       round(pos(target)[1] + radius * dy / norm)))
            if point is None or damage_rate(view, gun, target,
                    at_distance=distance(point, pos(target))) <= 0:
                continue
            if any(damage_rate(view, e, gun) > 0
                   and distance(pos(e), point) <= weapon_range(view, e, gun) + 1.
                   for e in enemies):
                continue
            return point
        return None

    def _support(self, view, army, goal, enemies):
        artillery = [a for a in army if _kind(a) in ARTILLERY]
        if not artillery:
            return [], set()
        front = [a for a in army if _kind(a) not in ARTILLERY]
        center = _center(front or army)
        orders, sheltered = [], []
        withdrawing = set()
        for a in artillery:
            nearby = [e for e in enemies if weapons(view, e) and distance(pos(e), pos(a)) < 7]
            screened = all(any(distance(pos(f), pos(e)) + 1 < distance(pos(a), pos(e))
                               and distance(pos(f), pos(a)) < 8 for f in front) for e in nearby)
            if nearby and (not screened or any(distance(pos(a), pos(e)) < 4 for e in nearby)):
                orders += self._orders(view, [a], "move", self._fallback(view, pos(a), nearby),
                                       f"gun-retreat-{_id(a)}", 99)
                withdrawing.add(_id(a))
            else:
                sheltered.append(a)
        firing, engaged = self._local_fire(view, sheltered, enemies, "artillery", 85)
        orders += firing
        for a in artillery:
            if _id(a) in engaged | withdrawing:
                continue
            firing_point = self._siege_position(view, a, enemies)
            if firing_point is not None:
                orders += self._orders(view, [a], "attack_move", firing_point,
                                       f"gun-siege-{_id(a)}", 50)
                continue
            dx, dy = goal[0] - center[0], goal[1] - center[1]
            norm = max(1., hypot(dx, dy))
            rear = (center[0] - 4 * dx / norm, center[1] - 4 * dy / norm)
            orders += self._orders(view, [a], "attack_move", rear, f"gun-support-{_id(a)}", 50)
        return orders, {_id(a) for a in artillery}

    def _body_center(self, army, goal):

        infantry = [a for a in army if _kind(a) in {"e1", "e2", "e3", "e4", "shok", "e7"}]
        pool = infantry if len(infantry) >= 4 else [a for a in army if _kind(a) not in ARTILLERY]
        if not pool:
            pool = army
        seed = max(pool, key=lambda a: (sum(distance(pos(a), pos(b)) <= 8 for b in pool),
                                        -distance(pos(a), goal), -_id(a)))
        return _center([a for a in pool if distance(pos(a), pos(seed)) <= 8])

    def _navigation(self, view):
        if self.ground_routes is None or not self.ground_routes.matches(view):
            self.ground_routes = GroundRoutes(view)
            self.march_goal = None
        return self.ground_routes

    def _body_origin(self, army, goal):

        center = self._body_center(army, goal)
        body = [a for a in army if _kind(a) not in ARTILLERY] or army
        return pos(min(body, key=lambda a: (distance(pos(a), center), _id(a))))

    def _march_point(self, view, army, goal, step=6.):
        origin = self._body_origin(army, goal)
        routes = self._navigation(view)
        if routes.available:
            return (self.flank_planner.waypoint(view, routes, army, origin, goal,
                                               self.contacts, step=step) or list(origin))
        dx, dy = goal[0] - origin[0], goal[1] - origin[1]
        norm = max(1., hypot(dx, dy))
        scale = min(step, norm) / norm
        return view.ground_point((round(origin[0] + scale * dx),
                                  round(origin[1] + scale * dy)))

    def _cohesive_advance(self, view, army, movable, goal):

        self._navigation(view)
        center = self._body_center(army, goal)
        if (self.march_goal is None or self.march_destination is None
                or distance(goal, self.march_destination) > 6
                or distance(center, self.march_goal) < 2.5
                or view.now - self.march_updated >= 4):
            self.march_goal = self._march_point(view, army, goal)
            self.march_destination = tuple(goal)
            self.march_updated = view.now
        return self._orders(view, movable, "attack_move", self.march_goal, "pressure", 40)

    def _screen_skirmish(self, view, army, enemies, goal):

        if not army:
            return [], set()
        center = self._body_center(army, goal)
        dx, dy = goal[0] - center[0], goal[1] - center[1]
        norm = max(1., hypot(dx, dy))
        direction = (dx / norm, dy / norm)
        returners, kites = [], []
        for a in army:
            if _kind(a) not in MOBILE_FIRE:
                continue
            attackers = [e for e in enemies if damage_rate(view, e, a) > 0
                         and distance(pos(a), pos(e)) <= weapon_range(view, e, a) + 3]
            if not attackers:
                continue
            lead = ((pos(a)[0] - center[0]) * direction[0]
                    + (pos(a)[1] - center[1]) * direction[1])
            screen = [b for b in army if b is not a and _kind(b) not in ARTILLERY
                      and distance(pos(a), pos(b)) <= 7]
            if len(army) >= 5 and lead > 7 and len(screen) < 3:
                returners.append(a)
                continue
            close = [e for e in attackers
                     if distance(pos(a), pos(e)) <= weapon_range(view, e, a) + .5
                     and weapon_range(view, a, e) >= weapon_range(view, e, a) + .8
                     and speed(view, a) >= speed(view, e) * 1.15]
            if not close:
                continue
            threat = min(close, key=lambda e: distance(pos(a), pos(e)))
            ax, ay = pos(a)[0] - pos(threat)[0], pos(a)[1] - pos(threat)[1]
            length = max(1., hypot(ax, ay))
            desired_range = weapon_range(view, a, threat) - .25
            point = view.ground_point((round(pos(threat)[0] + desired_range * ax / length),
                                       round(pos(threat)[1] + desired_range * ay / length)))
            if point is None or distance(point, pos(a)) < 1:
                continue
            routes = self._navigation(view)
            if routes.available and not routes.reachable(pos(a), point):
                continue
            if any(distance(point, pos(e)) + .25 < distance(pos(a), pos(e)) for e in attackers):
                continue
            if distance(point, center) > max(10., distance(pos(a), center) + 1):
                continue
            kites.append((a, point))
        rally = self._march_point(view, army, goal, step=2.)
        routes = self._navigation(view)
        returners = [a for a in returners if not routes.available
                     or routes.reachable(pos(a), rally)]
        orders = self._orders(view, returners, "move", rally,
                              "screen-return", 91)
        reserved = {_id(a) for a in returners}
        for a, point in sorted(kites, key=lambda pair: (_hp(pair[0]), _id(pair[0])))[:4]:
            orders += self._orders(view, [a], "move", point, f"kite-{_id(a)}", 90, arrival=.75)
            reserved.add(_id(a))
        return orders, reserved

    def _resistance(self, view, goal, enemies, army):
        resistance = [e for e in enemies if weapons(view, e) and distance(pos(e), goal) < 12]
        visible_ids = {_id(e) for e in enemies}
        resistance += [e for uid, (e, seen, building) in self.contacts.items()
                       if uid not in visible_ids and weapons(view, e)
                       and view.now - seen < (90 if building else 15)
                       and distance(pos(e), goal) < 12]
        center = self._body_center(army, goal)
        line = [a for a in army if _kind(a) not in ARTILLERY] or army
        reach = min(5., max((weapon_range(view, a) for a in line), default=4.))
        dx, dy = center[0] - goal[0], center[1] - goal[1]
        norm = max(1., hypot(dx, dy))
        approach = (goal[0] + reach * dx / norm, goal[1] + reach * dy / norm)
        result = []
        building_ids = {_id(b) for b in view.enemy_buildings}
        building_ids.update(uid for uid, (_, _, building) in self.contacts.items() if building)
        for enemy in resistance:
            if _id(enemy) in building_ids and _kind(enemy) in GROUND_DEFENSE:
                radius = max((weapon_range(view, enemy, a) for a in line), default=0.) + 1.5
                if distance(pos(enemy), center) > radius and distance(pos(enemy), approach) > radius:
                    continue
            result.append(enemy)
        return result

    def _assault_active(self, view, army, goal, enemies):
        if (goal is None or self.assault_goal is None or view.now >= self.assault_until
                or distance(goal, self.assault_goal) > 6):
            return False
        resistance = self._resistance(view, goal, enemies, army)
        ratio = force_ratio(view, army, resistance, horizon=24, projected=True)
        intact = sum(health(view, a) for a in army) >= self.assault_health * .68
        if ratio < .85 or not intact:
            self.assault_until = 0.
            return False
        return True

    def _assault_standoff(self, view, army, goal, enemies):
        resistance = self._resistance(view, goal, enemies, army)
        center = self._body_center(army, goal)
        if distance(center, goal) > 23:
            return None
        ratio = force_ratio(view, army, resistance, horizon=30, projected=True)
        self.assault_ratio = ratio
        active = self._assault_active(view, army, goal, enemies)
        if not resistance or ratio >= 1.1 or active:
            if resistance and ratio >= 1.15 and not active:
                self.assault_goal = tuple(goal)
                self.assault_until = view.now + 18.
                self.assault_health = sum(health(view, a) for a in army)
            return None
        dx, dy = center[0] - goal[0], center[1] - goal[1]
        norm = max(1., hypot(dx, dy))
        radius = 10 if any(_kind(a) in ARTILLERY for a in army) else 15
        point = (round(goal[0] + radius * dx / norm), round(goal[1] + radius * dy / norm))
        routes = self._navigation(view)
        origin = self._body_origin(army, goal)
        if routes.available:
            return routes.waypoint(origin, point, distance_cells=10000) or list(origin)
        return view.ground_point(point)

    def propose(self, view):
        army = [u for u in view.units if self._combat(view, u)]
        if not army:
            return []
        live_ids = {_id(a) for a in army}
        self.desired = {k: v for k, v in self.desired.items() if k in live_ids}
        enemies = [e for e in view.enemies + view.enemy_buildings
                   if living(e) and pos(e) is not None]
        self._prepare_sweep(view)
        self._remember(view, army)
        orders, scout_id = self._scout(view, army, enemies)
        main = [a for a in army if _id(a) != scout_id]
        if not main:
            return orders
        defense, defending = self._defense(view, main, enemies)
        orders += defense
        main = [a for a in main if _id(a) not in defending]
        if not main:
            self._set_mode("defend", view.now)
            return orders
        raids, raiding = self._raid(view, main, enemies)
        orders += raids
        main = [a for a in main if _id(a) not in raiding]
        center = _center(main)
        goal = self._goal(view, center)
        nearby = [e for e in enemies if weapons(view, e) and distance(pos(e), center) < 17]
        local = [a for a in main if distance(pos(a), center) < 15]
        support = [b for b in view.buildings if _kind(b) in GROUND_DEFENSE | {"agun", "sam"}
                   and b.get("powered", True) and distance(pos(b), center) < 10]
        ratio = force_ratio(view, local + support, nearby)
        self.last_ratio = ratio
        assaulting = self._assault_active(view, main, goal, enemies)
        if nearby and ratio < (.68 if assaulting else .8):
            self.assault_until = 0.
            if self.mode != "retreat" or view.now >= self.retreat_until:
                self.withdraw_goal = self._fallback(view, center, nearby)
            self.retreat_until = max(self.retreat_until, view.now + 9)
        if view.now < self.retreat_until:
            self._set_mode("retreat", view.now)
            return orders + self._withdraw(view, main, nearby)
        self.withdraw_goal = None
        weak = [a for a in main if _kind(a) not in {"e1", "e2", "e3", "dog"} and _hp(a) < 25
                and any(distance(pos(a), pos(e)) < 9 for e in nearby)
                and all(speed(view, a) > speed(view, e) * 1.08 for e in nearby
                        if distance(pos(a), pos(e)) <= weapon_range(view, e, a))]
        if weak:
            orders += self._orders(view, weak, "move", self._fallback(view, _center(weak), nearby), "wounded", 100)
            weak_ids = {_id(a) for a in weak}
            main = [a for a in main if _id(a) not in weak_ids]
        if not main:
            return orders
        if goal is None:
            return orders
        total = sum(self._value(view, a) for a in main)
        threshold = 1000 if view.now < 180 else 800
        enough_force = ((total >= threshold and len(main) >= 6)
                        or (total >= 1700 and len(main) >= 3)
                        or (view.now > 360 and len(main) >= 3))
        if view.now < OPENING_ARMOR_DEADLINE and view.has("weap") and view.count("harv") >= 2:
            armor = sum(_kind(a) in {"1tnk", "2tnk", "3tnk", "4tnk"} for a in main)
            enough_force = enough_force and armor >= OPENING_ARMOR_TARGET
        ready = enough_force or view.now < self.commit_until
        standoff = self._assault_standoff(view, main, goal, enemies) if ready else None
        if standoff is not None:
            self._set_mode("standoff", view.now)
            if enough_force:
                self.commit_until = view.now + 20
            line = [a for a in main if _kind(a) not in ARTILLERY]
            orders += self._orders(view, line, "move", standoff, "squad-standoff", 94,
                                   arrival=.75, interrupt=True)
            guns, _ = self._support(view, main, goal, enemies)
            return orders + guns
        skirmish, maneuvering = self._screen_skirmish(view, main, enemies, goal)
        orders += skirmish
        fire, engaged = self._local_fire(view, [a for a in main if _kind(a) not in ARTILLERY
                                               and _id(a) not in maneuvering], enemies)
        orders += fire
        guns, gun_ids = self._support(view, main, goal, enemies)
        orders += guns
        movable = [a for a in main if _id(a) not in engaged | gun_ids | maneuvering]
        if not ready:
            self._set_mode("regroup", view.now)
            origin = view.base or center
            dx, dy = goal[0] - origin[0], goal[1] - origin[1]
            norm = max(1., hypot(dx, dy))
            rally = (origin[0] + 6 * dx / norm, origin[1] + 6 * dy / norm)
            return orders + self._orders(view, movable, "attack_move", rally, "regroup", 40)
        clustered = sum(distance(pos(a), center) < 12 for a in main) >= max(2, len(main) * .65)
        if not clustered and not nearby and (self.mode != "regroup" or view.now - self.mode_since < 12):
            self._set_mode("regroup", view.now)
            return orders + self._orders(view, movable, "attack_move", center, "assemble", 45)
        self._set_mode("pressure", view.now)
        if enough_force:
            self.commit_until = view.now + 20
        if self.army_goal is None or distance(self.army_goal, goal) > 6 or view.now - self.goal_since > 20:
            self.army_goal, self.goal_since = goal, view.now
        return orders + self._cohesive_advance(view, main, movable, self.army_goal)
