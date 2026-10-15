from __future__ import annotations

from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from altruagent import DecisionContext, GameState, TERMINATE_MESSAGING, WAIT
from altru_redalert import RedAlertAgent, create_agent


def state(game_type: str = "red_alert") -> GameState:
    return GameState.from_mcp_state(
        {
            "session_id": "offline-test",
            "game_type": game_type,
            "status": "in_progress",
            "phase": "playing" if game_type == "red_alert" else "moving",
            "is_current_actor": True,
            "is_terminal": False,
            "state_version": 50,
            "observation": {"tick": 50},
            "legal_actions": {},
        }
    )


def context(game_type: str = "red_alert", config=None) -> DecisionContext:
    return DecisionContext(
        session_id="offline-test",
        tournament_id=None,
        game_type=game_type,
        agent_id="offline-agent",
        game_config=config,
    )


class FakeController:
    def __init__(self, answer=None):
        self.answer = answer
        self.decisions = []
        self.results = []
        self.stats = {"offline": 1}

    def decide(self, raw, config=None):
        self.decisions.append((raw, config))
        return self.answer

    def on_result(self, result):
        self.results.append(result)


class RecordingDelegate:
    def __init__(self):
        self.actions = []
        self.messages = []
        self.results = []

    def choose_action(self, st, ctx):
        self.actions.append((st, ctx))
        return "delegate-action"

    def choose_message(self, st, ctx):
        self.messages.append((st, ctx))
        return TERMINATE_MESSAGING

    def on_action_result(self, result, ctx):
        self.results.append((result, ctx))


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"REDALERT_LOG_DIR": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_factory_does_not_load_other_game_agent(self):
        with patch("altru_redalert.adapter.load_agent_factory") as loader:
            agent = create_agent()
            self.assertIsInstance(agent, RedAlertAgent)
            self.assertIsInstance(agent.stats, dict)
            loader.assert_not_called()

    def test_red_alert_forwards_raw_config_and_result(self):
        order = {"type": "orders", "orders": [{"cmd": "build", "item": "powr"}]}
        core = FakeController(order)
        agent = RedAlertAgent(core)
        st = state()
        config = {"rules": {}}
        result = {"accepted": True, "pending": True}
        with patch("altru_redalert.adapter.load_agent_factory") as loader:
            self.assertIs(agent.choose_action(st, context(config=config)), order)
            agent.on_action_result(result, context())
            loader.assert_not_called()
        self.assertIs(core.decisions[0][0], st.raw)
        self.assertIs(core.decisions[0][1], config)
        self.assertEqual(core.results, [result])
        self.assertIs(agent.stats, core.stats)

    def test_none_means_wait_and_missing_context_is_supported(self):
        core = FakeController()
        agent = RedAlertAgent(core)
        self.assertIs(agent.choose_action(state()), WAIT)
        self.assertIsNone(core.decisions[0][1])

    def test_delegate_is_loaded_once_and_receives_all_hooks(self):
        delegate = RecordingDelegate()
        core = FakeController()
        agent = RedAlertAgent(core, other_agent_spec="my_agents:build")
        st, ctx = state("werewolf"), context("werewolf")
        result = {"accepted": True}
        with patch("altru_redalert.adapter.load_agent_factory", return_value=lambda: delegate) as loader:
            self.assertEqual(agent.choose_action(st, ctx), "delegate-action")
            self.assertIs(agent.choose_message(st, ctx), TERMINATE_MESSAGING)
            agent.on_action_result(result, ctx)
            agent.choose_action(st, ctx)
            loader.assert_called_once_with("my_agents:build")
        self.assertEqual(len(delegate.actions), 2)
        self.assertEqual(delegate.messages, [(st, ctx)])
        self.assertEqual(delegate.results, [(result, ctx)])
        self.assertEqual(core.decisions, [])
        self.assertEqual(core.results, [])

    def test_message_can_be_first_delegated_call(self):
        delegate = RecordingDelegate()
        agent = RedAlertAgent(FakeController())
        st, ctx = state("werewolf"), context("werewolf")
        with patch("altru_redalert.adapter.load_agent_factory", return_value=lambda: delegate):
            self.assertIs(agent.choose_message(st, ctx), TERMINATE_MESSAGING)
        self.assertEqual(delegate.messages, [(st, ctx)])

    def test_callable_takes_precedence_and_missing_message_ends_chat(self):
        class CallableDelegate:
            def __call__(self, st, ctx):
                return "callable"

            def choose_action(self, st, ctx):
                raise AssertionError("SDK callable precedence was not preserved")

        agent = RedAlertAgent(FakeController())
        st, ctx = state("werewolf"), context("werewolf")
        with patch("altru_redalert.adapter.load_agent_factory", return_value=CallableDelegate):
            self.assertEqual(agent.choose_action(st, ctx), "callable")
            self.assertIs(agent.choose_message(st, ctx), TERMINATE_MESSAGING)
            agent.on_action_result({"accepted": True}, ctx)

    def test_delegate_configuration_error_is_not_swallowed(self):
        agent = RedAlertAgent(FakeController())
        with patch("altru_redalert.adapter.load_agent_factory", side_effect=ValueError("bad config")):
            with self.assertRaisesRegex(ValueError, "bad config"):
                agent.choose_action(state("werewolf"), context("werewolf"))

    def test_delegate_cannot_point_back_to_this_adapter(self):
        agent = RedAlertAgent(FakeController(), other_agent_spec="altru_redalert:create_agent")
        with self.assertRaisesRegex(ValueError, "must not point back"):
            agent.choose_action(state("werewolf"), context("werewolf"))

    def test_logging_is_disabled_without_explicit_environment_setting(self):
        with patch("altru_redalert.adapter.os.open") as open_file:
            agent = RedAlertAgent(FakeController())
            agent.choose_action(state(), context())
            agent.on_action_result({"accepted": True}, context())
            open_file.assert_not_called()
        self.assertIsNone(agent._replay)

    def test_private_replay_preserves_decisions_and_excludes_unexpected_secrets(self):
        secret = "MUST_NOT_BE_WRITTEN"
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"REDALERT_LOG_DIR": directory}):
            order = {"type": "orders", "orders": [{"cmd": "build", "item": "powr"}]}
            core = FakeController(order)
            agent = RedAlertAgent(core)
            st = state()
            st.raw.update(
                session_id=secret,
                headers={"Authorization": secret},
                access_token=secret,
                players=[{"agent_id": secret}],
                grant={"access_token": secret},
                next_actions=[{"hint": secret}],
            )
            st.raw["observation"].update(
                token=secret,
                unexpected=secret,
                units=[{"id": 10, "type": "e1", "x": 1, "y": 2, "hp": 100, "access_token": secret}],
            )
            st.raw["last_orders"] = {
                "batch": 1, "state_version": 49, "pending": False, "detail": secret,
                "results": [{"index": 0, "cmd": "build", "status": "ok", "reason": "ok", "detail": secret}],
            }
            st.raw["recent_order_problems"] = [{"batch": 0, "index": 0, "cmd": "deploy", "status": "rejected", "reason": "invalid", "detail": secret}]
            config = {"rules": {"units": {"e1": {"cost": 100, "secret": secret}}}, "access_token": secret, "unexpected": secret}
            self.assertIs(agent.choose_action(st, context(config=config)), order)
            agent.on_action_result({
                "accepted": True, "pending": True, "detail": secret,
                "error": "INVALID_ACTION", "next_actions": [{"hint": secret}],
                "results": [{"index": 0, "cmd": "build", "status": "pending", "reason": "pending", "commands": 1, "detail": secret,
                             "failed": [{"unit": 999, "reason": "not_owned", "detail": secret}]}],
            }, context())
            core.answer = None
            self.assertIs(agent.choose_action(st, context(config=config)), WAIT)
            agent._replay.close()
            files = list(Path(directory).glob("*.jsonl"))
            self.assertEqual(len(files), 1)
            self.assertRegex(files[0].name, r"^[a-f0-9]{32}\.jsonl$")
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)
            text = files[0].read_text()
            self.assertNotIn(secret, text)
            records = [json.loads(line) for line in text.splitlines()]
            self.assertEqual(records[0]["raw"]["session_id"], "replay")
            self.assertEqual(records[0]["decision"], order)
            self.assertIn("config", records[0])
            self.assertNotIn("config", records[2])
            self.assertIsNone(records[2]["decision"])
            self.assertEqual(records[0]["raw"]["last_orders"]["results"][0]["status"], "ok")
            self.assertEqual(records[0]["raw"]["recent_order_problems"][0]["batch"], 0)
            self.assertEqual(records[1]["result"]["results"][0]["failed"], [{"unit": 999, "reason": "not_owned"}])

    def test_logging_failure_warns_and_gameplay_continues(self):
        with tempfile.TemporaryDirectory() as directory:
            blocked = Path(directory) / "a-file"
            blocked.write_text("not a directory")
            with patch.dict(os.environ, {"REDALERT_LOG_DIR": str(blocked)}):
                agent = RedAlertAgent(FakeController())
                warning = io.StringIO()
                with redirect_stderr(warning):
                    self.assertIs(agent.choose_action(state(), context()), WAIT)
                    self.assertIs(agent.choose_action(state(), context()), WAIT)
                self.assertEqual(warning.getvalue().count("logging disabled"), 1)
                self.assertNotIn(str(blocked), warning.getvalue())

    def test_other_games_do_not_create_red_alert_logs(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"REDALERT_LOG_DIR": directory}):
            agent = RedAlertAgent(FakeController())
            with patch("altru_redalert.adapter.load_agent_factory", return_value=RecordingDelegate):
                agent.choose_action(state("werewolf"), context("werewolf"))
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
