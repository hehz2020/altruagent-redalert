"""Conservative ground-army control using only contestant-visible information.

Spearhead-inspired local commitment, economy protection, selective targeting
and stable withdrawals. No hidden actors or engine-internal state are used.
"""

from collections import deque
from math import hypot, sqrt
from statistics import median

from .model import Intent, distance, living, pos
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
            if order.get("cmd") == "attack" and "target" in order:
                signature = ("attack", order["target"])
            elif order.get("cmd") in {"move", "attack_move"} and "to" in order:
                signature = (order["cmd"], tuple(order["to"]))
            else:
                continue
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
                   or view.now - old[1] >= 18
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
        # Store only the last authorized sighting. Mobile contacts expire quickly;
        # their positions are risk hints, never valid attack-target actor IDs.
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

    def _attack_orders(self, view, assignments, role, priority=80):
        groups = {}
        for actor, target in assignments:
            uid, tid = _id(actor), _id(target)
            old = self.desired.get(uid)
            signature = ("attack", tid)
            if (old is None or old[0] != signature or view.now - old[1] >= 12
                    or (actor.get("idle") and view.now - old[1] >= 2)):
                groups.setdefault(tid, []).append(uid)
        # Leave room for production and urgent economy orders in the 20-order cap.
        return [Intent({"cmd": "attack", "units": ids, "target": tid},
                       priority=priority, cooldown=1.5, key=f"military:{role}:{tid}")
                for tid, ids in sorted(groups.items(), key=lambda pair: -len(pair[1]))[:6]]

    def _local_fire(self, view, army, enemies, role="fire", priority=80):
        """Focus only within actual estimated range: do not chase into a base.

        Allocation discourages spending the entire army's volley on a nearly
        dead rifleman. Busy units with an unchanged target keep that order.
        """
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
                    score *= 1.2  # Hysteresis: avoid target churn and cancelled shots.
                candidates.append((score, -_id(e), e))
            if not candidates:
                continue
            target = max(candidates, key=lambda entry: entry[:2])[2]
            assignments.append((actor, target))
            committed.add(_id(actor))
            allocated[_id(target)] = allocated.get(_id(target), 0) + damage_rate(view, actor, target) * 2.
        intents = self._attack_orders(view, assignments, role, priority)
        emitted = {uid for intent in intents for uid in intent.order["units"]}
        # A capped target group must not reserve units whose attack was omitted.
        # Preserve an already running valid attack, otherwise let macro control act.
        committed = { _id(a) for a, target in assignments if _id(a) in emitted
                      or (self.desired.get(_id(a), (None,))[0] == ("attack", _id(target))
                          and (not a.get("idle", False)
                               or view.now - self.desired[_id(a)][1] < 2)) }
        return intents, committed

    def _withdraw(self, view, army, enemies, role="retreat"):
        """Fast units disengage; trapped slow units fight instead of free losses."""
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
            # Artillery cannot trade at point-blank range; withdraw behind screens.
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
        threats = [e for e in enemies if (weapons(view, e) or _kind(e) in {"e6", "thf"})
                   and any(distance(pos(e), pos(p)) < 11 for p in protected)]
        if not threats:
            return [], set()
        # Deal with the most exposed economy group, not a bait unit beside an
        # irrelevant remote power plant. Only enough closest defenders respond.
        target = min(threats, key=lambda e: min(distance(pos(e), pos(p)) for p in protected))
        local = [e for e in threats if distance(pos(e), pos(target)) < 13]
        # Aircraft must not recall ground-only units that cannot help. Check
        # weapon suitability independently of distance, so distant AA can still
        # respond while the ground army retains its own objective.
        candidates = sorted((a for a in army if any(
            damage_rate(view, a, e) > 0 for e in local)),
            key=lambda a: distance(pos(a), pos(target)))
        if not candidates:
            return [], set()
        defenders = []
        for a in candidates:
            defenders.append(a)
            if len(defenders) >= 2 and force_ratio(view, defenders, local, horizon=16) >= 1.4:
                break
        ids = {_id(a) for a in defenders}
        center = _center(defenders)
        ratio = force_ratio(view, defenders, local)
        if ratio < .65 and any(distance(pos(a), pos(e)) < 9 for a in defenders for e in local):
            # Survive to reinforce while avoiding a full-army suicide response.
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
        # Opportunistic harassment requires real reconnaissance and a large main
        # force; never split a small starting army or invent an unseen harvester.
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
        """A visible structure's safe firing position, independent of the screen.

        Keeping every gun four cells behind tanks at a ten-cell standoff can
        strand a twelve-cell gun forever. Approach a currently visible building
        from the gun's side, and verify the resulting map cell is both in our
        firing range and outside visible enemy firing ranges. This is a local
        position check, not a prediction of an unseen enemy or a safe route.
        """
        visible_buildings = {_id(b) for b in view.enemy_buildings}
        targets = [e for e in enemies if _id(e) in visible_buildings
                   and damage_rate(view, gun, e) > 0]
        for target in sorted(targets, key=lambda e: distance(pos(gun), pos(e))):
            # Far-away sightings do not peel a gun off its screen. Normal
            # formation movement brings it close enough for a local approach.
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
            # Use a conservative outer-range margin, not distance minus one:
            # subtracting a margin can accidentally move an enemy artillery
            # estimate inside its minimum range and label real counterfire safe.
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
            # A screen must actually stand between the gun and its attacker.
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
        nearby = [e for e in enemies if weapons(view, e) and distance(pos(e), center) < 17]
        local = [a for a in main if distance(pos(a), center) < 15]
        # Friendly static guns count only while they can support this contact.
        support = [b for b in view.buildings if _kind(b) in GROUND_DEFENSE | {"agun", "sam"}
                   and b.get("powered", True) and distance(pos(b), center) < 10]
        ratio = force_ratio(view, local + support, nearby)
        self.last_ratio = ratio
        if nearby and ratio < .8:
            if self.mode != "retreat" or view.now >= self.retreat_until:
                self.withdraw_goal = self._fallback(view, center, nearby)
            self.retreat_until = max(self.retreat_until, view.now + 9)
        # Different enter/exit thresholds prevent advance-retreat oscillations.
        if view.now < self.retreat_until and (nearby and ratio < 1.2):
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
        goal = self._goal(view, center)
        if goal is None:
            return orders
        total = sum(self._value(view, a) for a in main)
        threshold = 1000 if view.now < 180 else 800
        ready = ((total >= threshold and len(main) >= 6) or (total >= 1700 and len(main) >= 3)
                 or (view.now > 360 and len(main) >= 3) or view.now < self.commit_until)
        fire, engaged = self._local_fire(view, [a for a in main if _kind(a) not in ARTILLERY], enemies)
        orders += fire
        guns, gun_ids = self._support(view, main, goal, enemies)
        orders += guns
        movable = [a for a in main if _id(a) not in engaged | gun_ids]
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
        self.commit_until = view.now + 20
        # Previously seen static defenses survive fog in the risk model only.
        # We never target their IDs or update their hidden health/position.
        resistance = [e for e in enemies if weapons(view, e) and distance(pos(e), goal) < 12]
        visible_ids = {_id(e) for e in enemies}
        resistance += [e for uid, (e, seen, building) in self.contacts.items()
                       if uid not in visible_ids and building and weapons(view, e)
                       and view.now - seen < 90 and distance(pos(e), goal) < 12]
        siege = any(_kind(a) in ARTILLERY for a in main)
        if resistance and force_ratio(view, main, resistance, horizon=30, projected=True) < 1.1:
            dx, dy = center[0] - goal[0], center[1] - goal[1]
            norm = max(1., hypot(dx, dy))
            standoff = 10 if siege else 15
            goal = (goal[0] + standoff * dx / norm, goal[1] + standoff * dy / norm)
        if self.army_goal is None or distance(self.army_goal, goal) > 6 or view.now - self.goal_since > 20:
            self.army_goal, self.goal_since = goal, view.now
        return orders + self._orders(view, movable, "attack_move", self.army_goal, "pressure", 40)
