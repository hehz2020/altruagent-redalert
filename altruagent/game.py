from __future__ import annotations

import re
from urllib.parse import urlsplit
from typing import TYPE_CHECKING

from .errors import ConfigurationError
from .models import GameState

if TYPE_CHECKING:
    from .client import AltruAgentClient

_HAS_SCHEME = re.compile(r"^https?://", re.IGNORECASE)


_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def _is_local_host(host_and_path: str) -> bool:
    host = urlsplit(f"//{host_and_path}").hostname or ""
    return host in _LOCAL_HOSTS or host.endswith(".localhost")


def _normalize_game_server_url(game_server_url: str) -> str:

    value = (game_server_url or "").strip()
    if not value:
        raise ConfigurationError("game_server_url must not be empty.")
    if not _HAS_SCHEME.match(value):
        scheme = "http" if _is_local_host(value) else "https"
        value = f"{scheme}://{value}"
    return value.rstrip("/")


class GameSession:


    def __init__(self, client: "AltruAgentClient", *, session_id: str, game_server_url: str) -> None:
        if not session_id:
            raise ConfigurationError("session_id must not be empty.")
        self._client = client
        self.session_id = session_id
        self.game_server_url = _normalize_game_server_url(game_server_url)

    def _url(self, suffix: str = "") -> str:
        return f"{self.game_server_url}/games/{self.session_id}{suffix}"

    def state(self) -> GameState:

        data = self._client.request("GET", self._url())
        return GameState.from_dict(data if isinstance(data, dict) else {})

    def step(self, action: int) -> GameState:

        data = self._client.request("POST", self._url("/step"), json={"action": action})
        return GameState.from_dict(data if isinstance(data, dict) else {})

    def resign(self) -> GameState:

        data = self._client.request("POST", self._url("/resign"), json={})
        return GameState.from_dict(data if isinstance(data, dict) else {})

    def send_message(self, content: str, recipients: list[int] | None = None) -> GameState:

        body = {"type": "chat", "content": content, "recipients": list(recipients or [])}
        data = self._client.request("POST", self._url("/message"), json=body)
        return GameState.from_dict(data if isinstance(data, dict) else {})

    def terminate_messaging(self) -> GameState:

        data = self._client.request(
            "POST", self._url("/message"), json={"type": "terminate", "recipients": []}
        )
        return GameState.from_dict(data if isinstance(data, dict) else {})
