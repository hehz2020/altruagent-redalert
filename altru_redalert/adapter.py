"""AltruAgent SDK adapter for the scripted Red Alert controller.

Red Alert does not import or initialize an LLM. Other assigned games are
delegated lazily to ``REDALERT_OTHER_AGENT`` (``MODULE[:FACTORY]``), whose
default is the starter's ``examples.llm_agent``. That default needs its own
model/API-key configuration, but only when a non-Red-Alert game is played.
Consequently, ``--check-tournament --agent altru_redalert`` does not validate
the fallback's model credentials: check the chosen fallback separately.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys
import uuid
from typing import Any, Callable

from altruagent import TERMINATE_MESSAGING, WAIT
from altruagent.agent_loader import load_agent_factory

from .core import Controller


_ACTOR_FIELDS = frozenset("id type x y hp act idle stance wreck powered powered_down repairing producing rally".split())
_ORDER_FIELDS = frozenset("cmd units to target building item count at on stance queued".split())
_COMMANDS = frozenset("move attack_move attack stop deploy unload guard enter_transport harvest set_stance build train place cancel sell repair power_toggle set_primary rally".split())
_REASONS = frozenset("ok no_feedback pending invalid not_owned wreck is_building target_not_visible not_available not_ready unknown_actor not_applied already_repairing not_repairing already_on already_off".split())
_ERRORS = frozenset("STALE_STATE NOT_YOUR_TURN INVALID_ACTION RUNTIME_TEMPORARILY_UNAVAILABLE GAME_ALREADY_COMPLETE SESSION_NOT_FOUND AGENT_NOT_IN_SESSION RUNTIME_UNAVAILABLE UNAUTHENTICATED TOO_MANY_WAITS".split())
_PRIVATE_KEYS = frozenset("headers authorization token access_token refresh_token api_key official_agent_key agent_id player_id players session_id grant seat_grant next_actions".split())
_CONFIG_FIELDS = frozenset("rules order_schema match_rules maps realtime legal_actions observation_fields results_policy timeouts".split())


def _public_value(value: Any) -> Any:
    """Copy JSON data, dropping credential/identity keys at every nesting level."""
    if isinstance(value, dict):
        return {
            key: _public_value(item)
            for key, item in value.items()
            if isinstance(key, str)
            and key.lower() not in _PRIVATE_KEYS
            and not any(part in key.lower() for part in ("token", "secret", "password", "credential"))
        }
    if isinstance(value, (list, tuple)):
        return [_public_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return None


def _known(value: Any, fields) -> dict:
    if not isinstance(value, dict):
        return {}
    return {key: _public_value(value[key]) for key in fields if key in value}


def _rows(value: Any, fields) -> list:
    return [_known(row, fields) for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _verdict(row: Any, *, delayed: bool = False) -> dict:
    data = {}
    if not isinstance(row, dict):
        return data
    numeric_fields = ("index", "commands")
    if delayed:
        numeric_fields += ("state_version", "accepted_orders", "rejected_orders")
    for key in numeric_fields:
        if isinstance(row.get(key), int) and not isinstance(row[key], bool):
            data[key] = row[key]
    if delayed and isinstance(row.get("batch"), (str, int)) and not isinstance(row["batch"], bool):
        data["batch"] = row["batch"]
    if delayed and isinstance(row.get("pending"), bool):
        data["pending"] = row["pending"]
    for key, choices in (("cmd", _COMMANDS), ("status", {"pending", "ok", "partial", "rejected", "lost"}), ("reason", _REASONS)):
        if isinstance(row.get(key), str) and row[key] in choices:
            data[key] = row[key]
    if isinstance(row.get("failed"), list):
        data["failed"] = []
        for failed in row["failed"]:
            if not isinstance(failed, dict):
                continue
            entry = {}
            if isinstance(failed.get("unit"), int) and not isinstance(failed["unit"], bool):
                entry["unit"] = failed["unit"]
            if isinstance(failed.get("reason"), str) and failed["reason"] in _REASONS:
                entry["reason"] = failed["reason"]
            data["failed"].append(entry)
    return data


def _safe_result(result: Any, *, delayed: bool = False) -> dict:
    data = {}
    if isinstance(result, dict):
        for key in ("accepted", "pending"):
            if isinstance(result.get(key), bool):
                data[key] = result[key]
        if delayed:
            for key in ("state_version", "accepted_orders", "rejected_orders"):
                if isinstance(result.get(key), int) and not isinstance(result[key], bool):
                    data[key] = result[key]
            if isinstance(result.get("batch"), (str, int)) and not isinstance(result["batch"], bool):
                data["batch"] = result["batch"]
        if isinstance(result.get("results"), list):
            data["results"] = [_verdict(row) for row in result["results"] if isinstance(row, dict)]
        if isinstance(result.get("error"), str) and result["error"] in _ERRORS:
            data["error"] = result["error"]
    return data


def _safe_state(raw: dict) -> dict:
    """Whitelist the gameplay snapshot; never serialize grants or identities."""
    clean = _known(raw, ("state_version", "phase", "is_current_actor", "is_terminal"))
    clean.update(game_type="red_alert", session_id="replay")
    schemas = {
        "map": "id width height bounds layout",
        "match_rules": "starting_cash starting_units explored_map kill_bounties crates",
        "time": "max_minutes game_seconds remaining_seconds",
        "limits": "max_orders_per_batch max_units_per_order max_train_count max_engine_commands_per_batch min_batch_interval_s stale_seconds",
        "pacing": "mode min_batch_interval_s stale_seconds next_batch_allowed_in_ms",
    }
    for key, fields in schemas.items():
        if key in raw:
            clean[key] = _known(raw[key], fields.split())
    obs = raw.get("observation")
    if isinstance(obs, dict):
        view = _known(obs, ("tick", "faction", "enemy_faction", "base_center", "explored_percent", "available_production"))
        view["economy"] = _known(obs.get("economy"), "cash ore power_provided power_drained resource_capacity harvesters".split())
        view["military"] = _known(obs.get("military"), "kills_cost deaths_cost assets_value army_value units_killed units_lost buildings_killed buildings_lost".split())
        view["map"] = _known(obs.get("map"), "id width height bounds".split())
        for key in ("units", "buildings", "visible_enemies", "visible_enemy_buildings"):
            view[key] = _rows(obs.get(key), _ACTOR_FIELDS)
        view["production"] = _rows(obs.get("production"), "queue item count progress remaining_s paused ready".split())
        view["events"] = _rows(obs.get("events"), "seq tick kind id type unit unit_id building building_id wreck_id x y count".split())
        clean["observation"] = view
    else:
        clean["observation"] = None
    legal = raw.get("legal_actions")
    if isinstance(legal, dict):
        clean["legal_actions"] = {}
        for key in ("build", "train", "place", "deploy", "repair", "attack", "combat_units", "idle_units", "harvesters", "production_buildings"):
            value = legal.get(key)
            if isinstance(value, list):
                clean["legal_actions"][key] = [
                    _known(item, _ACTOR_FIELDS | {"item"}) if isinstance(item, dict) else _public_value(item)
                    for item in value
                ]
        if "enemy_base" in legal:
            clean["legal_actions"]["enemy_base"] = _public_value(legal["enemy_base"])
        if "attack_now" in legal:
            clean["legal_actions"]["attack_now"] = _known(legal["attack_now"], _ORDER_FIELDS) if isinstance(legal["attack_now"], dict) else None
    if "last_orders" in raw:
        clean["last_orders"] = _safe_result(raw["last_orders"], delayed=True)
    if isinstance(raw.get("recent_order_problems"), list):
        clean["recent_order_problems"] = [_verdict(row, delayed=True) for row in raw["recent_order_problems"] if isinstance(row, dict)]
    return clean


class _ReplayLog:
    """Opt-in private local JSONL; logging failures never interrupt gameplay."""

    def __init__(self, directory: str) -> None:
        self.directory = directory
        self.file = None
        self.disabled = False
        self.config_written = False

    def write(self, entry: dict) -> None:
        if self.disabled:
            return
        try:
            line = json.dumps(entry, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            if self.file is None:
                directory = Path(self.directory)
                directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                path = directory / f"{uuid.uuid4().hex}.jsonl"
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                self.file = os.fdopen(descriptor, "w", encoding="utf-8")
            self.file.write(line + "\n")
            self.file.flush()
        except (OSError, TypeError, ValueError) as exc:
            self.disabled = True
            # Do not echo exception text: it can contain paths or payload data.
            print(f"Red Alert replay logging disabled ({type(exc).__name__}); gameplay continues.", file=sys.stderr)
            self.close()

    def state(self, raw: dict, config: Any, decision: Any) -> None:
        entry = {"type": "state", "raw": _safe_state(raw), "decision": decision}
        if isinstance(config, dict) and not self.config_written:
            entry["config"] = _known(config, _CONFIG_FIELDS)
            self.config_written = True
        self.write(entry)

    def close(self) -> None:
        if self.file is not None:
            try:
                self.file.close()
            except OSError:
                pass
            self.file = None

    def __del__(self) -> None:
        self.close()


class RedAlertAgent:
    """One controller per match, using the starter's existing transport.

    ``controller`` and ``other_agent_spec`` may be supplied for local tests.
    The public factory uses the normal controller and the environment setting.
    Delegate errors propagate to the SDK so configuration failures are visible.
    """

    def __init__(
        self,
        controller: Controller | None = None,
        *,
        other_agent_spec: str | None = None,
    ) -> None:
        self.controller = controller if controller is not None else Controller()
        self._other_agent_spec = (
            other_agent_spec
            if other_agent_spec is not None
            else os.environ.get("REDALERT_OTHER_AGENT", "examples.llm_agent")
        )
        self._delegate: Any = None
        self._delegate_decision: Callable | None = None
        self._active_game_type = "red_alert"
        directory = os.environ.get("REDALERT_LOG_DIR", "").strip()
        self._replay = _ReplayLog(directory) if directory else None

    @property
    def stats(self) -> dict:
        """The controller's live Red Alert counters."""
        return self.controller.stats

    def _game_type(self, raw: dict, context: Any) -> str:
        # Real SDK contexts always name the game. Raw state is a useful
        # fallback for captured observations and minimal local test contexts.
        game_type = getattr(context, "game_type", None) or raw.get("game_type")
        self._active_game_type = game_type or self._active_game_type
        return self._active_game_type

    def _load_delegate(self) -> Any:
        if self._delegate is not None:
            return self._delegate

        spec = self._other_agent_spec.strip()
        if not spec:
            raise ValueError(
                "REDALERT_OTHER_AGENT is empty. Set it to your other-game "
                "agent's MODULE[:FACTORY], or examples.llm_agent (requires "
                "the starter's model/API-key configuration)."
            )
        module_name = spec.partition(":")[0]
        if module_name in {__package__, __name__}:
            raise ValueError("REDALERT_OTHER_AGENT must not point back to altru_redalert.")

        delegate = load_agent_factory(spec)()
        if isinstance(delegate, RedAlertAgent):
            raise ValueError("REDALERT_OTHER_AGENT returned another RedAlertAgent.")
        # Match the SDK contract: a callable object/function takes precedence
        # over a choose_action method on that same object.
        decision = delegate if callable(delegate) else getattr(delegate, "choose_action", None)
        if not callable(decision):
            raise TypeError(
                f"Other-game agent {spec!r} must be callable or expose "
                "choose_action(state, context)."
            )
        self._delegate = delegate
        self._delegate_decision = decision
        return delegate

    def choose_action(self, state: Any, context: Any = None) -> Any:
        raw = state.raw
        if self._game_type(raw, context) != "red_alert":
            self._load_delegate()
            return self._delegate_decision(state, context)

        config = getattr(context, "game_config", None)
        orders = self.controller.decide(raw, config)
        if self._replay is not None:
            self._replay.state(raw, config, orders)
        return WAIT if orders is None else orders

    def choose_message(self, state: Any, context: Any = None) -> Any:
        if self._game_type(state.raw, context) == "red_alert":
            # Red Alert has no messaging; match the SDK's default if a local
            # caller nevertheless asks for a message.
            return TERMINATE_MESSAGING
        delegate = self._load_delegate()
        message = getattr(delegate, "choose_message", None)
        return message(state, context) if callable(message) else TERMINATE_MESSAGING

    def on_action_result(self, result: dict, context: Any = None) -> None:
        game_type = getattr(context, "game_type", None) or self._active_game_type
        if game_type == "red_alert":
            if self._replay is not None:
                self._replay.write({"type": "result", "result": _safe_result(result)})
            self.controller.on_result(result)
            return
        # The SDK calls this after choose_action, so the delegate is normally
        # already loaded. Do not instantiate another-game agent just for a hook.
        hook = getattr(self._delegate, "on_action_result", None)
        if callable(hook):
            hook(result, context)


def create_agent() -> RedAlertAgent:
    """Factory accepted by ``python -m agent --agent altru_redalert``."""
    return RedAlertAgent()
