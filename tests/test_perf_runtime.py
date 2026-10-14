"""Offline checks for real-time pacing and secret-free phase diagnostics."""
from __future__ import annotations

import json

import pytest

from altruagent import WAIT
from altruagent.runner import run_game
from altru_redalert.adapter import RedAlertAgent
from tests.test_realtime import CONFIG, ORDERS, RED_ALERT, Recorder, RealtimeFakeGame, accepted, ra_state
from tests.test_runner import result_dict, terminal_state


@pytest.mark.parametrize("interval, expected", [(0.2, 0.2), (0.8, 0.8), (0, 0.2), (float("nan"), 0.2)])
def test_old_server_realtime_fallback_respects_server_minimum(interval, expected):
    game = RealtimeFakeGame(CONFIG)
    game.supports_wait = False
    game.queue_state(ra_state(pacing={"mode": "realtime", "min_batch_interval_s": interval}), terminal_state())
    game.queue_result(result_dict())
    sleeps = []
    run_game(game, RED_ALERT, Recorder(WAIT), sleep=sleeps.append)
    assert sleeps == [expected]


def test_timing_separates_state_decision_send_without_extra_realtime_sleep():
    clock = [0.0]

    class TimedGame(RealtimeFakeGame):
        def get_state(self):
            clock[0] += 0.4
            return super().get_state()

        def get_game_config(self, game_type):
            clock[0] += 0.1
            return super().get_game_config(game_type)

        def play_action(self, **kwargs):
            clock[0] += 0.3
            return super().play_action(**kwargs)

    class TimedAgent(Recorder):
        def __init__(self):
            super().__init__(ORDERS)
            self.timings = []

        def choose_action(self, state, context):
            clock[0] += 0.02
            return super().choose_action(state, context)

        def on_runtime_timing(self, record, context):
            self.timings.append(record)

    game = TimedGame(CONFIG).queue_state(ra_state(time={"game_seconds": 15}), terminal_state())
    game.queue_play_action(accepted(("build", "pending", "pending"))).queue_result(result_dict())
    agent = TimedAgent()
    sleeps = []
    run_game(game, RED_ALERT, agent, sleep=sleeps.append, now=lambda: clock[0])
    timings = {entry["phase"]: entry for entry in agent.timings}
    assert timings["get_state"]["elapsed_s"] == pytest.approx(0.4)
    assert timings["get_game_config"]["elapsed_s"] == pytest.approx(0.1)
    assert timings["decision"]["elapsed_s"] == pytest.approx(0.02)
    assert timings["play_action"]["elapsed_s"] == pytest.approx(0.3)
    assert agent.timings[0]["game_seconds"] == 15
    assert agent.timings[0]["state_version"] == 100
    assert all(entry["ok"] for entry in agent.timings)
    assert sleeps == []
    assert game.get_state_calls == 2
    assert game.config_calls == ["red_alert"]


def test_diagnostic_failure_never_interrupts_gameplay():
    class BrokenDiagnostics(Recorder):
        def on_runtime_timing(self, record, context):
            raise ValueError("diagnostic sink unavailable")

    game = RealtimeFakeGame(CONFIG).queue_state(ra_state(), terminal_state())
    game.queue_play_action(accepted(("build", "pending", "pending"))).queue_result(result_dict())
    run_game(game, RED_ALERT, BrokenDiagnostics(ORDERS), sleep=lambda seconds: None)
    assert len(game.play_action_calls) == 1


def test_redalert_timing_log_whitelists_fields_and_is_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("REDALERT_LOG_DIR", str(tmp_path))
    agent = RedAlertAgent()
    agent.on_runtime_timing({"phase": "play_action", "elapsed_s": 0.7, "since_start_s": 1.5,
                             "ok": False, "token": "private-key", "error": "private-key",
                             "payload": {"authorization": "private-key"}, "game_seconds": float("nan")}, RED_ALERT)
    agent.on_runtime_timing({"phase": "private-key", "elapsed_s": 0.7}, RED_ALERT)
    agent._replay.close()
    entries = [json.loads(line) for path in tmp_path.glob("*.jsonl") for line in path.read_text().splitlines()]
    assert entries == [{"type": "timing", "phase": "play_action", "elapsed_s": 0.7,
                        "since_start_s": 1.5, "ok": False}]
    monkeypatch.delenv("REDALERT_LOG_DIR")
    unlogged = RedAlertAgent()
    unlogged.on_runtime_timing({"phase": "play_action", "elapsed_s": 0.1}, RED_ALERT)
    assert unlogged._replay is None
