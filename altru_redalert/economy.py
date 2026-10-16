from __future__ import annotations

import math
from .model import Intent, distance, pos
from .macro_map import MacroMap
from .tactics import damage_rate, health, weapons

_COST = {"powr": 300, "tent": 500, "barr": 500, "proc": 1400,
         "weap": 2000, "fix": 1200, "e1": 100, "harv": 1100,
         "1tnk": 700, "jeep": 500, "apc": 850, "ftrk": 600}
_TIME = {"powr": 7.2, "tent": 12, "barr": 12, "proc": 33.6,
         "weap": 48, "e1": 2.4, "harv": 26.4}
_POWER = {"powr": 100, "tent": -20, "barr": -20, "proc": -30, "weap": -30}
_NONCOMBAT = {"mcv", "harv", "e6", "medi", "mech", "spy", "spy.england", "thf", "truk"}
_VEHICLES = {"1tnk", "2tnk", "3tnk", "4tnk", "apc", "ftrk", "jeep", "arty", "v2rl", "ttnk", "stnk", "ctnk"}
_TANKS = {"1tnk", "2tnk", "3tnk", "4tnk", "ttnk", "stnk", "ctnk"}
_AIR = {"yak", "mig", "heli", "hind", "mh60", "tran"}
_DEFENSES = {"pbox", "hbox", "gun", "ftur", "tsla", "agun", "sam"}


def _number(value, default=0.0):
    if isinstance(value, bool):
        return default
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _count(value):
    return max(1, int(_number(value, 1)))


def _cost(v, item):
    return max(0.0, _number(v.cost(item)) or _COST.get(item, 0))


def _power(v, item):
    value = v.spec(item).get("power")
    return _number(value) if value is not None else _POWER.get(item)


def _build_time(v, item, kind):
    return max(.2, _number(v.spec(item).get("build_time_s"),
                          _TIME.get(item, 60 if kind == "build" else 45)))


def _pending(v, cmd, item=None):
    return any(o.get("cmd") == cmd and (item is None or o.get("item") == item)
               for o in v.pending_orders)


def _reserved(v):

    amount = 0.0
    for p in v.production:
        item = str(p.get("item", "")).lower()
        progress = 1.0 if p.get("ready") else min(1.0, max(0.0, _number(p.get("progress"))))
        amount += _cost(v, item) * (_count(p.get("count")) - progress)
    for o in v.pending_orders:
        if o.get("cmd") in {"build", "train"}:
            amount += _cost(v, str(o.get("item", "")).lower()) * _count(o.get("count"))
    return amount


def _ready_buildings(v):
    if isinstance(v.legal.get("place"), list):
        entries = v.legal["place"]
        names = [e if isinstance(e, str) else e.get("item", e.get("type", ""))
                 for e in entries if isinstance(e, (str, dict))]
        return {n.lower() for n in names if isinstance(n, str)
                and v.queue(n).lower() in {"building", "defense"}}
    return {str(p.get("item", "")).lower() for p in v.production if p.get("ready")
            and str(p.get("queue", v.queue(p.get("item", "")))).lower() in {"building", "defense"}}


