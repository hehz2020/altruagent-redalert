"""Conservative, deterministic Red Alert economy and production.

This policy uses only the documented MCP orders and currently available items.
Its opening is a starting candidate, not a measured optimum: short maps get
infantry first, long maps get the first refinery first.  Resource reservations,
small queues and modest technology keep an untested build from consuming every
credit.  Combat movement and scouting assignments belong to Military.
"""
from __future__ import annotations

import math
from .model import Intent, distance, pos

# Only costs/times explicitly stated in the platform guide are fallbacks.
_COST = {"powr": 300, "tent": 500, "barr": 500, "proc": 1400,
         "weap": 2000, "fix": 1200, "e1": 100, "harv": 1100,
         "1tnk": 700, "jeep": 500, "apc": 850, "ftrk": 600}
_TIME = {"powr": 7.2, "tent": 12, "barr": 12, "proc": 33.6,
         "weap": 48, "e1": 2.4, "harv": 26.4}
_POWER = {"powr": 100, "tent": -20, "barr": -20, "proc": -30,
          "weap": -30}
_NONCOMBAT = {"mcv", "harv", "e6", "medi", "mech"}
_VEHICLES = {"1tnk", "2tnk", "3tnk", "4tnk", "apc", "ftrk", "jeep",
             "arty", "v2rl", "ttnk", "stnk"}
_AIR = {"yak", "mig", "heli", "hind", "tran"}
_DEFENSES = {"pbox", "gun", "ftur", "tsla", "agun", "sam"}


def _number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _cost(v, item):
    return max(0.0, _number(v.cost(item)) or _COST.get(item, 0))


def _power(v, item):
    # Unknown power is left unknown rather than silently claiming it is free.
    spec = v.spec(item)
    value = spec.get("power") if isinstance(spec, dict) else None
    return _number(value) if value is not None else _POWER.get(item)


def _build_time(v, item, kind):
    spec = v.spec(item)
    value = spec.get("build_time_s") if isinstance(spec, dict) else None
    # Unknown duration: a conservative decision horizon, not an engine fact.
    return _number(value, _TIME.get(item, 60 if kind == "build" else 45))


def _pending(v, cmd, item=None):
    return any(o.get("cmd") == cmd and (item is None or o.get("item") == item)
               for o in v.pending_orders)


def _reserved(v):
    """Reserve the unpaid part of queues plus unresolved new production.

    The controller removes reflected pending orders from its ledger.  Reserving
    the whole pending price until then is intentionally conservative.
    """
    amount = 0.0
    for p in v.production:
        if p.get("ready"):
            continue
        item = str(p.get("item", "")).lower()
        progress = min(1.0, max(0.0, _number(p.get("progress"))))
        amount += _cost(v, item) * (1.0 - progress)
    for o in v.pending_orders:
        if o.get("cmd") in {"build", "train"}:
            amount += _cost(v, str(o.get("item", "")).lower()) * max(1, int(_number(o.get("count"), 1)))
    return amount


