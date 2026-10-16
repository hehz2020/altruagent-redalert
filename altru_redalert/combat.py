from collections import deque
from math import hypot, sqrt
from statistics import median

from .model import Intent, distance, living, number, pos
from .ground_routes import GroundRoutes
from .flanking import FlankPlanner
from .opportunities import RaidOpportunities
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
        self.goal_evaluated = -1000.
        self.goal_signature = None
        self.scored_goal = None
        self.desired = {}
        self.contacts = {}
        self.withdraw_goal = None
        self.raid_ids = set()
        self.raid_until = 0.0
        self.raid_cooldown = 0.0
        self.raid_returning = False
        self.raid_planner = RaidOpportunities()
        self.raid_return_planner = FlankPlanner()
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
        self.defense_posts = {}

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

    def _goal(self, view, center, committed_army=None):
        routes = self._navigation(view)
        army = committed_army or [a for a in view.units if self._combat(view, a)]
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
            signature = (tuple(sorted(_id(b) for b in visible)),
                         tuple(sorted((_id(e), _hp(e) // 20, pos(e)[0] // 8, pos(e)[1] // 8)
                                      for e in view.enemies + view.enemy_buildings
                                      if living(e) and pos(e) is not None)),
                         tuple(sorted((_id(a), _hp(a) // 20) for a in army)),
                         pos(center)[0] // 8, pos(center)[1] // 8)
            if (signature == self.goal_signature and 0 <= view.now - self.goal_evaluated < 1.
                    and any(pos(b) == self.scored_goal for b in visible)):
                return self.scored_goal
            priorities = {"weap": 16, "proc": 14, "fact": 12, "barr": 7, "tent": 7,
                          "powr": 5, "apwr": 7, "dome": 4}
            def rank(building):
                value = distance(center, pos(building)) - priorities.get(_kind(building), 0)
                value += 16 if _kind(building) in GROUND_DEFENSE else 0
                if self.army_goal is not None and distance(pos(building), self.army_goal) <= 3:
                    value -= 5
                return value, _id(building)
            # A nearby factory behind an unbeaten army is not automatically a
            # better objective than an exposed refinery. Keep the search small
            # and let the existing path planner choose the approach.
            candidates = sorted(visible, key=rank)[:6]
            enemies = [e for e in view.enemies + view.enemy_buildings
                       if living(e) and pos(e) is not None]
            evaluated = {}
            def risk_adjusted(building):
                value, uid = rank(building)
                resistance = self._resistance(view, pos(building), enemies, army)
                if resistance:
                    key = tuple(sorted(_id(e) for e in resistance))
                    if key not in evaluated:
                        evaluated[key] = force_ratio(view, army, resistance, horizon=30, projected=True)
                    ratio = evaluated[key]
                    value += min(65., (24. if ratio < 1.1 else 0.)
                                 + max(0., 1.15 - ratio) * 40.)
                return value, uid
            self.scored_goal = pos(min(candidates, key=risk_adjusted))
            self.goal_signature, self.goal_evaluated = signature, view.now
            return self.scored_goal
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

    def _withdraw(self, view, army, enemies, role="retreat", *, destination=None):

        center = _center(army)
        anchored = destination is not None
        if destination is None:
            if self.withdraw_goal is None or view.now >= self.retreat_until:
                self.withdraw_goal = self._fallback(view, center, enemies)
            destination = self.withdraw_goal
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
        orders = self._orders(view, movers, "move", destination, role, 100, interrupt=anchored)
        visible_ids = {_id(e) for e in view.enemies + view.enemy_buildings}
        fire, engaged = self._local_fire(view, trapped,
                                         [e for e in enemies if _id(e) in visible_ids],
                                         role + "-trade", 101)
        orders += fire
        orders += self._orders(view, [a for a in trapped if _id(a) not in engaged],
                               "move", destination, role, 100, interrupt=anchored)
        return orders

    def _defense_refuge(self, view, point, defenders, enemies, previous=None):
        """Stay near the defended home, rather than repeatedly retreating outward."""
        routes = self._navigation(view)
        origin = pos(min(defenders, key=lambda a: distance(pos(a), point)))
        sample = min(defenders, key=lambda a: health(view, a))

        def exposure(cell):
            return sum(damage_rate(view, e, sample, at_distance=distance(pos(e), cell),
                                   horizon=2) for e in enemies)

        def usable(cell):
            return (cell is not None and distance(cell, point) <= 10
                    and (not routes.available or routes.reachable(origin, cell)))

        old = view.ground_point(previous) if previous is not None else None
        if usable(old) and exposure(old) == 0:
            return old
        offsets = ((0, 0), (8, 0), (-8, 0), (0, 8), (0, -8),
                   (6, 6), (-6, 6), (6, -6), (-6, -6))
        candidates = [view.ground_point((point[0] + dx, point[1] + dy))
                      for dx, dy in offsets]
        candidates = [cell for cell in candidates if usable(cell)]
        if usable(old):
            candidates.append(old)
        return min(candidates, key=lambda cell: (exposure(cell), distance(origin, cell)),
                   default=view.ground_point(point))

    def _defense(self, view, army, enemies):
        protected = [a for a in view.buildings + view.units
                     if _kind(a) in {"fact", "proc", "weap", "barr", "tent", "harv", "mcv"}
                     and living(a) and pos(a) is not None]
        alive = {_id(a): a for a in army if living(a) and pos(a) is not None}
        assets = {_id(a): a for a in protected}
        self.defense_posts = {
            key: post for key, post in self.defense_posts.items()
            if 0 <= view.now - post["seen"] < 18
            and any(uid in assets and distance(pos(assets[uid]), post["point"]) <= 20
                    for uid in post["assets"])
            and any(uid in alive for uid in post["guards"])
        }
        structures = [a for a in protected if a in view.buildings]
        incidents = []
        for asset in protected:
            attackers = [e for e in enemies if living(e) and pos(e) is not None and
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
        # One raider may threaten a refinery and several miners. Allocate it once,
        # then spend the remaining detachment budget on separate incidents.
        incidents.sort(key=lambda entry: (-entry[0], _id(entry[1])))
        orders, assigned, covered, active_posts = [], set(), set(), set()
        budget = min(6, max(2, (len(army) + 2) // 3))
        detached = 0
        for _, asset, threats, emergency in incidents:
            threat_ids = {_id(e) for e in threats}
            if threat_ids <= covered:
                continue
            threats = [e for e in threats if _id(e) not in covered]
            target = min(threats, key=lambda e: distance(pos(e), pos(asset)))
            local = [e for e in enemies if living(e) and pos(e) is not None
                     and (weapons(view, e) or _kind(e) in {"e6", "thf"})
                     and distance(pos(e), pos(target)) < 11]
            point = self._defense_anchor(asset, structures)
            key = _id(asset)
            previous_key = next((old_key for old_key, post in self.defense_posts.items()
                                 if old_key not in active_posts
                                 and (_id(asset) in post["assets"]
                                      or distance(point, post["point"]) <= 8)), key)
            previous = self.defense_posts.get(previous_key, {})
            recalling = view.now < previous.get("recall_until", 0)
            active_posts.add(key)
            remote = (_kind(asset) == "harv" and
                      min((distance(pos(asset), pos(b)) for b in structures), default=99) > 20)
            shelters = [b for b in view.buildings if living(b) and pos(b) is not None
                        and weapons(view, b) and any(damage_rate(view, b, e,
                            at_distance=distance(pos(b), pos(e))) > 0 for e in local)]
            if (shelters and _hp(asset) >= 80 and force_ratio(view, shelters, local) >= 1.6
                    and all(any(damage_rate(view, b, e,
                                at_distance=distance(pos(b), pos(e))) > 0 for b in shelters) for e in local)):
                self.defense_posts.pop(key, None)
                self.defense_posts.pop(previous_key, None)
                covered.update(threat_ids)
                continue
            candidates = [a for a in army if _id(a) not in assigned and living(a)
                          and pos(a) is not None and any(damage_rate(view, a, e) > 0 for e in local)
                          and (emergency or (recalling and _id(a) in previous.get("guards", ()))
                               or distance(pos(a), pos(asset)) <= (22 if remote else 30))]
            candidates.sort(key=lambda a: distance(pos(a), pos(target)) / max(.4, speed(view, a))
                            + min((health(view, e) / max(1., damage_rate(view, a, e))
                                   for e in local if damage_rate(view, a, e) > 0), default=1000) * .1
                            - (3 if _id(a) in previous.get("guards", ()) else 0))
            cap = len(candidates) if emergency or recalling else min(3 if remote else 6, max(0, budget - detached))
            defenders = []
            for a in candidates[:cap]:
                defenders.append(a)
                if force_ratio(view, defenders + shelters, local, horizon=16) >= 1.35:
                    break
            if recalling:
                chosen = {_id(a) for a in defenders}
                # A projected engagement score from the leading unit is not
                # proof that the rescue has arrived. Keep its travelling peers
                # reserved until they reach home or the bounded lease expires.
                defenders += [a for a in candidates if _id(a) in previous.get("guards", ())
                              and _id(a) not in chosen and distance(pos(a), point) > 18]
            if not defenders:
                continue
            ids = {_id(a) for a in defenders}
            assigned.update(ids)
            detached += len(ids) if not (emergency or recalling) else 0
            covered.update(threat_ids)
            # A large rescue force must not become a permanent garrison. Only a
            # couple of nearby escorts remain briefly after contact disappears.
            nearby = sorted((a for a in defenders if distance(pos(a), point) <= 18),
                            key=lambda a: distance(pos(a), point))[:2]
            if previous_key != key:
                self.defense_posts.pop(previous_key, None)
            self.defense_posts[key] = {
                **previous,
                "point": point, "seen": view.now, "guards": ids,
                "hold": {_id(a) for a in nearby},
                "assets": {_id(a) for a in protected if distance(pos(a), point) <= 14},
                # Only a fresh major threat renews the distant rescue. A small
                # scout or a fog observation cannot pin the whole army forever.
                "recall_until": view.now + 12 if emergency else previous.get("recall_until", 0),
            }
            center = _center(defenders)
            ratio = force_ratio(view, defenders + shelters, local)
            role = f"defense-{key}"
            post = self.defense_posts[key]
            recovery_ratio = (force_ratio(view, defenders + shelters, local,
                                           horizon=16, projected=True)
                              if previous.get("withdraw_goal") is not None else ratio)
            withdrawing = (view.now < previous.get("withdraw_until", 0)
                           or (previous.get("withdraw_goal") is not None and recovery_ratio < 1.05))
            if withdrawing or (ratio < .65 and any(
                    distance(pos(a), pos(e)) < 9 for a in defenders for e in local)):
                if recovery_ratio < .95:
                    post["withdraw_until"] = view.now + 6
                refuge = min(shelters, key=lambda b: distance(pos(b), center), default=None)
                if refuge is not None:
                    orders += self._orders(view, defenders, "attack_move", pos(refuge), role + "-cover", 97)
                else:
                    hazards = [e for e in enemies if weapons(view, e)
                               and (distance(pos(e), point) <= 24 or any(
                                   distance(pos(e), pos(a)) <= 12 for a in defenders))]
                    post["withdraw_goal"] = self._defense_refuge(
                        view, point, defenders, hazards, previous.get("withdraw_goal"))
                    orders += self._withdraw(view, defenders, hazards, role + "-withdraw",
                                             destination=post["withdraw_goal"])
                self.defense_posts[key]["hold"] = set()
                continue
            post.pop("withdraw_goal", None)
            post.pop("withdraw_until", None)
            # Only shoot visible targets near the protected asset. A retreating
            # raider crossing this leash gets no fresh chase order next cycle.
            leash = max(12., min(18., max(weapon_range(view, e, asset) + 3. for e in threats)))
            targets = [e for e in local if distance(pos(e), pos(asset)) <= leash]
            fire, engaged = self._local_fire(view, [a for a in defenders if _kind(a) not in ARTILLERY],
                                            targets, role + "-fire", 96)
            guns, gun_ids = self._support(view, defenders, pos(target), targets)
            orders += fire + guns
            orders += self._orders(view, [a for a in defenders if _id(a) not in engaged | gun_ids],
                                   "attack_move", pos(target), role, 95)
        # Keep a small screen on the mine road through short fog/raid gaps. Move
        # back to our asset, never attack-move toward a last-seen enemy in fog.
        hold_budget = min(4, max(1, len(army) // 4), max(0, budget - len(assigned)))
        for key, post in sorted(self.defense_posts.items(), key=lambda item: -item[1]["seen"]):
            withdrawing = view.now < post.get("withdraw_until", 0)
            recalling = view.now < post.get("recall_until", 0)
            continuing = recalling or withdrawing
            if key in active_posts or (hold_budget <= 0 and not continuing):
                continue
            guards = [alive[uid] for uid in post["guards"] if uid in alive and uid not in assigned
                      and (continuing or uid in post["hold"])]
            guards.sort(key=lambda a: distance(pos(a), post["point"]))
            if not continuing:
                guards = guards[:min(2, hold_budget)]
            if not guards:
                continue
            assigned.update(_id(a) for a in guards)
            if not continuing:
                hold_budget -= len(guards)
            point = post.get("withdraw_goal", post["point"]) if withdrawing else post["point"]
            orders += self._orders(view, guards, "move", point, f"defense-hold-{key}",
                                   95, arrival=2.5, interrupt=True)
        return orders, assigned

    def _defense_anchor(self, asset, structures):
        """A short mine-road guard position, independent of an enemy's retreat."""
        point = pos(asset)
        if _kind(asset) != "harv":
            return point
        refinery = min((b for b in structures if _kind(b) == "proc"),
                       key=lambda b: distance(pos(b), point), default=None)
        if refinery is None or distance(pos(refinery), point) > 20:
            return point
        home = pos(refinery)
        return (point[0] * .7 + home[0] * .3, point[1] * .7 + home[1] * .3)

    def _raid(self, view, army, enemies):
        active = [a for a in army if _id(a) in self.raid_ids]
        main = [a for a in army if _id(a) not in self.raid_ids]
        if (self.raid_returning or (active and view.now >= self.raid_until)
                or len(army) < 14 or any(distance(pos(e), _center(main or army)) < 12
                                       and weapons(view, e) for e in enemies)):
            return self._recall_raid(view, army)
        if view.now < self.raid_cooldown:
            return [], set()
        fast = [a for a in army if _kind(a) in {"1tnk", "2tnk", "3tnk", "stnk", "ctnk"}
                and _hp(a) >= 70]
        if len(fast) < 5:
            return self._recall_raid(view, army)
        raiders = sorted(fast, key=lambda a: (_id(a) not in self.raid_ids,
                                              distance(pos(a), _center(fast)), _id(a)))[:3]
        raid_ids = {_id(a) for a in raiders}
        remainder = [a for a in army if _id(a) not in raid_ids]
        center = _center(remainder)
        threats = self._nearby_threats(view, enemies, center)
        if threats:
            line = [a for a in remainder if distance(pos(a), center) < 15]
            cover = [b for b in view.buildings if _kind(b) in GROUND_DEFENSE
                     and b.get("powered", True) and distance(pos(b), center) < 10]
            if force_ratio(view, line + cover, threats, horizon=16) < 1.25:
                return self._recall_raid(view, army)
        choice = self.raid_planner.choose(view, raiders, self.contacts,
                                          routes=self._navigation(view))
        if choice is None:
            return self._recall_raid(view, army)
        if not self.raid_ids:
            self.raid_until = view.now + 45.
        self.raid_ids = {_id(a) for a in raiders}
        orders, firing = self._local_fire(view, raiders, [choice.target], "raid-fire", 75)
        orders += self._orders(view, [a for a in raiders if _id(a) not in firing],
                               "move", choice.waypoint, "raid", 55, arrival=.75)
        return orders, self.raid_ids

    def _recall_raid(self, view, army):
        raiders = [a for a in army if _id(a) in self.raid_ids]
        main = [a for a in army if _id(a) not in self.raid_ids]
        destination = _center(main) if main else view.base
        if not raiders or destination is None or all(
                distance(pos(a), destination) < 7 for a in raiders):
            if self.raid_ids:
                self.raid_cooldown = view.now + 12.
            self.raid_ids.clear()
            self.raid_returning = False
            return [], set()
        self.raid_returning = True
        routes = self._navigation(view)
        origin = self._body_origin(raiders, destination)
        point = self.raid_return_planner.waypoint(view, routes, raiders, origin,
                                                 destination, self.contacts, step=6.)
        point = point or (list(origin) if routes.available else view.ground_point(destination))
        return (self._orders(view, raiders, "move", point, "raid-recall", 93,
                             arrival=.75, interrupt=True), {_id(a) for a in raiders})

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

    def _nearby_threats(self, view, enemies, center):
        """Fog is uncertainty, not proof of destruction; never target old ids."""
        known = {_id(e): e for e in enemies if weapons(view, e)}
        for uid, (enemy, seen, building) in self.contacts.items():
            if (uid not in known and weapons(view, enemy)
                    and view.now - seen < (45. if building else 8.)):
                known[uid] = enemy
        return [e for e in known.values() if distance(pos(e), center) < 17]

    def _protect_lead(self, view):
        # Only use an explicit kill-cost lead, never assume an asset-value tie
        # is won. Re-evaluate every observation so a lost lead resumes pressure.
        military = view.military
        if "kills_cost" not in military or "deaths_cost" not in military:
            return False
        return (view.remaining <= 90 and
                number(military["kills_cost"]) - number(military["deaths_cost"]) >= 1500)

    def _consolidate(self, view, army, enemies):
        """Replace existing outward orders as well as stopping new attacks."""
        center = _center(army)
        strongholds = [b for b in view.buildings if pos(b) is not None
                       and _kind(b) in GROUND_DEFENSE | {"fact", "proc", "weap"}
                       and b.get("powered", True)]
        routes = self._navigation(view)
        origin = self._body_origin(army, view.base or center)
        strongholds = [b for b in strongholds if not routes.available
                      or routes.reachable(origin, pos(b))]
        shelter = min(strongholds, key=lambda b: distance(pos(b), center)
                      + (0 if _kind(b) in GROUND_DEFENSE else 6), default=None)
        destination = pos(shelter) if shelter is not None else view.base
        if destination is None:
            destination = center
        if routes.available:
            point = self.flank_planner.waypoint(view, routes, army, origin,
                                                destination, self.contacts, step=6.) or list(origin)
        else:
            point = view.ground_point(destination)
        # In established cover, keep shooting enemies already in range. Away
        # from cover, a move order breaks old attack-target pursuits immediately.
        covered = distance(center, destination) <= 8
        close = [e for e in enemies if weapons(view, e) and distance(pos(e), center) < 12]
        if covered and (not close or force_ratio(view, army, close) >= 1.1):
            fire, engaged = self._local_fire(view, army, enemies, "hold-fire", 96)
        else:
            fire, engaged = [], set()
        return fire + self._orders(view, [a for a in army if _id(a) not in engaged],
                                   "move", point, "protect-lead", 94,
                                   arrival=.75, interrupt=True)

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
        protecting = self._protect_lead(view)
        # Assign home duties first, including continuing rescues. Scouting must
        # not take a defender away before the defense allocator can reserve it.
        orders, defending = self._defense(view, army, enemies)
        main = [a for a in army if _id(a) not in defending]
        if not main:
            self._set_mode("defend", view.now)
            return orders
        scouts, scout_id = (([], None) if protecting or self.scout_id in defending
                           else self._scout(view, main, enemies))
        orders += scouts
        main = [a for a in main if _id(a) != scout_id]
        if not main:
            return orders
        if protecting:
            self.raid_ids.clear()
            self.commit_until = self.assault_until = 0.
            self._set_mode("protect-lead", view.now)
            return orders + self._consolidate(view, main, enemies)
        raids, raiding = self._raid(view, main, enemies)
        orders += raids
        main = [a for a in main if _id(a) not in raiding]
        center = _center(main)
        goal = self._goal(view, center, main)
        nearby = self._nearby_threats(view, enemies, center)
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
            visible_ids = {_id(e) for e in enemies}
            fresh = [e for e in nearby if _id(e) in visible_ids]
            fresh_danger = bool(fresh) and force_ratio(view, local + support, fresh) < .8
            seen_at = view.now if fresh_danger else max(
                (self.contacts[_id(e)][1] for e in nearby
                 if _id(e) not in visible_ids and _id(e) in self.contacts), default=view.now)
            # Old sightings can preserve a retreat, not keep renewing it forever.
            deadline = seen_at + 9
            for enemy in nearby:
                remembered = self.contacts.get(_id(enemy))
                if _id(enemy) not in visible_ids and remembered and remembered[2]:
                    # Static guns have not walked away. Entering their remembered
                    # range is new danger even when the sighting is older than 9s.
                    deadline = max(deadline, min(view.now + 9, remembered[1] + 45))
            self.retreat_until = max(self.retreat_until, deadline)
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
