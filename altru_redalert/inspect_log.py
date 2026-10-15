from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path


def summarize(path):
    commands, errors, verdicts = Counter(), Counter(), Counter()
    first_owned, samples, batches, waits, bad_lines = {}, 0, 0, 0, 0
    first_time = last_time = None
    last_economy = last_military = None
    low_power_samples = 0
    delayed_seen = set()
    for line in Path(path).open(encoding="utf-8"):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            bad_lines += 1
            continue
        if entry.get("type") == "result":
            result = entry.get("result") or {}
            if result.get("error"):
                errors[str(result["error"])] += 1
            for row in result.get("results") or []:
                verdicts["immediate_" + str(row.get("status", "unknown"))] += 1
            continue
        if entry.get("type") != "state":
            continue
        raw = entry.get("raw") or {}
        obs = raw.get("observation") or {}
        now = (raw.get("time") or {}).get("game_seconds", obs.get("tick", 0) / 25)
        first_time = now if first_time is None else first_time
        last_time = now
        samples += 1
        decision = entry.get("decision")
        if decision:
            batches += 1
            for o in decision.get("orders") or []:
                label = o.get("cmd", "unknown")
                if o.get("item"):
                    label += ":" + o["item"]
                commands[label] += 1
        else:
            waits += 1
        for a in (obs.get("units") or []) + (obs.get("buildings") or []):
            if not a.get("wreck") and a.get("type"):
                first_owned.setdefault(a["type"], now)
        eco = obs.get("economy") or {}
        if eco.get("power_drained", 0) > eco.get("power_provided", 0):
            low_power_samples += 1
        last_economy = eco
        last_military = obs.get("military") or {}
        latest = raw.get("last_orders") or {}
        rows = [dict(row, batch=latest.get("batch")) for row in latest.get("results") or []]
        rows += raw.get("recent_order_problems") or []
        for row in rows:
            status = row.get("status")
            key = (row.get("batch"), row.get("index"), status)
            if row.get("batch") is not None and status != "pending" and key not in delayed_seen:
                delayed_seen.add(key)
                verdicts["final_" + str(status)] += 1
    return {
        "state_samples": samples, "decision_batches": batches, "wait_decisions": waits,
        "first_game_second": first_time, "last_game_second": last_time,
        "low_power_sample_fraction": low_power_samples / samples if samples else None,
        "first_observed_owned_at_seconds": first_owned,
        "command_counts": dict(commands), "batch_errors": dict(errors),
        "observed_verdict_counts": dict(verdicts), "last_economy": last_economy,
        "last_military": last_military, "unreadable_lines": bad_lines,
        "note": "Recorded observations only. WAIT often means productive orders are running. "
                "Missing final callbacks cannot establish victory or defeat.",
    }


def main():
    parser = argparse.ArgumentParser(description='Summarize an opt-in player-view JSONL log; never connect to a server.\n\nThese are recorded actions, not counterfactual replay or simulated win rates.\nRun: python -m altru_redalert.inspect_log path/to/match.jsonl\n')
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.path), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
