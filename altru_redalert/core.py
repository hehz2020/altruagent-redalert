"""Order arbitration, acknowledgements and the deterministic decision loop.

This is a tested baseline controller, not a claim of tournament strength.
Production has a pending-intent ledger. Unknown transport outcomes are
reconciled against fresh observations rather than retried immediately.
"""
from __future__ import annotations

from collections import Counter, deque
import json
from typing import Any

from .model import Intent, View, living, number, pos


FIELDS = {
    "move": ({"units", "to"}, {"queued"}),
    "attack_move": ({"units", "to"}, {"queued"}),
    "attack": ({"units"}, {"target", "to", "queued"}),
    "stop": ({"units"}, set()),
    "deploy": ({"units"}, set()),
    "guard": ({"units", "target"}, {"queued"}),
    "harvest": ({"units"}, {"to", "queued"}),
    "set_stance": ({"units", "stance"}, set()),
    "build": ({"item"}, set()),
    "train": ({"item"}, {"count"}),
    "place": ({"item"}, {"at"}),
    "cancel": ({"item"}, set()),
    "repair": ({"building"}, {"on"}),
    "power_toggle": ({"building"}, {"on"}),
    "rally": ({"building", "to"}, set()),
    "set_primary": ({"building"}, set()),
}
PRODUCTION = {"build", "train"}
TRACKED = PRODUCTION | {"place", "deploy", "cancel"}


def fingerprint(order: dict) -> str:
    return json.dumps(order, sort_keys=True, separators=(",", ":"))


def validate_order(order: Any, v: View) -> dict | None:
    """Validate against the current player view before sending any command."""
    if not isinstance(order, dict) or order.get("cmd") not in FIELDS:
        return None
    o = dict(order)
    cmd = o["cmd"]
    required, optional = FIELDS[cmd]
    if not required <= o.keys() or o.keys() - required - optional - {"cmd"}:
        return None
    units = {a["id"]: a for a in v.units}
    buildings = {a["id"]: a for a in v.buildings}
    enemies = {a["id"]: a for a in v.enemies + v.enemy_buildings}
    if "units" in o:
        ids = o["units"]
        if not isinstance(ids, (list, tuple)):
            return None
        own = {**units, **buildings} if cmd in {"attack", "stop", "set_stance", "guard"} else units
        ids = list(dict.fromkeys(i for i in ids if isinstance(i, int) and not isinstance(i, bool) and i in own))
        if cmd == "deploy":
            ids = [i for i in ids if str(units[i].get("type", "")).lower() == "mcv"]
            if isinstance(v.legal.get("deploy"), list):
                candidates = [a.get("id") if isinstance(a, dict) else a for a in v.legal["deploy"]]
                allowed = {i for i in candidates if isinstance(i, int) and not isinstance(i, bool)}
                ids = [i for i in ids if i in allowed]
        if cmd == "harvest":
            ids = [i for i in ids if str(units[i].get("type", "")).lower() == "harv"]
        if not ids:
            return None
        o["units"] = ids
    if "building" in o and (not isinstance(o["building"], int) or isinstance(o["building"], bool) or o["building"] not in buildings):
        return None
    for field in ("to", "at"):
        if field in o:
            p = o[field]
            if (not isinstance(p, (list, tuple)) or len(p) != 2
                    or any(isinstance(x, bool) or not isinstance(x, int) for x in p)
                    or v.clamp(p) != list(p)):
                return None
            o[field] = list(p)
    if cmd == "attack":
        if ("target" in o) == ("to" in o):
            return None
        if "target" in o and (not isinstance(o["target"], int) or isinstance(o["target"], bool) or o["target"] not in enemies):
            return None
    if cmd == "guard" and (not isinstance(o["target"], int) or isinstance(o["target"], bool) or o["target"] not in {**units, **buildings}):
        return None
    if "item" in o:
        if not isinstance(o["item"], str):
            return None
        o["item"] = o["item"].lower()
        if cmd in PRODUCTION and not v.available(o["item"], cmd):
            return None
        if cmd == "place" and o["item"] not in v.ready_to_place():
            return None
    if "count" in o:
        limit = int(number(v.raw.get("limits", {}).get("max_train_count", 10), 10))
        if isinstance(o["count"], bool) or not isinstance(o["count"], int) or not 1 <= o["count"] <= min(10, max(1, limit)):
            return None
    if "on" in o and not isinstance(o["on"], bool):
        return None
    if "queued" in o and not isinstance(o["queued"], bool):
        return None
    if cmd == "set_stance" and o["stance"] not in {"hold_fire", "return_fire", "defend", "attack_anything"}:
        return None
    return o


