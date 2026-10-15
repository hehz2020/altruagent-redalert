from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import ConfigurationError
from .game import _normalize_game_server_url
from .mcp_transport import call_tool
from .models import GameState

if TYPE_CHECKING:
    from .client import AltruAgentClient


class MCPGameSession:


    def __init__(self, client: "AltruAgentClient", *, session_id: str, game_server_url: str) -> None:
        if not session_id:
            raise ConfigurationError("session_id must not be empty.")
        self._client = client
        self.session_id = session_id
        self.game_server_url = _normalize_game_server_url(game_server_url)

    def _mcp_url(self) -> str:
        return f"{self.game_server_url}/mcp"

    def _call(self, tool: str, arguments: dict) -> dict:
        return call_tool(self._client, self._mcp_url(), tool, arguments)

    def get_state(self) -> GameState:

        data = self._call("get_game_state", {"session_id": self.session_id})
        return GameState.from_mcp_state(data)

    def wait_for_update(
        self,
        *,
        since_version: int,
        since_message_seq: int | None = None,
        since_is_current_actor: bool | None = None,
        since_phase: str | None = None,
        timeout_seconds: float | None = None,
    ) -> GameState:

        arguments: dict = {"session_id": self.session_id, "since_version": since_version}
        if since_message_seq is not None:
            arguments["since_message_seq"] = since_message_seq
        if since_is_current_actor is not None:
            arguments["since_is_current_actor"] = since_is_current_actor
        if since_phase is not None:
            arguments["since_phase"] = since_phase
        if timeout_seconds is not None:
            arguments["timeout_seconds"] = timeout_seconds
        return GameState.from_mcp_state(self._call("wait_for_update", arguments))

    def get_game_config(self, game_type: str) -> dict:

        return self._call("get_game_config", {"game_type": game_type})

    def get_legal_actions(self) -> dict:

        return self._call("get_legal_actions", {"session_id": self.session_id})

    def play_action(
        self,
        *,
        action_id: str | None = None,
        action: dict | None = None,
        state_version: int,
        reasoning_summary: str | None = None,
    ) -> dict:

        arguments: dict = {"session_id": self.session_id, "state_version": state_version}
        if action is not None:
            arguments["action"] = action
        if action_id is not None:
            arguments["action_id"] = action_id
        if reasoning_summary is not None:
            arguments["reasoning_summary"] = reasoning_summary
        return self._call("play_action", arguments)

    def send_message(self, *, message_type: str, content: str | None = None, recipients: list[int] | None = None) -> dict:

        arguments = {
            "session_id": self.session_id,
            "message_type": message_type,
            "content": content,
            "recipients": recipients,
        }
        return self._call("send_message", arguments)

    def get_messages(self, *, since: int = -1) -> dict:

        return self._call("get_messages", {"session_id": self.session_id, "since": since})

    def resign(self) -> dict:

        return self._call("resign", {"session_id": self.session_id})

    def get_result(self) -> dict:

        return self._call("get_result", {"session_id": self.session_id})
