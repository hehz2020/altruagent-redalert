from __future__ import annotations

from dataclasses import dataclass
from math import hypot, inf, isfinite
from typing import Any


FALLBACKS = {
    "powr": dict(cost=300, build_time_s=7.2, power=100, queue="Building"),
    "tent": dict(cost=500, build_time_s=12, power=-20, queue="Building"),
    "barr": dict(cost=500, build_time_s=12, power=-20, queue="Building"),
    "proc": dict(cost=1400, build_time_s=33.6, power=-30, queue="Building"),
    "weap": dict(cost=2000, build_time_s=48, power=-30, queue="Building"),
    "fix": dict(cost=1200, queue="Building"),
    "e1": dict(cost=100, build_time_s=2.4, queue="Infantry"),
    "harv": dict(cost=1100, build_time_s=26.4, queue="Vehicle"),
    "1tnk": dict(cost=700, queue="Vehicle"),
    "jeep": dict(cost=500, queue="Vehicle"),
    "apc": dict(cost=850, queue="Vehicle"),
    "ftrk": dict(cost=600, queue="Vehicle"),
}


def number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        value = float(value)
    except (ValueError, TypeError):
        return default
    return value if isfinite(value) else default


def pos(actor: Any) -> tuple[int, int] | None:
    if isinstance(actor, dict):
        pair = actor.get("x"), actor.get("y")
    elif isinstance(actor, (list, tuple)) and len(actor) == 2:
        pair = actor
    else:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) for v in pair):
        return None
    return int(pair[0]), int(pair[1])


def distance(a: Any, b: Any) -> float:
    a, b = pos(a), pos(b)
    return hypot(a[0] - b[0], a[1] - b[1]) if a is not None and b is not None else inf


def living(actor: Any) -> bool:
    return (isinstance(actor, dict) and isinstance(actor.get("id"), int)
            and not isinstance(actor.get("id"), bool) and not actor.get("wreck")
            and not str(actor.get("type", "")).lower().endswith(("husk", "wreck"))
            and number(actor.get("hp", 100)) > 0)