class Economy:
    def __init__(self):
        self._ore_cache = {}
        self._deploy_attempts = {}

    def _ore(self, v):
        key = (v.map_id, tuple(v.base) if v.base else None)
        if key in self._ore_cache:
            return self._ore_cache[key]
        layout = v.map_info.get("layout", {})
        best = None
        if isinstance(layout, dict) and v.base:
            rows = layout.get("rows", [])
            origin = layout.get("origin", [0, 0])
            if isinstance(origin, (list, tuple)) and len(origin) == 2:
                choices = []
                for y, row in enumerate(rows):
                    if not isinstance(row, str):
                        continue
                    for x, ch in enumerate(row):
                        if ch in {"$", "*", "M"}:
                            p = (origin[0] + x, origin[1] + y)
                            d = distance(v.base, p)
                            if d <= 30:
                                choices.append((d, p))
                if choices:
                    best = min(choices)[1]
        self._ore_cache[key] = best
        return best

    def _placement(self, v, item, threat=None):
        """Only suggest nearby cells; the engine validates/falls back itself.

        The map is static, so ore is used for initial siting only, never to
        repeatedly order harvesters toward a possibly depleted field.
        """
        if not v.base:
            return None
        target = self._ore(v) if item == "proc" else threat
        if target is None:
            return None  # Default engine placement is safer than guessed footprints.
        dx, dy = target[0] - v.base[0], target[1] - v.base[1]
        norm = math.hypot(dx, dy)
        if norm < 1:
            return None
        return v.ground_point((round(v.base[0] + 4 * dx / norm),
                               round(v.base[1] + 4 * dy / norm)))

    def _deploy(self, v):
        orders = []
        for unit in v.units:
            if unit.get("type") != "mcv" or not isinstance(unit.get("id"), int):
                continue
            uid, point = unit["id"], pos(unit)
            if any(uid in o.get("units", []) for o in v.pending_orders
                   if o.get("cmd") in {"deploy", "move"}):
                continue
            previous = self._deploy_attempts.get(uid)
            if previous and point == previous[0] and v.now - previous[1] >= 4:
                # A stationary MCV which has not unfolded may be blocked.
                # Move a few cells, then retry; never assume deploy succeeded.
                n = previous[2]
                offsets = ((3, 0), (0, 3), (-3, 0), (0, -3))
                dx, dy = offsets[n % len(offsets)]
                dest = v.ground_point((point[0] + dx, point[1] + dy)) if point else None
                if dest and tuple(dest) != point:
                    orders.append(Intent({"cmd": "move", "units": [uid], "to": dest},
                                         priority=95, cooldown=3, key=f"mcv-clear:{uid}"))
                    self._deploy_attempts[uid] = (point, v.now, n + 1)
                    continue
            if previous and point == previous[0] and not unit.get("idle", True):
                continue
            orders.append(Intent({"cmd": "deploy", "units": [uid]}, priority=95,
                                 cooldown=2, key=f"deploy:{uid}"))
            if previous is None or point != previous[0]:
                self._deploy_attempts[uid] = (point, v.now, previous[2] if previous else 0)
        return orders

    def propose(self, v):
        intents = self._deploy(v)
        budget = max(0.0, v.funds - _reserved(v))
        emergency_harvester = (v.count("harv") == 0 and v.total("harv") == 0
                               and v.available("harv", "train")
                               and not v.queue_busy("Vehicle") and v.remaining > 50)
        # When income has stopped, optional construction/infantry must not
        # consume the replacement harvester's budget first.
        harvester_reserve = min(budget, _cost(v, "harv")) if emergency_harvester else 0
        budget -= harvester_reserve
        # Reserve power for already-queued drains. Unfinished power plants do
        # not yet supply usable electricity, so their positive power is ignored.
        projected_power = v.power_surplus
        future_builds = [str(p.get("item", "")).lower() for p in v.production
                         if str(p.get("queue", v.queue(str(p.get("item", ""))))).lower()
                         in {"building", "defense"}]
        future_builds += [str(o.get("item", "")).lower() for o in v.pending_orders
                          if o.get("cmd") == "build"]
        for item in future_builds:
            power = _power(v, item)
            projected_power += min(0, power) if power is not None else 0
        near = [e for e in v.enemies if pos(e) and v.base
                and distance(pos(e), v.base) <= 19
                and e.get("type") not in _NONCOMBAT]
        armor = sum(e.get("type") in _VEHICLES for e in v.enemies)
        def airborne(e):
            return e.get("type") in _AIR or v.queue(str(e.get("type", ""))).lower() == "aircraft"
        air = sum(airborne(e) for e in v.enemies)
        air_near = any(airborne(e) for e in near)
        infantry_threat = sum(str(e.get("type", "")).startswith("e") for e in near)
        target = min((pos(e) for e in near), key=lambda p: distance(p, v.base), default=None)
        home_danger = bool(near)

        # Placement is free and remains urgent even at the end of the match.
        ready = {str(p.get("item", "")).lower() for p in v.production if p.get("ready")}
        for entry in v.legal.get("place", []) or []:
            name = entry if isinstance(entry, str) else (entry.get("item", entry.get("type", ""))
                                                        if isinstance(entry, dict) else "")
            if isinstance(name, str) and name:
                ready.add(name.lower())
        for item in sorted(ready):
            if not item or _pending(v, "place", item):
                continue
            order = {"cmd": "place", "item": item}
            at = self._placement(v, item, target if item in _DEFENSES else None)
            if at is not None:
                order["at"] = at
            intents.append(Intent(order, priority=96, cooldown=0.6, key=f"place:{item}"))

        # Preserve important structures, but do not enable repair everywhere
        # during an opening with insufficient resources for the next building.
        damaged = sorted((b for b in v.buildings if 0 < _number(b.get("hp"), 100) < 85
                          and not b.get("repairing") and isinstance(b.get("id"), int)),
                         key=lambda b: (b.get("type") not in {"fact", "proc", "powr", "weap"}, b.get("hp", 100)))
        if v.funds >= 150:
            for b in damaged[:3]:
                if home_danger or _number(b.get("hp"), 100) < 60 or v.funds >= 1200:
                    intents.append(Intent({"cmd": "repair", "building": b["id"], "on": True},
                                          priority=99 if home_danger else 75,
                                          cooldown=3, key=f"repair:{b['id']}"))
        for u in v.units:
            if u.get("type") == "harv" and u.get("idle") and isinstance(u.get("id"), int):
                intents.append(Intent({"cmd": "harvest", "units": [u["id"]]},
                                      priority=82, cooldown=4, key=f"harvest:{u['id']}"))

        barracks = "tent" if v.available("tent", "build") or v.has("tent") else "barr"
        has_barracks = v.total("tent") + v.total("barr") > 0
        far = bool(v.base and v.enemy_base and distance(v.base, v.enemy_base) >= 70)
        harvs = v.count("harv")
        total_harvs = v.total("harv")
        owned_combat = sum(u.get("type") not in _NONCOMBAT for u in v.units)
        building = None
        build_priority = 80

        if (v.has("fact") and not v.queue_busy("Building")
                and not any(v.queue(item).lower() == "building" for item in ready)):
            if v.total("powr") == 0 or v.power_surplus < 0:
                if v.total("powr") == v.count("powr"):
                    building, build_priority = "powr", 91
            elif not has_barracks and (not far or v.total("proc") > 0 or home_danger):
                building = barracks
            elif v.total("proc") == 0:
                building = "proc"
            elif (harvs == 0 and total_harvs == 0 and not v.available("harv", "train")
                  and v.total("proc") == v.count("proc")):
                # No vehicle producer remains: another refinery supplies its
                # own harvester, and costs less than a replacement factory.
                building = "proc"
            elif not has_barracks:
                building = barracks
            elif v.total("weap") == 0:
                building = "weap"
            elif (v.now >= 125 and v.remaining > 240 and v.total("proc") < 2
                  and not home_danger and budget >= _cost(v, "proc") + 300):
                building = "proc"
            elif (v.now >= 180 and v.remaining > 240 and v.total("fix") == 0
                  and v.count("proc") >= 2 and harvs >= 2 and not home_danger
                  and _power(v, "fix") is not None and budget >= _cost(v, "fix") + 600):
                building = "fix"

            if building:
                drain = _power(v, building)
                if drain is not None and drain < 0 and projected_power < -drain:
                    building = "powr" if v.total("powr") == v.count("powr") else None
                    build_priority = 91
                if building and v.total(building) > v.count(building):
                    building = None
                if building:
                    cost = _cost(v, building)
                    end_ok = v.remaining > _build_time(v, building, "build") + 35
                    if (v.available(building, "build") and cost > 0 and budget >= cost
                            and (end_ok or (building == "powr" and v.power_surplus < 0
                                            and v.remaining > _build_time(v, building, "build") + 5))):
                        intents.append(Intent({"cmd": "build", "item": building},
                                              priority=build_priority, cooldown=1, key=f"build:{building}"))
                        budget -= cost
                        power = _power(v, building)
                        projected_power += min(0, power) if power is not None else 0

        # One home defense can punish small raids; its cost and power must be
        # supplied by runtime config, never inferred from another OpenRA build.
        if (home_danger and not v.queue_busy("Defense") and v.remaining > 40
                and not any(v.queue(item).lower() == "defense" for item in ready)):
            choices = (["sam", "agun"] if air_near else
                       ["gun", "tsla", "pbox", "ftur"] if armor >= 2 else
                       ["pbox", "ftur", "gun", "tsla"])
            # Ground defenses do not satisfy the need for an AA emplacement.
            existing = sum(v.total(x) for x in ({"sam", "agun"} if air_near else _DEFENSES))
            if existing < (2 if len(near) >= 6 else 1):
                for item in choices:
                    cost, power = _cost(v, item), _power(v, item)
                    if (v.available(item, "build") and cost > 0 and budget >= cost + 100
                            and power is not None and projected_power + power >= 0
                            and v.remaining > _build_time(v, item, "build") + 15):
                        intents.append(Intent({"cmd": "build", "item": item}, priority=89,
                                              cooldown=1, key=f"build:{item}"))
                        budget -= cost
                        break

        # Keep the initial scouting/defense commitment small.  After vehicles
        # unlock, a mixed infantry screen supplements them rather than spending
        # every credit in batches of ten riflemen.
        rifle_cap = 4 if not far else 2
        if v.has("weap"):
            rifle_cap = min(18, max(8, 4 + 2 * sum(v.count(t) for t in _VEHICLES)))
        if home_danger:
            rifle_cap = max(rifle_cap, 8)
        if not v.queue_busy("Infantry") and v.remaining > 12:
            item = None
            if ((armor >= 2 or air) and v.available("e3", "train") and _cost(v, "e3") > 0
                    and v.total("e3") < max(3, v.count("e1") // 2)):
                item = "e3"
            elif v.total("e1") < rifle_cap:
                item = "e1"
            if item and v.available(item, "train"):
                cost = _cost(v, item)
                # If the factory is the next unmet step, stop optional rifle
                # growth while saving for it, after securing a minimal screen.
                saving_factory = (v.has("proc") and v.total("weap") == 0
                                  and v.count("e1") >= (2 if not far else 1)
                                  and not home_danger)
                reserve = _cost(v, "weap") if saving_factory and not air else (100 if v.has("weap") else 0)
                if cost > 0 and budget >= cost + reserve and v.remaining > _build_time(v, item, "train") + 8:
                    intents.append(Intent({"cmd": "train", "item": item}, priority=72 if home_danger else 60,
                                          cooldown=0.6, key=f"train:{item}"))
                    budget -= cost

        budget += harvester_reserve
        if not v.queue_busy("Vehicle") and v.remaining > 25:
            item = None
            priority = 60
            # Losing the yard is recoverable only if runtime explicitly permits
            # a replacement MCV; no undocumented undeploy/repair abilities.
            if harvs == 0 and total_harvs == 0 and v.available("harv", "train"):
                item, priority = "harv", 93
            elif (not v.has("fact") and v.total("mcv") == 0 and v.remaining > 180
                    and v.available("mcv", "train") and _cost(v, "mcv") > 0):
                item, priority = "mcv", 92
            else:
                goal = 3 if v.count("proc") >= 2 and v.now > 160 else 1
                if (v.count("proc") >= 2 and v.now > 420 and owned_combat >= 20
                        and v.funds < 2500 and v.remaining > 300):
                    goal = 4
                if (total_harvs < goal and v.remaining > 240 and not home_danger
                        and v.available("harv", "train") and budget >= _cost(v, "harv") + 300):
                    item, priority = "harv", 78
                else:
                    if armor >= 2:
                        choices = ["3tnk", "2tnk", "1tnk", "ftrk", "apc", "jeep"]
                    elif infantry_threat >= 3:
                        choices = ["ftrk", "apc", "jeep", "1tnk", "3tnk", "2tnk"]
                    else:
                        choices = ["3tnk", "2tnk", "1tnk", "ftrk", "apc", "jeep"]
                    item = next((x for x in choices if v.available(x, "train")
                                 and _cost(v, x) > 0 and budget >= _cost(v, x) + 100), None)
            if item and v.available(item, "train"):
                cost = _cost(v, item)
                if cost > 0 and budget >= cost and v.remaining > _build_time(v, item, "train") + 15:
                    intents.append(Intent({"cmd": "train", "item": item}, priority=priority,
                                          cooldown=0.8, key=f"train:{item}"))
        return intents
