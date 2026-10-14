"""Conservative ground-army control using only contestant-visible information.

Cost/health comparisons below are deliberately coarse heuristics, not damage
simulation or a claim about the opponent's hidden army or tiebreak score.
"""

from collections import deque
from math import hypot, sqrt

from .model import Intent, distance, living, pos


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
    return (sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points))


class Military:
    """One cheap scout, a concentrated main force, and interruptible defense.

    Orders retain their goals between observations. New units join existing
    goals; unchanged busy units are left alone. Static map sweeps are restricted
    to an approximate connected ground region where a layout is available.
    """

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
        self.army_goal = None
        self.goal_since = 0.0
        self.desired = {}

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
        # Missing costs affect only this tactical estimate, never spending.
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
        """Record only orders selected for submission by the shared controller.

        ``propose`` is speculative: its intents may lose priority arbitration.
        Root's submission ledger handles rejected/lost orders; idle units also
        naturally retry after three seconds, and busy orders after eight.
        """
        for order in orders:
            if order.get("cmd") not in {"move", "attack_move"} or "to" not in order:
                continue
            signature = (order["cmd"], tuple(order["to"]))
            for uid in order.get("units", []):
                self.desired[uid] = (signature, now)

    def _orders(self, view, actors, cmd, point, role, priority=40):
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
            at_goal = pos(actor) is not None and distance(pos(actor), target) < 2.5
            # Busy units execute a stable order. Refresh only after a generous
            # timeout or a changed tactical goal; idle units retry after 3 s.
            due = (old is None or old[0] != signature
                   or view.now - old[1] >= 8
                   or (actor.get("idle") and view.now - old[1] >= 3))
            if due and (not at_goal or cmd != "move"):
                selected.append(uid)
        return [Intent({"cmd": cmd, "units": selected[i:i + 50], "to": target},
                       priority=priority, cooldown=2.5,
                       key=f"military:{role}:{i // 50}")
                for i in range(0, len(selected), 50)]

    def _fallback(self, view, origin, enemies):
        nearest = min(enemies, key=lambda a: distance(pos(a), origin), default=None)
        threat = pos(nearest) if nearest else None
        if view.base is not None and distance(origin, view.base) > 8:
            # Returning home must not send a unit straight through its pursuer.
            if threat is None or distance(threat, view.base) > distance(threat, origin):
                return view.base
        if threat is not None:
            dx, dy = origin[0] - threat[0], origin[1] - threat[1]
            scale = 10 / max(1.0, hypot(dx, dy))
            return (origin[0] + dx * scale, origin[1] + dy * scale)
        return view.base or origin

    def _prepare_sweep(self, view):
        if self.sweep_map == view.map_id and self.sweep:
            return
        self.sweep_map = view.map_id
        if not view.bounds:
            return
        x, y, w, h = view.bounds
        candidates = [(x + w * fx, y + h * fy)
                      for fy in (0.15, 0.38, 0.62, 0.85)
                      for fx in (0.15, 0.38, 0.62, 0.85)]
        layout = view.map_info.get("layout", {})
        rows = layout.get("rows", []) if isinstance(layout, dict) else []
        origin = layout.get("origin", [x, y]) if isinstance(layout, dict) else [x, y]
        reachable = None
        if rows and view.base is not None and isinstance(origin, (list, tuple)) and len(origin) == 2:
            passable = {(origin[0] + j, origin[1] + i)
                        for i, row in enumerate(rows) for j, char in enumerate(row)
                        if char in ".,$*S"}
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
        visible = [b for b in view.enemy_buildings if living(b) and pos(b) is not None]
        if visible:
            # Valuable production/economy is a destination, but attack-move
            # lets the engine engage local defenders before reaching it.
            return pos(min(visible, key=lambda b: distance(center, pos(b))
                           + (12 if _kind(b) in GROUND_DEFENSE else 0)))
        mcvs = [u for u in view.enemies if living(u) and _kind(u) == "mcv"
                and pos(u) is not None]
        if mcvs:
            # Victory also requires the surviving enemy MCV. Pursue its
            # current visible position before searching old base locations.
            return pos(min(mcvs, key=lambda u: distance(center, pos(u))))
        memories = [p for p, _ in self.memories.values()]
        if memories:
            return min(memories, key=lambda p: distance(center, p))
        if view.enemy_base is not None:
            key = tuple(view.enemy_base)
            if distance(center, key) < 7:
                self.visited[key] = view.now
            if view.now - self.visited.get(key, -10000) > 180:
                return key
        if self.sweep:
            return min(self.sweep, key=lambda p: (self.visited.get(p, -10000), distance(center, p)))
        return view.enemy_base

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
        if len(main) >= 12 and view.base is not None:
            reserves = sorted((a for a in main if _kind(a) in {"e1", "e3"}),
                              key=lambda a: distance(pos(a), view.base))[:2]
            reserve_ids = {_id(a) for a in reserves}
            main = [a for a in main if _id(a) not in reserve_ids]
            refineries = [b for b in view.buildings if _kind(b) == "proc" and pos(b) is not None]
            guard_at = pos(refineries[0]) if refineries else view.base
            orders += self._orders(view, reserves, "attack_move", guard_at, "reserve", 45)
        center = _center(main)
        protected = [pos(a) for a in view.buildings + view.units
                     if living(a) and pos(a) is not None
                     and (a in view.buildings or _kind(a) == "harv")]
        home_threats = [e for e in enemies if self._value(view, e, e in view.enemy_buildings) > 0
                        and any(distance(pos(e), p) < 11 for p in protected)]
        nearby = [e for e in enemies if distance(pos(e), center) < 15]
        local_enemy = self._strength(view, nearby, center)
        local_own = self._strength(view, main, center)
        weak = [a for a in main if _hp(a) < 28 and any(distance(pos(a), pos(e)) < 10 for e in nearby)]
        if weak:
            orders += self._orders(view, weak, "move", self._fallback(view, center, nearby),
                                   "wounded", 100)
            weak_ids = {_id(a) for a in weak}
            main = [a for a in main if _id(a) not in weak_ids]
        if not main:
            return orders
        local_own = self._strength(view, main, center)
        aircraft = [e for e in nearby if _kind(e) in AIR
                    and self._value(view, e) > 0 and distance(pos(e), center) < 11]
        if aircraft and not any(_kind(a) in {"e3", "ftrk"} for a in main):
            aa_cover = [b for b in view.buildings if _kind(b) in {"agun", "sam"}
                        and b.get("powered", True) and pos(b) is not None]
            fallback = (pos(min(aa_cover, key=lambda b: distance(pos(b), center)))
                        if aa_cover else self._fallback(view, center, aircraft))
            self._set_mode("air-retreat", view.now)
            return orders + self._orders(view, main, "move", fallback, "air-retreat", 100)
        if local_enemy > local_own * 1.2 and local_enemy > 200:
            self.retreat_until = view.now + 10
        if view.now < self.retreat_until:
            self._set_mode("retreat", view.now)
            return orders + self._orders(view, main, "move", self._fallback(view, center, nearby),
                                         "retreat", 100)
        if home_threats:
            self._set_mode("defend", view.now)
            threat = min(home_threats, key=lambda e: distance(pos(e), center))
            return orders + self._orders(view, main, "attack_move", pos(threat), "defend", 95)
        goal = self._goal(view, center)
        if goal is None:
            return orders
        total = sum(self._value(view, a) for a in main)
        try:
            trade_proxy = float(view.military.get("kills_cost", 0)) - float(view.military.get("deaths_cost", 0))
        except (TypeError, ValueError):
            trade_proxy = 0
        if view.remaining < 90 and trade_proxy > 0 and local_enemy > local_own * 0.6:
            # Own net trades are only a proxy, not the opponent's score. Take
            # fewer marginal fights late; home threats were handled above.
            self._set_mode("preserve", view.now)
            return orders + self._orders(view, main, "move", self._fallback(view, center, nearby),
                                         "preserve", 90)
        threshold = 900 if view.now < 240 else 700
        ready = total >= threshold and len(main) >= 5
        ready = ready or (total >= 1400 and len(main) >= 2)
        # A small surviving force still searches and applies pressure late;
        # neither a positive own score nor unseen enemies proves a won game.
        ready = ready or (view.now > 360 and len(main) >= 3)
        ready = ready or (view.remaining < 75 and trade_proxy < 0 and len(main) >= 3
                          and total >= 450 and local_enemy < local_own * 0.7)
        if not ready:
            self._set_mode("regroup", view.now)
            origin = view.base or center
            dx, dy = goal[0] - origin[0], goal[1] - origin[1]
            norm = max(1.0, hypot(dx, dy))
            rally = (origin[0] + 6 * dx / norm, origin[1] + 6 * dy / norm)
            return orders + self._orders(view, main, "attack_move", rally, "regroup", 40)
        clustered = sum(distance(pos(a), center) < 12 for a in main) >= max(2, len(main) * 0.65)
        if not clustered and (self.mode != "regroup" or view.now - self.mode_since < 12):
            self._set_mode("regroup", view.now)
            return orders + self._orders(view, main, "attack_move", center, "assemble", 45)
        self._set_mode("pressure", view.now)
        # Advance in bounded steps. Refuse a visible defended destination until
        # reinforcements change the local comparison, while remaining active.
        if self._strength(view, enemies, goal, 12) > total * 0.9:
            dx, dy = center[0] - goal[0], center[1] - goal[1]
            norm = max(1.0, hypot(dx, dy))
            goal = (goal[0] + 18 * dx / norm, goal[1] + 18 * dy / norm)
        if self.army_goal is None or distance(self.army_goal, goal) > 6 or view.now - self.goal_since > 15:
            self.army_goal, self.goal_since = goal, view.now
        return orders + self._orders(view, main, "attack_move", self.army_goal, "pressure", 40)