def _actors(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [a for a in value if living(a)]


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _names(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    result = set()
    for entry in value:
        name = entry if isinstance(entry, str) else (
            entry.get("item", entry.get("type", "")) if isinstance(entry, dict) else "")
        if isinstance(name, str) and name:
            result.add(name.lower())
    return result


@dataclass
class Intent:
    order: dict
    priority: int = 50
    cooldown: float = 1.0
    key: str | None = None


class View:


    def __init__(self, raw: dict, config: dict | None = None,
                 pending_orders: list[dict] | None = None):
        self.raw = _dict(raw)
        self.config = _dict(config)
        self.obs = _dict(self.raw.get("observation"))
        self.legal = _dict(self.raw.get("legal_actions"))
        self.pending_orders = pending_orders or []
        self.tick = int(number(self.obs.get("tick", self.raw.get("state_version", 0))))
        self.now = number(_dict(self.raw.get("time")).get("game_seconds"), self.tick / 25)
        self.units = _actors(self.obs.get("units"))
        self.buildings = _actors(self.obs.get("buildings"))
        self.enemies = _actors(self.obs.get("visible_enemies"))
        self.enemy_buildings = _actors(self.obs.get("visible_enemy_buildings"))
        self.production = [p for p in (self.obs.get("production") or []) if isinstance(p, dict)]
        self.rules = _dict(self.config.get("rules"))
        self.catalog = {k: dict(v) for k, v in FALLBACKS.items()}
        for section in ("units", "buildings"):
            entries = self.rules.get(section, {})
            if isinstance(entries, dict):
                pairs = entries.items()
            elif isinstance(entries, list):
                pairs = ((e.get("type", e.get("id", "")), e)
                         for e in entries if isinstance(e, dict))
            else:
                pairs = ()
            for key, data in pairs:
                if isinstance(key, str) and isinstance(data, dict):
                    name = key.lower()
                    self.catalog[name] = {**self.catalog.get(name, {}), **data}
        self.map = _dict(self.raw.get("map")) or _dict(self.obs.get("map"))
        self.map_id = str(self.map.get("id", ""))
        self.map_info = _dict(_dict(self.rules.get("maps")).get(self.map_id))
        b = self.map.get("bounds", self.map_info.get("bounds"))
        self.bounds = tuple(b) if (isinstance(b, (list, tuple)) and len(b) == 4
                                  and all(isinstance(x, int) and not isinstance(x, bool) for x in b)
                                  and b[2] > 0 and b[3] > 0) else None
        self.base = pos(self.obs.get("base_center"))
        if self.base is None:
            candidates = [a for a in self.buildings if a.get("type") == "fact"]
            candidates = candidates or self.buildings or self.units
            self.base = next((pos(a) for a in candidates if pos(a) is not None), None)
        self.enemy_base = pos(self.legal.get("enemy_base"))
        if self.enemy_base is None and self.base is not None:
            spawns = [pos(p) for p in (self.map_info.get("spawns") or [])]
            spawns = [p for p in spawns if p is not None]
            if len(spawns) >= 2:
                self.enemy_base = max(spawns, key=lambda p: distance(p, self.base))
        economy = _dict(self.obs.get("economy"))
        self.funds = max(0, number(economy.get("cash")) + number(economy.get("ore")))
        self.power_surplus = number(economy.get("power_provided")) - number(economy.get("power_drained"))
        remaining = _dict(self.raw.get("time")).get("remaining_seconds")
        self.remaining = max(0, number(remaining)) if remaining is not None else inf
        self.military = _dict(self.obs.get("military"))

    def spec(self, item: str) -> dict:
        return self.catalog.get(str(item).lower(), {})

    def cost(self, item: str) -> float:
        return max(0, number(self.spec(item).get("cost")))

    def queue(self, item: str) -> str:
        return str(self.spec(item).get("queue", ""))

    def count(self, item: str) -> int:
        return sum(str(a.get("type", "")).lower() == item.lower() for a in self.units + self.buildings)

    def production_count(self, item: str) -> int:

        return sum(max(1, int(number(p.get("count", 1), 1)))
                   for p in self.production
                   if str(p.get("item", "")).lower() == item.lower())

    def ready_to_place(self) -> set[str]:

        if isinstance(self.legal.get("place"), list):
            return {item for item in _names(self.legal["place"])
                    if not self.queue(item) or self.queue(item).lower() in {"building", "defense"}}
        return {str(p.get("item", "")).lower() for p in self.production
                if p.get("ready") and str(p.get("queue", self.queue(str(p.get("item", ""))))).lower()
                in {"building", "defense"}}

    def total(self, item: str) -> int:
        item = item.lower()
        queued = self.production_count(item)
        pending = sum(max(1, int(number(o.get("count", 1), 1)))
                      for o in self.pending_orders if o.get("cmd") in ("build", "train")
                      and str(o.get("item", "")).lower() == item)
        return self.count(item) + queued + pending

    def has(self, item: str) -> bool:
        return self.count(item) > 0

    def available(self, item: str, kind: str = "train") -> bool:
        item = item.lower()
        if isinstance(self.legal.get(kind), list):
            return item in _names(self.legal[kind])
        return item in _names(self.obs.get("available_production"))

    def queue_busy(self, queue: str) -> bool:
        return (any(str(p.get("queue", self.queue(str(p.get("item", ""))))).lower() == queue.lower()
                    for p in self.production)
                or any(o.get("cmd") in ("build", "train")
                       and self.queue(str(o.get("item", ""))).lower() == queue.lower()
                       for o in self.pending_orders))

    def clamp(self, point: Any) -> list[int] | None:
        point = pos(point)
        if self.bounds is None or point is None:
            return None
        x, y, w, h = self.bounds
        return [max(x, min(x + w - 1, point[0])), max(y, min(y + h - 1, point[1]))]

    def ground_point(self, point: Any) -> list[int] | None:
        target = self.clamp(point)
        if target is None:
            return None
        layout = _dict(self.map_info.get("layout"))
        rows = layout.get("rows")
        origin = pos(layout.get("origin"))
        if not isinstance(rows, list) or origin is None:
            return target
        for radius in range(6):
            offsets = [(dx, dy) for dy in range(-radius, radius + 1)
                       for dx in range(-radius, radius + 1) if max(abs(dx), abs(dy)) == radius]
            offsets.sort(key=lambda d: d[0] * d[0] + d[1] * d[1])
            for dx, dy in offsets:
                candidate = [target[0] + dx, target[1] + dy]
                if self.clamp(candidate) != candidate:
                    continue
                i, j = candidate[1] - origin[1], candidate[0] - origin[0]
                if 0 <= i < len(rows) and isinstance(rows[i], str) and 0 <= j < len(rows[i]):
                    if rows[i][j] not in "~^T# ":
                        return candidate
        return None
