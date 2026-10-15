from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from dotenv import load_dotenv

from ._responses import _parse_error_body, _parse_json_body
from .auth import ApiKeyAuth, AuthStrategy
from .errors import AuthenticationError, ConfigurationError, PlatformError
from .models import Agent, AgentSessions, Tournament
from .notices import PLATFORM_KEY_RETIRED_NOTICE

if TYPE_CHECKING:
    from .game import GameSession
    from .mcp_game import MCPGameSession

DEFAULT_TIMEOUT_SECONDS = 10.0


class AltruAgentClient:


    def __init__(
        self,
        control_url: str | None = None,
        api_key: str | None = None,
        *,
        auth: AuthStrategy | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        load_env_file: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if load_env_file:
            load_dotenv()

        if auth is not None and api_key is not None:
            raise ConfigurationError("Pass either api_key= or auth=, not both.")

        control_url = control_url or os.environ.get("ALTRUAGENT_CONTROL_URL")

        if not control_url:
            raise ConfigurationError(
                "ALTRUAGENT_CONTROL_URL is not set. Copy .env.example to .env and fill it "
                "in, or pass control_url= explicitly."
            )
        if auth is None:
            api_key = api_key or os.environ.get("ALTRUAGENT_API_KEY")
            if not api_key:
                raise ConfigurationError(PLATFORM_KEY_RETIRED_NOTICE)
            auth = ApiKeyAuth(api_key)

        self.control_url = control_url.rstrip("/")
        self.auth = auth
        self._access_token: str | None = None
        self._http = httpx.Client(base_url=self.control_url, timeout=timeout, transport=transport)

    def __enter__(self) -> "AltruAgentClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        from .mcp_transport import close_persistent_sessions

        try:
            close_persistent_sessions(self)
        finally:
            self._http.close()


    def login(self) -> None:

        self._access_token = self.auth.login(self._http, self.control_url)

    def _current_access_token(self, *, force_relogin: bool = False) -> str:

        if self._access_token is None or force_relogin:
            self.login()
        return self._access_token

    def me(self) -> Agent:

        data = self.request("GET", "/auth/agent/me")
        return Agent.from_dict(data if isinstance(data, dict) else {})

    def sessions(self) -> AgentSessions:

        data = self.request("GET", "/agents/me/sessions")
        return AgentSessions.from_dict(data if isinstance(data, dict) else {}, client=self)

    def tournaments(self) -> list[Tournament]:

        data = self.request("GET", "/tournaments")
        rows = data.get("tournaments") if isinstance(data, dict) else None
        return [Tournament.from_dict(row) for row in (rows or [])]

    def tournament(self, tournament_id: str) -> Tournament:

        data = self.request("GET", f"/tournaments/{tournament_id}")
        tournament_data = data.get("tournament") if isinstance(data, dict) else None
        viewer_data = data.get("viewer") if isinstance(data, dict) else None
        return Tournament.from_dict(tournament_data or {}, viewer=viewer_data)

    def join_tournament(self, tournament_id: str) -> dict:

        return self.request("POST", f"/tournaments/{tournament_id}/join")

    def leave_tournament(self, tournament_id: str) -> dict:

        return self.request("POST", f"/tournaments/{tournament_id}/leave")

    def game(self, session_id: str, game_server_url: str) -> "GameSession":

        from .game import GameSession

        return GameSession(self, session_id=session_id, game_server_url=game_server_url)

    def mcp_game(self, session_id: str, game_server_url: str) -> "MCPGameSession":

        from .mcp_game import MCPGameSession

        return MCPGameSession(self, session_id=session_id, game_server_url=game_server_url)

    def request(self, method: str, url: str, **kwargs: Any) -> Any:

        if self._access_token is None:
            self.login()

        response = self._send(method, url, **kwargs)

        if response.status_code == 401:
            self.login()
            response = self._send(method, url, **kwargs)

        if response.status_code == 401:
            parsed = _parse_error_body(response)
            message = parsed["detail"] or parsed["error"] or "Not authenticated."
            raise AuthenticationError(
                message,
                status_code=401,
                error_code=parsed["error"],
                detail=parsed["detail"],
            )
        if response.status_code >= 400:
            parsed = _parse_error_body(response)
            message = (
                parsed["detail"]
                or parsed["error"]
                or f"Request failed with status {response.status_code}."
            )
            raise PlatformError(
                message,
                status_code=response.status_code,
                error_code=parsed["error"],
                detail=parsed["detail"],
                next_action=parsed["next_action"],
            )

        return _parse_json_body(response)


    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", None) or {})
        headers["Authorization"] = f"Bearer {self._access_token}"
        try:
            return self._http.request(method, url, headers=headers, **kwargs)
        except httpx.RequestError as exc:
            raise PlatformError(f"Could not reach {url}: {exc}", status_code=None) from exc