class Economy:
    def __init__(self):
        self._map = None
        self._map_id = None
        self._map_layout = None
        self._deploy_attempts = {}
        self._mcv_targets = {}
        self._mcv_progress = {}
        self._blocked_sites = {}
        self._last_now = None
        self._cadence = 15.0
        self._float_since = None
        self._harvester_retreat = {}
        self._saving_item = None
        self._saving_best_budget = 0.0
        self._saving_progress_at = 0.0
        self._saving_resume_at = 0.0
        self._tank_core_established = False
        self._ore_pressure = {}
        self._defense_targets = {}
        self._defense_placement_attempts = {}
        self._infantry_alert_until = 0.0
        self._factory_seen_at = None

    def _opening_pressure(self, v, anchors):
        """A visible group approaching our assets, never an inferred enemy army."""
        approaching = []
        if v.now < 360 and sum(v.count(t) for t in _TANKS) < 3:
            infantry = [e for e in v.enemies if pos(e) and weapons(v, e)
                        and (str(e.get("type", "")).startswith("e")
                             or v.queue(e.get("type", "")).lower() == "infantry")
                        and any(distance(pos(e), a) <= 24 for a in anchors)]
            approaching = max(([e for e in infantry if distance(pos(e), pos(center)) <= 12]
                               for center in infantry), key=len, default=[])
            if len(approaching) >= 4:
                self._infantry_alert_until = v.now + 25
            else:
                approaching = []
        return v.now < self._infantry_alert_until, approaching

    def _rush_cancel(self, v):
        # One observed optional commitment at a time. A cancellation does not
        # create spendable money here: wait for the queue/receipt to reconcile.
        if any(o.get("cmd") == "cancel" for o in v.pending_orders):
            return [], True
        if any(o.get("cmd") in {"build", "train", "place"} for o in v.pending_orders):
            return [], False
        optional = []
        for p in v.production:
            item = str(p.get("item", "")).lower()
            progress = _number(p.get("progress"))
            if p.get("ready") or not 0 <= progress < .8:
                continue
            if item == "fix" or (item == "harv" and v.count("harv") >= 2):
                optional.append((item != "fix", item))
        if not optional:
            return [], False
        item = min(optional)[1]
        return [Intent({"cmd": "cancel", "item": item}, priority=100,
                       cooldown=2, key=f"rush-cancel:{item}")], True

    def _development_goal(self, v, budget, critical_danger, vehicles, owned_combat):

        if sum(v.count(x) for x in ("3tnk", "2tnk", "1tnk")) >= 3:
            self._tank_core_established = True
        item = None
        if not critical_danger and v.has("proc") and v.count("harv") > 0 and v.remaining > 240:
            incoming = max(0, v.total("proc") - v.count("proc"))
            if v.total("proc") < 2 and v.available("proc", "build"):
                item = "proc"
            elif v.total("weap") == 0 and v.available("weap", "build"):
                item = "weap"
            elif v.has("weap"):
                # A first cheap combat vehicle covers the otherwise empty
                # interval while a depot unlocks medium/heavy tanks.
                escort = next((x for x in ("ftrk", "jeep", "apc", "1tnk")
                               if v.available(x, "train") and _cost(v, x) > 0), None)
                # A placed factory can be visible one observation before its
                # Vehicle queue enables legal items. Do not commit to a depot
                # in that brief window and thereby skip the opening escort.
                factory_starting = (v.now < 240 and v.total("harv") >= 2 and not vehicles
                                    and v.total("fix") == 0 and not v.queue_busy("Vehicle")
                                    and not escort and not v.available("harv", "train")
                                    and self._factory_seen_at is not None
                                    and v.now - self._factory_seen_at < 3)
                if (v.now < 240 and v.total("harv") >= 2 and not vehicles
                        and v.total("fix") == 0 and escort and not v.queue_busy("Vehicle")):
                    item = escort
                elif factory_starting:
                    pass
                elif v.total("harv") + incoming < 3 and v.available("harv", "train"):
                    item = "harv"
                elif (v.total("fix") == 0 and v.total("harv") >= 2
                      and v.available("fix", "build") and _power(v, "fix") is not None):
                    item = "fix"
                elif v.has("fix") and v.total("harv") >= 2:
                    core = sum(v.total(x) for x in ("3tnk", "2tnk", "1tnk"))
                    if core >= 3 and v.total("harv") < 4 and v.available("harv", "train"):
                        item = "harv"
                    elif (self._tank_core_established and v.total("e1") < 3
                          and v.available("e1", "train")):
                        item = "e1"
                    elif (self._tank_core_established
                          and sum(v.total(x) for x in ("ftrk", "apc", "jeep")) < 1):
                        item = next((x for x in ("ftrk", "apc", "jeep")
                                     if v.available(x, "train") and _cost(v, x) > 0), None)
                    if item is None and core < 6:
                        item = next((x for x in ("3tnk", "2tnk", "1tnk")
                                     if v.available(x, "train") and _cost(v, x) > 0), None)
        if item is None:
            self._saving_item = None
            return None
        if v.now < self._saving_resume_at:
            return None
        if item != self._saving_item:
            self._saving_item = item
            self._saving_best_budget = budget
            self._saving_progress_at = v.now
        elif budget >= self._saving_best_budget + 50:
            self._saving_best_budget = budget
            self._saving_progress_at = v.now
        elif v.now - self._saving_progress_at >= 45:
            self._saving_resume_at = v.now + 20
            self._saving_item = None
            return None
        return item

    def _refresh(self, v):
        if not v.has("weap"):
            self._factory_seen_at = None
        elif (self._factory_seen_at is None
              or self._last_now is not None and v.now < self._last_now):
            self._factory_seen_at = v.now
        layout = v.map_info.get("layout")
        if (self._map is None or self._map_id != v.map_id
                or self._map_layout != layout or self._map.bounds != v.bounds):
            self._map, self._map_id = MacroMap(v), v.map_id
            self._map_layout = layout
        if self._last_now is not None and v.now > self._last_now:
            dt = v.now - self._last_now
            if dt < 90:
                self._cadence = .7 * self._cadence + .3 * dt
        self._last_now = v.now
        if v.funds >= 2600:
            if self._float_since is None:
                self._float_since = v.now
        else:
            self._float_since = None
        self._blocked_sites = {p: until for p, until in self._blocked_sites.items() if until > v.now}
        live = {u["id"] for u in v.units if u.get("type") == "mcv"}
        self._mcv_targets = {uid: p for uid, p in self._mcv_targets.items() if uid in live}
        self._mcv_progress = {uid: p for uid, p in self._mcv_progress.items() if uid in live}

    def _ore(self, v, anchor=None):
        anchor = anchor or v.base
        if not anchor or not self._map.resources:
            return None
        candidates = [p for p in self._map.resources if distance(anchor, p) <= 28]
        return min(candidates, key=lambda p: (distance(anchor, p), p), default=None)

    def _unserved_yard(self, v):
        refs = [pos(b) for b in v.buildings if b.get("type") == "proc" and pos(b)]
        yards = [pos(b) for b in v.buildings if b.get("type") == "fact" and pos(b)]
        return next((p for p in yards if not any(distance(p, r) < 15 for r in refs)), None)

    def _placement(self, v, item, threat=None):
        if not v.base:
            return None
        if item in _DEFENSES:
            plan = self._defense_targets.get(item)
            if plan is None or v.now - plan["seen"] > 120:
                plan = self._ore_defense_plan(v)
            if plan is None:
                anchors = [pos(b) for b in v.buildings if b.get("type") in {"fact", "proc"} and pos(b)]
                point = threat or self._ore(v) or v.enemy_base or v.base
                anchor = min(anchors, key=lambda p: distance(p, point), default=v.base)
                plan = {"anchor": anchor, "point": point}
            previous = self._defense_placement_attempts.get(item)
            attempt = previous[1] if previous else 0
            if previous and v.now - previous[0] >= 2.5:
                attempt += 1
            if previous is None or attempt != previous[1]:
                self._defense_placement_attempts[item] = (v.now, attempt)
            if attempt >= 8:
                return None
            return self._defense_site(v, item, plan, attempt)
        anchor = v.base
        if item == "proc":
            anchor = self._unserved_yard(v) or anchor
        elif threat is not None:
            anchors = [pos(b) for b in v.buildings if pos(b) and b.get("type") in {"fact", "proc"}]
            anchor = min(anchors, key=lambda p: distance(p, threat), default=anchor)
        target = self._ore(v, anchor) if item == "proc" else threat
        if target is None:
            return None
        dx, dy = target[0] - anchor[0], target[1] - anchor[1]
        norm = math.hypot(dx, dy)
        if norm < 1:
            return None
        return v.ground_point((round(anchor[0] + 5 * dx / norm), round(anchor[1] + 5 * dy / norm)))

    def _ore_defense_plan(self, v):
        self._ore_pressure = {uid: p for uid, p in self._ore_pressure.items()
                              if v.now - p["seen"] < 100}
        plans = []
        refs = [b for b in v.buildings if b.get("type") == "proc" and pos(b)]
        for ref in refs:
            anchor = pos(ref)
            haulers = [u for u in v.units if u.get("type") == "harv" and pos(u)
                       and distance(pos(u), anchor) <= 18]
            fields = [p for p, size, regrows in self._map.clusters
                      if distance(p, anchor) <= 17 and (size >= 5 or regrows)]
            points = [anchor] + [pos(u) for u in haulers] + fields
            targets = [ref] + haulers
            enemies = [e for e in v.enemies if pos(e) and
                       (weapons(v, e) or e.get("type") in {"e6", "thf"})
                       and distance(pos(e), anchor) <= 23
                       and min(distance(pos(e), p) for p in points) <= 8
                       and (e.get("type") in {"e6", "thf"}
                            or any(damage_rate(v, e, a) > 0 for a in targets))]
            old = self._ore_pressure.get(ref["id"])
            if enemies:
                sustained = old is not None and v.now - old["seen"] <= 12
                first = old["first"] if sustained else v.now
                raids = (old["raids"] + int(not sustained)) if old else 1
                threat = min(enemies, key=lambda e: min(distance(pos(e), p) for p in points))
                armor = sum(e.get("type") in _VEHICLES for e in enemies)
                serious = armor >= 2 or len(enemies) >= 4
                damaged = any(_number(u.get("hp"), 100) < 75 for u in haulers)
                plan = {"anchor": anchor, "point": pos(threat), "enemies": enemies,
                        "seen": v.now, "first": first, "raids": raids,
                        "armor": armor, "air": any(e.get("type") in _AIR for e in enemies),
                        "repeat": raids >= 2 or v.now - first >= 12,
                        "urgent": serious or (armor >= 1 and damaged),
                        "severe": len(enemies) >= 6 or armor >= 3,
                        "refinery": ref["id"]}
                self._ore_pressure[ref["id"]] = plan
                if plan["repeat"] or plan["urgent"]:
                    plans.append(plan)
            elif old and v.now - old["seen"] <= 40 and old["repeat"]:
                plans.append({**old, "enemies": []})
        return max(plans, key=lambda p: (p["urgent"], p["repeat"], len(p["enemies"])), default=None)

    def _defense_site(self, v, item, plan, attempt=0):
        anchor, threat = plan["anchor"], plan["point"]
        buildings = [b for b in v.buildings if pos(b)]
        refs = [b for b in buildings if b.get("type") == "proc"]
        lanes = []
        for ref in refs:
            points = [pos(u) for u in v.units if u.get("type") == "harv" and pos(u)
                      and distance(pos(u), pos(ref)) <= 18]
            points += [p for p, _, _ in self._map.clusters if distance(p, pos(ref)) <= 18]
            lanes.extend((pos(ref), point) for point in points)

        def on_lane(point, start, end):
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = dx * dx + dy * dy
            if length < 1:
                return False
            t = max(0., min(1., ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length))
            return math.hypot(point[0] - start[0] - t * dx, point[1] - start[1] - t * dy) < 2.1

        sites = []
        for dx in range(-8, 9):
            for dy in range(-8, 9):
                point = (anchor[0] + dx, anchor[1] + dy)
                if v.clamp(point) != list(point) or not 4 <= math.hypot(dx, dy) <= 8:
                    continue
                if any(distance(point, pos(b)) < (4 if b.get("type") in {"proc", "weap"} else 3)
                       for b in buildings):
                    continue
                if min((distance(point, pos(b)) for b in buildings), default=99) > 6:
                    continue
                if any(on_lane(point, start, end) for start, end in lanes):
                    continue
                if any(distance(point, pos(u)) < 2 for u in v.units if u.get("type") == "harv"):
                    continue
                if self._map.origin is not None and any(
                        self._map.char((point[0] + x, point[1] + y)) not in {".", ",", "=", "_", "S"}
                        for x in (-1, 0, 1) for y in (-1, 0, 1, 2)):
                    continue
                coverage = distance(point, threat)
                score = coverage + .3 * distance(point, anchor)
                sites.append((score, point))
        sites.sort()
        if not sites:
            return None
        return list(sites[min(attempt * 3, len(sites) - 1)][1])

    def _defense_build(self, v, budget, power, plan, close, air_near, ready, reserved_vehicle=0,
                       infantry_alert=False):
        if (v.queue_busy("Defense") or v.remaining <= 40 or v.total("harv") == 0
                or any(v.queue(x).lower() == "defense" for x in ready)):
            return None, 0
        total = sum(v.total(x) for x in _DEFENSES)
        if total >= 2:
            return None, 0
        if plan is None and close:
            threat = min(close, key=lambda e: distance(pos(e), v.base))
            anchors = [pos(b) for b in v.buildings if b.get("type") in {"fact", "proc", "weap"} and pos(b)]
            anchor = min(anchors, key=lambda p: distance(p, pos(threat)), default=v.base)
            plan = {"anchor": anchor, "point": pos(threat), "enemies": close,
                    "seen": v.now, "repeat": False, "urgent": True,
                    "severe": len(close) >= 6, "refinery": None}
        if plan is None:
            return None, 0
        towers = [b for b in v.buildings if b.get("type") in _DEFENSES and pos(b) and weapons(v, b)]
        covered = bool(plan["enemies"]) and all(
            sum(damage_rate(v, b, enemy, at_distance=distance(pos(b), pos(enemy)))
                for b in towers) >= health(v, enemy) / 30
            for enemy in plan["enemies"])
        uncovered = bool(plan["enemies"]) and not covered
        correction = uncovered and (plan["urgent"] or v.now - plan.get("first", v.now) >= 24)
        if total and not (plan["repeat"] and (plan["severe"] or correction) and budget >= 2400):
            return None, 0
        if covered and not plan["severe"]:
            return None, 0
        armor = plan.get("armor", sum(e.get("type") in _VEHICLES for e in plan["enemies"]))
        choices = (["sam", "agun"] if air_near or plan.get("air") else ["gun", "tsla", "pbox", "ftur"]
                   if armor else ["pbox", "ftur", "hbox", "gun", "tsla"])
        reserve = 700 if v.has("weap") else 350
        affordable_tanks = [_cost(v, x) for x in ("3tnk", "2tnk", "1tnk") if v.available(x, "train")]
        if affordable_tanks:
            reserve = max(reserve, min(affordable_tanks) + 250)
        if v.total("harv") < 2 and v.available("harv", "train"):
            reserve = max(reserve, _cost(v, "harv") + 250)
        reserve = max(250, reserve - reserved_vehicle)
        if infantry_alert and not armor and not air_near and v.count("harv") >= 2:
            reserve = 150
        invested = sum(v.total(x) * _cost(v, x) for x in _DEFENSES)
        for item in choices:
            cost, drain = _cost(v, item), _power(v, item)
            if (not v.available(item, "build") or cost <= 0 or budget < cost + reserve
                    or cost + invested > 2200 or drain is None or power + drain < 0
                    or v.remaining <= _build_time(v, item, "build") + 20
                    or self._defense_site(v, item, plan) is None):
                continue
            self._defense_targets[item] = dict(plan)
            self._defense_placement_attempts.pop(item, None)
            return Intent({"cmd": "build", "item": item}, priority=89,
                          cooldown=1, key=f"build:{item}"), cost
        return None, 0

    def _deploy(self, v):
        orders = []
        deployable = v.legal.get("deploy")
        for unit in v.units:
            if unit.get("type") != "mcv" or not isinstance(unit.get("id"), int):
                continue
            uid, point = unit["id"], pos(unit)
            if point is None or any(uid in o.get("units", []) for o in v.pending_orders
                                    if o.get("cmd") in {"deploy", "move"}):
                continue
            target = self._mcv_targets.get(uid)
            if v.has("fact") and target is None:
                target = self._map.expansion(v, self._blocked_sites)
                if target:
                    self._mcv_targets[uid] = target
            if target:
                threats = [e for e in v.enemies + v.enemy_buildings if pos(e)
                           and e.get("type") not in _NONCOMBAT
                           and min(distance(pos(e), point), distance(pos(e), target)) < 15]
                if threats:
                    self._blocked_sites[target] = v.now + 90
                    self._mcv_targets.pop(uid, None)
                    self._mcv_progress.pop(uid, None)
                    home = v.ground_point(v.base)
                    if home and distance(point, home) > 4:
                        orders.append(Intent({"cmd": "move", "units": [uid], "to": home},
                                             priority=98, cooldown=3, key=f"mcv-escape:{uid}"))
                    continue
                previous = self._mcv_progress.get(uid)
                if previous is None or distance(point, previous[0]) >= 2:
                    self._mcv_progress[uid] = (point, v.now)
                elif v.now - previous[1] > 45 and distance(point, target) > 4:
                    self._blocked_sites[target] = v.now + 120
                    self._mcv_targets.pop(uid, None)
                    self._mcv_progress.pop(uid, None)
                    continue
                if distance(point, target) > 3:
                    if unit.get("idle", True) or previous is None:
                        orders.append(Intent({"cmd": "move", "units": [uid], "to": list(target)},
                                             priority=94, cooldown=5, key=f"mcv-expand:{uid}"))
                    continue
            elif v.has("fact"):
                continue
            previous = self._deploy_attempts.get(uid)
            allowed = not isinstance(deployable, list) or uid in deployable
            retry = previous and point == previous[0] and v.now - previous[1] >= 4
            if not allowed or retry:
                if not unit.get("idle", True):
                    continue
                n = previous[2] if previous else 0
                dx, dy = ((3, 0), (0, 3), (-3, 0), (0, -3))[n % 4]
                dest = v.ground_point((point[0] + dx, point[1] + dy))
                if dest and tuple(dest) != point:
                    orders.append(Intent({"cmd": "move", "units": [uid], "to": dest},
                                         priority=95, cooldown=3, key=f"mcv-clear:{uid}"))
                    self._deploy_attempts[uid] = (point, v.now, n + 1)
                    if target:
                        self._mcv_targets[uid] = tuple(dest)
                continue
            orders.append(Intent({"cmd": "deploy", "units": [uid]}, priority=95,
                                 cooldown=2, key=f"deploy:{uid}"))
            self._deploy_attempts[uid] = (point, v.now, previous[2] if previous else 0)
        return orders

    def _harvest(self, v):
        from .mining import MiningManager

        if not hasattr(self, "_mining"):
            self._mining = MiningManager()
        return self._mining.propose(v, self._map)

    def _batch(self, v, item, budget, cap=10, reserve=0, horizon=None):
        cost, duration = _cost(v, item), _build_time(v, item, "train")
        if cost <= 0 or not v.available(item, "train"):
            return 0
        runway = horizon if horizon is not None else max(12, min(28, self._cadence * 1.6))
        limit = min(10, max(1, int(_number((v.raw.get("limits") or {}).get("max_train_count"), 10))))
        time_limit = int(max(0, v.remaining - 10) // duration) if math.isfinite(v.remaining) else limit
        return max(0, min(cap, limit, math.ceil(runway / duration),
                          int(max(0, budget - reserve) // cost),
                          time_limit))

    def _recover_income(self, v):

        if v.count("harv") or v.remaining <= 50:
            return [], False
        incoming = v.total("harv") > 0 or v.total("proc") > v.count("proc")
        if incoming:
            required = 0
        elif v.available("harv", "train"):
            required = _cost(v, "harv")
        elif v.has("fact") and v.available("proc", "build"):
            required = _cost(v, "proc")
        elif not v.has("fact") and (v.total("mcv") or v.available("mcv", "train")):
            required = _cost(v, "proc") + (0 if v.total("mcv") else _cost(v, "mcv"))
            if v.total("powr") + v.total("apwr") == 0:
                required += _cost(v, "powr")
        else:
            return [], False
        if v.funds >= _reserved(v) + required:
            return [], False
        if any(o.get("cmd") in {"build", "train", "cancel"} for o in v.pending_orders):
            return [], True
        candidates = []
        for p in v.production:
            item = str(p.get("item", "")).lower()
            if not item or item in {"harv", "proc"} or p.get("ready"):
                continue
            if item == "mcv" and not v.has("fact") and not v.available("harv", "train"):
                continue
            queue = str(p.get("queue", v.queue(item))).lower()
            unpaid = _cost(v, item) * (_count(p.get("count")) - min(1, max(0, _number(p.get("progress")))))
            blocking = queue == ("vehicle" if v.available("harv", "train") else "building")
            candidates.append((not blocking, -unpaid, item))
        if not candidates:
            return [], False
        item = min(candidates)[2]
        return [Intent({"cmd": "cancel", "item": item}, priority=100,
                       cooldown=2, key=f"income-cancel:{item}")], True

    def propose(self, v):
        self._refresh(v)
        intents = self._deploy(v) + self._harvest(v)
        budget = max(0.0, v.funds - _reserved(v))
        anchors = [pos(b) for b in v.buildings if b.get("type") in {"fact", "proc", "weap"} and pos(b)]
        if not anchors and v.base:
            anchors = [v.base]
        near = [e for e in v.enemies if pos(e) and (weapons(v, e) or e.get("type") in {"e6", "thf"})
                and any(distance(pos(e), a) <= 18 for a in anchors)]
        infantry_alert, approaching = self._opening_pressure(v, anchors)
        armor = sum(e.get("type") in _VEHICLES for e in v.enemies)
        air = sum(e.get("type") in _AIR or v.queue(e.get("type", "")).lower() == "aircraft" for e in v.enemies)
        air_near = any(e.get("type") in _AIR or v.queue(e.get("type", "")).lower() == "aircraft" for e in near)
        infantry_threat = max(len(approaching), sum(str(e.get("type", "")).startswith("e") for e in near))
        home_danger = infantry_alert or len(near) >= 2 or any(e.get("type") in _VEHICLES | _AIR for e in near)
        close = [e for e in near if any(distance(pos(e), a) <= 10 for a in anchors)]
        critical_danger = infantry_alert or len(close) >= 2 or any(e.get("type") in _VEHICLES | _AIR for e in close)
        target = min((pos(e) for e in near), key=lambda p: distance(p, v.base), default=None)
        ore_defense = self._ore_defense_plan(v)
        if approaching and ore_defense is None and anchors:
            threat = min(approaching, key=lambda e: min(distance(pos(e), a) for a in anchors))
            anchor = min(anchors, key=lambda a: distance(a, pos(threat)))
            ore_defense = {"anchor": anchor, "point": pos(threat), "enemies": approaching,
                           "seen": v.now, "first": v.now, "repeat": False, "urgent": True,
                           "severe": len(approaching) >= 6, "armor": 0, "air": False}
        ready = _ready_buildings(v)
        for item in sorted(ready):
            if _pending(v, "place", item):
                continue
            order = {"cmd": "place", "item": item}
            at = self._placement(v, item, target if item in _DEFENSES else None)
            if at is not None:
                order["at"] = at
            intents.append(Intent(order, priority=96, cooldown=.6, key=f"place:{item}"))

        recovery, holding_recovery = self._recover_income(v)
        intents.extend(recovery)
        if holding_recovery:
            return intents
        damaged = sorted((b for b in v.buildings if 0 < _number(b.get("hp"), 100) < 85
                          and not b.get("repairing") and isinstance(b.get("id"), int)),
                         key=lambda b: (b.get("type") not in {"fact", "proc", "powr", "weap"}, b.get("hp", 100)))
        if v.funds >= 150:
            for b in damaged[:3]:
                if home_danger or _number(b.get("hp"), 100) < 60 or v.funds >= 1200:
                    intents.append(Intent({"cmd": "repair", "building": b["id"], "on": True},
                                          priority=99 if home_danger else 75, cooldown=3, key=f"repair:{b['id']}"))
        if infantry_alert:
            cancelled, holding_cancel = self._rush_cancel(v)
            intents.extend(cancelled)
            if holding_cancel:
                return intents
        projected_power = v.power_surplus
        future_builds = [str(p.get("item", "")).lower() for p in v.production
                         if str(p.get("queue", v.queue(p.get("item", "")))).lower() in {"building", "defense"}]
        future_builds += [o.get("item", "") for o in v.pending_orders if o.get("cmd") == "build"]
        for item in future_builds:
            projected_power += min(0, _power(v, item) or 0)

        harvs, total_harvs = v.count("harv"), v.total("harv")
        owned_combat = sum(u.get("type") not in _NONCOMBAT for u in v.units)
        tanks = sum(v.total(t) for t in _TANKS)
        vehicles = sum(v.total(t) for t in _VEHICLES)
        has_barracks = v.total("tent") + v.total("barr") > 0
        barracks = "tent" if v.available("tent", "build") or v.has("tent") else "barr"
        far = bool(v.base and v.enemy_base and distance(v.base, v.enemy_base) >= 70)
        emergency_harvester = total_harvs == 0 and v.available("harv", "train") and not v.queue_busy("Vehicle") and v.remaining > 50
        income_reserve = min(budget, _cost(v, "harv")) if emergency_harvester else 0
        budget -= income_reserve
        # The first four rifles include one scout. Reserve their budget before
        # peaceful development, but let needed power and urgent defense use it.
        screen_order = False
        screen_reserve = 0
        if (v.now < 180 and v.has("fact") and v.has("proc") and harvs > 0
                and v.power_surplus >= 0 and v.total("e1") < 4
                and v.available("e1", "train") and not v.queue_busy("Infantry")):
            n = self._batch(v, "e1", budget, cap=4 - v.total("e1"))
            screen_reserve = n * _cost(v, "e1")
            budget -= screen_reserve
        unserved = self._unserved_yard(v) if v.count("fact") > 1 else None
        expansion = None
        if (1 <= v.count("fact") < 3 and v.now >= 240 * v.count("fact") and v.remaining > 300
                and v.count("proc") >= 2 and harvs >= 3 and owned_combat >= 12 and not home_danger):
            expansion = self._map.expansion(v, self._blocked_sites)
        expansion_due = (expansion is not None and v.total("mcv") == 0 and v.available("mcv", "train")
                         and budget >= _cost(v, "mcv") + _cost(v, "proc") + 300)
        expansion_in_transit = v.has("fact") and v.total("mcv") > 0
        expansion_reserve = min(budget, _cost(v, "proc") + 300) if expansion_in_transit or expansion_due else 0
        rebuilding_income = (not v.has("fact") and not v.has("proc") and total_harvs == 0
                             and (v.total("mcv") > 0 or v.available("mcv", "train")))
        if rebuilding_income:
            recovery_cost = _cost(v, "proc") + (300 if v.total("powr") + v.total("apwr") == 0 else 0)
            expansion_reserve = max(expansion_reserve, min(budget, recovery_cost))
        mcv_reserve = _cost(v, "mcv") if expansion_due else 0
        budget -= expansion_reserve + mcv_reserve
        budget = max(0, budget)
        development = self._development_goal(v, budget, critical_danger, vehicles, owned_combat)
        development_is_vehicle = development is not None and v.queue(development).lower() == "vehicle"
        development_vehicle = min(budget, _cost(v, development)) if development_is_vehicle else 0
        budget -= development_vehicle
        development_started = False

        building, build_priority = None, 80
        if v.has("fact") and not v.queue_busy("Building") and not any(v.queue(x).lower() == "building" for x in ready):
            if v.total("powr") + v.total("apwr") == 0 or v.power_surplus < 0:
                if not any(v.total(x) > v.count(x) for x in ("powr", "apwr")):
                    building, build_priority = "powr", 91
            elif not has_barracks and (not far or v.total("proc") or home_danger):
                building = barracks
            elif v.total("proc") == 0:
                building = "proc"
            elif total_harvs == 0 and not v.available("harv", "train"):
                building, build_priority = "proc", 92
            elif not has_barracks:
                building = barracks
            elif development in {"weap", "proc", "fix"}:
                building, build_priority = development, 85
            elif unserved and not home_danger and v.remaining > 160:
                building, build_priority = "proc", 88
            elif (far and not home_danger and v.total("proc") < 2 and v.total("weap") == 0
                  and v.count("e1") >= 2 and v.remaining > 300):
                building = "proc"
            elif v.total("weap") == 0 and not infantry_alert:
                building = "weap"
            elif (v.total("proc") < 2 and v.now >= 100 and v.remaining > 240 and not home_danger
                  and budget >= _cost(v, "proc") + 300):
                building = "proc"
            elif (v.total("fix") == 0 and v.available("fix", "build") and _power(v, "fix") is not None
                  and v.now >= 150 and v.remaining > 220
                  and (v.count("proc") >= 2 or armor >= 3) and harvs >= 2 and not home_danger
                  and budget >= _cost(v, "fix") + 500
                  and (v.now >= 240 or vehicles > 0)):
                building = "fix"
            elif (v.total("dome") == 0 and v.available("dome", "build") and _power(v, "dome") is not None
                  and v.now >= 210 and v.remaining > 170
                  and harvs >= 3 and vehicles >= 3 and (not home_danger or air_near)
                  and budget >= _cost(v, "dome") + 700):
                building = "dome"
            elif (v.total(barracks) < 2 and v.available(barracks, "build") and v.count("proc") >= 2 and harvs >= 3
                  and owned_combat >= 12 and v.now >= 240 and v.remaining > 160
                  and budget >= _cost(v, barracks) + 1600 and not home_danger):
                building = barracks
            elif (v.total("weap") < min(3, v.count("fact") + 1) and v.available("weap", "build") and harvs >= 4
                  and v.now >= 300 and v.remaining > 180 and not home_danger
                  and self._float_since is not None and v.now - self._float_since >= 25
                  and budget >= _cost(v, "weap") + 1800):
                building = "weap"
            if building:
                drain = _power(v, building)
                if drain is not None and drain < 0 and projected_power < -drain:
                    building = "powr" if not any(v.total(x) > v.count(x) for x in ("powr", "apwr")) else None
                    build_priority = 91
                if building == "powr" and v.available("apwr", "build") and budget >= _cost(v, "apwr"):
                    building = "apwr"
                if building and v.total(building) > v.count(building):
                    building = None
                if building:
                    cost = _cost(v, building)
                    if building in {"powr", "apwr"} and budget < cost:
                        released = min(screen_reserve, cost - budget)
                        budget += released
                        screen_reserve -= released
                    end_ok = v.remaining > _build_time(v, building, "build") + 35
                    if (v.available(building, "build") and cost > 0 and budget >= cost
                            and (end_ok or (building in {"powr", "apwr"} and v.power_surplus < 0
                                            and v.remaining > _build_time(v, building, "build") + 5))):
                        intents.append(Intent({"cmd": "build", "item": building}, priority=build_priority,
                                              cooldown=1, key=f"build:{building}"))
                        budget -= cost
                        projected_power += min(0, _power(v, building) or 0)
                        development_started = building == development

        defense_order, defense_cost = self._defense_build(
            v, budget + (screen_reserve if infantry_alert else 0), projected_power,
            ore_defense, close if critical_danger else [],
            air_near, ready, development_vehicle, infantry_alert)
        if defense_order is not None:
            released = min(screen_reserve, max(0, defense_cost - budget))
            budget += released
            screen_reserve -= released
            intents.append(defense_order)
            budget -= defense_cost

        if screen_reserve:
            n = self._batch(v, "e1", screen_reserve, cap=4 - v.total("e1"))
            if n:
                intents.append(Intent({"cmd": "train", "item": "e1", "count": n}, priority=88,
                                      cooldown=.6, key="train:e1"))
                screen_reserve -= n * _cost(v, "e1")
                screen_order = True
            budget += screen_reserve

        budget += income_reserve + mcv_reserve + development_vehicle
        if development in {"weap", "proc", "fix"} and not development_started:
            budget = max(0, budget - _cost(v, development))
        vehicle_item, vehicle_priority, vehicle_cap = None, 63, 2
        combat_vehicle_reserve = 250
        rush_escort = next((x for x in ("ftrk", "jeep", "apc")
                            if v.available(x, "train") and _cost(v, x) > 0
                            and budget >= _cost(v, x) + 100), None) if infantry_alert else None
        if not v.queue_busy("Vehicle") and v.remaining > 25:
            if emergency_harvester:
                vehicle_item, vehicle_priority, vehicle_cap = "harv", 93, 1
            elif not v.has("fact") and v.total("mcv") == 0 and v.remaining > 180 and v.available("mcv", "train"):
                vehicle_item, vehicle_priority, vehicle_cap = "mcv", 92, 1
            elif expansion_due:
                vehicle_item, vehicle_priority, vehicle_cap = "mcv", 84, 1
            elif rush_escort and sum(v.total(x) for x in ("ftrk", "jeep", "apc")) < 2:
                vehicle_item = rush_escort
                vehicle_priority, vehicle_cap, combat_vehicle_reserve = 90, 1, 100
            elif development_is_vehicle:
                if budget >= _cost(v, development):
                    vehicle_item, vehicle_priority, vehicle_cap = development, 84, 1
                    combat_vehicle_reserve = 0
            elif development == "e1":
                pass
            elif v.total("fix") > v.count("fix") and not critical_danger:
                pass
            else:
                goal = min(8, max(1, 2 * v.count("proc"))) if v.count("proc") >= 2 else 1
                incoming_refinery_harvs = max(0, v.total("proc") - v.count("proc"))
                if (total_harvs + incoming_refinery_harvs < goal and v.remaining > 220 and not home_danger
                        and v.available("harv", "train") and budget >= _cost(v, "harv") + 650):
                    vehicle_item, vehicle_priority, vehicle_cap = "harv", 78, 1
                else:
                    artillery = v.total("arty") + v.total("v2rl")
                    aa_need = air > 0 and v.total("ftrk") < max(2, min(5, air))
                    siege_need = (vehicles >= 3 and v.total("e1") >= 5 and artillery < min(4, max(1, tanks // 3))
                                  and not (home_danger and infantry_threat >= 4))
                    if aa_need:
                        choices = ["ftrk", "3tnk", "2tnk", "1tnk", "apc", "jeep"]
                        vehicle_cap = max(1, min(2, max(2, air) - v.total("ftrk")))
                    elif siege_need:
                        choices = ["arty", "v2rl", "3tnk", "2tnk", "1tnk", "ftrk", "apc", "jeep"]
                        vehicle_cap = 1
                    elif infantry_threat >= 3 and v.total("ftrk") + v.total("apc") + v.total("jeep") < max(2, vehicles // 3):
                        choices = ["ftrk", "apc", "jeep", "1tnk", "3tnk", "2tnk"]
                    else:
                        choices = ["3tnk", "2tnk", "1tnk", "ftrk", "apc", "jeep"]
                    vehicle_item = next((x for x in choices if v.available(x, "train") and _cost(v, x) > 0
                                         and budget >= _cost(v, x) + combat_vehicle_reserve), None)
        vehicle_order = None
        if vehicle_item:
            n = self._batch(v, vehicle_item, budget, cap=vehicle_cap,
                            reserve=0 if vehicle_item in {"harv", "mcv"} else combat_vehicle_reserve,
                            horizon=max(25, min(45, self._cadence * 2)))
            if n:
                vehicle_order = {"cmd": "train", "item": vehicle_item}
                if n > 1:
                    vehicle_order["count"] = n
                intents.append(Intent(vehicle_order, priority=vehicle_priority, cooldown=.8,
                                      key=f"train:{vehicle_item}"))
                budget -= n * _cost(v, vehicle_item)
        if emergency_harvester and not (vehicle_order and vehicle_item == "harv"):
            budget = max(0, budget - income_reserve)
        if development_is_vehicle and not (vehicle_order and vehicle_item == development):
            budget = max(0, budget - _cost(v, development))
        if v.total("fix") > v.count("fix") and not critical_danger:
            budget = max(0, budget - 1150)

        if not screen_order and not v.queue_busy("Infantry") and v.remaining > 12:
            rifles, rockets = v.total("e1"), v.total("e3")
            core = sum(v.total(x) for x in ("3tnk", "2tnk", "1tnk"))
            rifle_goal = min(24, 6 + core * 2) if v.has("weap") else (5 if home_danger else 3)
            rocket_goal = max(2 if v.has("weap") else 0, rifles // 5)
            if armor >= 2 or air:
                rocket_goal = max(rocket_goal, min(12, armor + 2 * air + 1))
            if home_danger:
                rifle_goal = max(rifle_goal, 10)
            if infantry_alert and rifles < max(6, infantry_threat + 2) and not air and armor < 2:
                item, deficit = "e1", max(6, infantry_threat + 2) - rifles
            elif development == "e1":
                item, deficit = "e1", 3 - rifles
            elif (rockets < rocket_goal and v.available("e3", "train")
                    and (rifles >= 4 or air or armor >= 2)):
                item, deficit = "e3", rocket_goal - rockets
            elif rifles < rifle_goal:
                item, deficit = "e1", rifle_goal - rifles
            else:
                item, deficit = None, 0
            if item:
                saving_factory = (v.total("weap") == 0 and v.has("proc") and rifles >= (2 if not far else 1) and not critical_danger)
                reserve = _cost(v, "weap") if saving_factory and not air else 0
                if (not v.has("fact") and v.total("mcv") == 0 and v.available("mcv", "train")
                        and v.remaining > 180 and not (vehicle_order and vehicle_item == "mcv")):
                    reserve = max(reserve, _cost(v, "mcv"))
                n = self._batch(v, item, budget, cap=min(10, deficit), reserve=reserve)
                if n:
                    order = {"cmd": "train", "item": item}
                    if n > 1:
                        order["count"] = n
                    intents.append(Intent(order, priority=74 if air and item == "e3" else 72 if home_danger else 60,
                                          cooldown=.6, key=f"train:{item}"))
        return intents