class Controller:
    """One fresh instance per match; no cross-match opponent memory."""

    def __init__(self):
        from .economy import Economy
        from .combat import Military
        self.economy = Economy()
        self.military = Military()
        self.stats: Counter = Counter()
        self._records: dict[int, dict] = {}
        self._by_version: dict[int, list[int]] = {}
        self._by_batch: dict[Any, list[int]] = {}
        self._cooldowns: dict[str, float] = {}
        self._failures: Counter = Counter()
        self._seen_problem: set[tuple] = set()
        self._problem_order = deque()
        self._serial = 0
        self._last_ids: list[int] = []
        self._last_tick: int | None = None
        self._now = 0.0
        self._session: str | None = None

    def _settle(self, ident: int, row: dict):
        r = self._records.get(ident)
        if r is None:
            return
        status = row.get("status", "")
        if status == "pending":
            return
        if r.get("verdict") == status:
            return
        r["verdict"] = status
        cmd = r["order"]["cmd"]
        key = r["key"]
        if status in {"rejected", "lost"}:
            r["pending"] = False
            self.stats["engine_rejected" if status == "rejected" else "engine_lost"] += 1
            self._failures[key] += 1
            # Actual loss can be retried; a persistent invalid action backs off.
            delay = 0.6 if status == "lost" else min(16.0, 2.0 ** min(self._failures[key], 4))
            self._cooldowns[key] = max(self._cooldowns.get(key, 0), self._now + delay)
        elif status in {"ok", "partial"}:
            self.stats["engine_" + status] += 1
            self._failures.pop(key, None)
            if cmd not in TRACKED:
                r["pending"] = False
            if row.get("reason") == "no_feedback":
                r["uncertain"] = True

    def on_result(self, result: dict):
        """Immediate SDK callback. Final engine verdicts arrive in later state."""
        if not isinstance(result, dict):
            return
        code = result.get("error")
        if code:
            self.stats["batch_errors"] += 1
            # These documented errors mean the batch was not applied.
            known_unsent = {"INVALID_ACTION", "STALE_STATE", "NOT_YOUR_TURN",
                            "RUNTIME_TEMPORARILY_UNAVAILABLE", "GAME_ALREADY_COMPLETE"}
            if code in known_unsent:
                for ident in self._last_ids:
                    self._settle(ident, {"status": "rejected", "reason": code})
            return
        if "batch" in result and isinstance(result["batch"], (int, str)):
            self._by_batch[result["batch"]] = list(self._last_ids)
        for row in result.get("results") or []:
            if isinstance(row, dict):
                index = row.get("index")
                if isinstance(index, int) and 0 <= index < len(self._last_ids):
                    self._settle(self._last_ids[index], row)

    def _reconcile(self, v: View):
        latest = v.raw.get("last_orders") or {}
        if isinstance(latest, dict):
            version = latest.get("state_version")
            ids = self._by_version.get(version, []) if isinstance(version, int) else []
            batch = latest.get("batch")
            if isinstance(batch, (int, str)):
                if ids:
                    self._by_batch[batch] = ids
                else:
                    ids = self._by_batch.get(batch, [])
            for row in latest.get("results") or []:
                if isinstance(row, dict) and isinstance(row.get("index"), int) and 0 <= row["index"] < len(ids):
                    self._settle(ids[row["index"]], row)
        for row in v.raw.get("recent_order_problems") or []:
            if not isinstance(row, dict):
                continue
            sig = (row.get("batch"), row.get("index"), row.get("status"), row.get("reason"))
            if sig in self._seen_problem:
                continue
            self._seen_problem.add(sig)
            self._problem_order.append(sig)
            if len(self._problem_order) > 256:
                self._seen_problem.discard(self._problem_order.popleft())
            ids = self._by_batch.get(row.get("batch"), [])
            index = row.get("index")
            if isinstance(index, int) and 0 <= index < len(ids):
                self._settle(ids[index], row)
        for r in self._records.values():
            if not r["pending"]:
                continue
            o = r["order"]
            item = o.get("item", "")
            cmd = o["cmd"]
            reflected = False
            if cmd in PRODUCTION:
                # A batch is not fully confirmed merely because its first
                # unit appeared. Reserve only the portion not yet represented
                # by observed actors or queued items, avoiding double counting.
                new_ids = {a["id"] for a in v.units + v.buildings
                           if str(a.get("type", "")).lower() == item} - r["baseline_ids"]
                r["created_ids"].update(new_ids)
                represented = len(r["created_ids"]) + max(0, v.production_count(item) - r["baseline_queued"])
                r["remaining_count"] = max(0, o.get("count", 1) - represented)
                reflected = r["remaining_count"] == 0
            elif cmd == "place":
                reflected = v.count(item) > r["baseline_count"]
            elif cmd == "cancel":
                # cancel removes one queued item, not the entire batch. Wait
                # for a smaller observed queue before cancelling another.
                reflected = v.production_count(item) < r["baseline_queued"]
            elif cmd == "deploy":
                reflected = any(u not in {a["id"] for a in v.units} for u in o["units"])
            if reflected:
                r["pending"] = False
                self.stats["observed_confirmations"] += 1
            elif v.now - r["sent_at"] >= r["confirm_timeout"] and v.tick > r["tick"]:
                # Advancing observations without the full expected result
                # eventually release the reservation. Batches get a longer
                # build-time-based window. This is bounded recovery, not an
                # exactly-once delivery guarantee.
                r["pending"] = False
                self.stats["unconfirmed_expiries"] += 1
                self._cooldowns[r["key"]] = max(self._cooldowns.get(r["key"], 0), v.now + 1)
        if len(self._records) > 512:
            remove = [i for i, r in self._records.items() if not r["pending"]][:256]
            for i in remove:
                self._records.pop(i, None)
            self._by_version = {k: ids for k, ids in self._by_version.items() if any(i in self._records for i in ids)}
            self._by_batch = {k: ids for k, ids in self._by_batch.items() if any(i in self._records for i in ids)}
        if len(self._cooldowns) > 2048:
            self._cooldowns = {k: until for k, until in self._cooldowns.items() if until > v.now}

    def decide(self, raw: dict, config: dict | None = None) -> dict | None:
        if not isinstance(raw, dict):
            return None
        session = raw.get("session_id")
        if self._session is not None and session and session != self._session:
            self.__init__()
        if session:
            self._session = session
        if (raw.get("is_terminal") or raw.get("phase") not in {None, "playing"}
                or raw.get("is_current_actor") is False or not isinstance(raw.get("observation"), dict)):
            return None
        v = View(raw, config)
        self._now = v.now
        self._reconcile(v)
        if self._last_tick == v.tick:
            return None
        self._last_tick = v.tick
        self.stats["observations"] += 1
        pending = [{**r["order"], "count": r["remaining_count"]}
                   if r["order"]["cmd"] == "train" else r["order"]
                   for r in self._records.values() if r["pending"]]
        v.pending_orders = pending
        candidates = self.economy.propose(v) + self.military.propose(v)
        candidates.sort(key=lambda p: p.priority, reverse=True)
        limits = raw.get("limits") or {}
        max_orders = min(20, max(1, int(number(limits.get("max_orders_per_batch"), 20))))
        max_units = min(50, max(1, int(number(limits.get("max_units_per_order"), 50))))
        max_expanded = min(200, max(1, int(number(limits.get("max_engine_commands_per_batch",
                                             limits.get("max_commands_per_batch")), 200))))
        orders: list[dict] = []
        meta: list[tuple[Intent, str]] = []
        claimed: set[int] = set()
        seen: set[str] = set()
        queues: set[str] = set()
        expanded = 0
        pending_fingerprints = {fingerprint(o) for o in pending}
        for intent in candidates:
            o = validate_order(intent.order, v)
            if o is None:
                self.stats["locally_filtered"] += 1
                continue
            fp = fingerprint(o)
            key = intent.key or fp
            if fp in seen or fp in pending_fingerprints or self._cooldowns.get(key, 0) > v.now:
                continue
            if o["cmd"] in PRODUCTION:
                queue = v.queue(o["item"])
                if queue and (queue in queues or any(p.get("cmd") in PRODUCTION and v.queue(p.get("item", "")) == queue for p in pending)):
                    continue
            chunks = [o]
            if "units" in o:
                ids = [i for i in o["units"] if i not in claimed]
                chunks = [{**o, "units": ids[k:k + max_units]} for k in range(0, len(ids), max_units)]
            used = False
            for chunk in chunks:
                n = len(chunk["units"]) if "units" in chunk else chunk.get("count", 1)
                if len(orders) >= max_orders or expanded + n > max_expanded:
                    continue
                orders.append(chunk)
                meta.append((intent, key))
                expanded += n
                claimed.update(chunk.get("units", []))
                if "building" in chunk:
                    # Repairs and rally points may coexist, so buildings are
                    # intentionally not claimed as movement actors here.
                    pass
                used = True
            if used:
                seen.add(fp)
                if o["cmd"] in PRODUCTION and v.queue(o["item"]):
                    queues.add(v.queue(o["item"]))
                self._cooldowns[key] = v.now + max(0, number(intent.cooldown))
        if not orders:
            return None
        self._last_ids = []
        for o, (intent, key) in zip(orders, meta):
            self._serial += 1
            count = o.get("count", 1)
            duration = number(v.spec(o.get("item", "")).get("build_time_s"), 30)
            self._records[self._serial] = {
                "order": o, "key": key, "pending": o["cmd"] in TRACKED,
                "sent_at": v.now, "tick": v.tick,
                "baseline_count": v.count(o.get("item", "")), "verdict": None,
                "baseline_ids": {a["id"] for a in v.units + v.buildings
                                 if str(a.get("type", "")).lower() == o.get("item", "")},
                "baseline_queued": v.production_count(o.get("item", "")),
                "created_ids": set(), "remaining_count": count,
                "confirm_timeout": max(8.0, min(120.0, duration * count * 2 + 8)) if count > 1 else 8.0,
            }
            self._last_ids.append(self._serial)
        self._by_version[int(number(raw.get("state_version"), v.tick))] = list(self._last_ids)
        self.stats["batches"] += 1
        self.stats["orders"] += len(orders)
        self.military.mark_sent(orders, v.now)
        return {"type": "orders", "orders": orders}
