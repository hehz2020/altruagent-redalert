"""Persistent bridge tested through the real MCP SDK and mocked HTTP only."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os

import httpx
import pytest

from altruagent.client import AltruAgentClient
from altruagent.mcp_transport import MCPToolError, call_tool, close_persistent_sessions
from test_mcp_transport import FakeClient, MCP_URL, _initialize_response, _tool_call_response


class Server:
    def __init__(self) -> None:
        self.calls = []
        self.clients = []
        self.initialize_count = 0
        self.list_count = 0
        self.reject_token = None
        self.fail_play = False
        self.reject_play_once = False
        self.application_error = False
        self.block_play = False

    async def handle(self, request):
        assert request.method == "POST", "stateless sessions should not open GET or DELETE requests"
        body = json.loads(request.content)
        method, req_id = body.get("method"), body.get("id")
        self.calls.append((method, request.headers.get("authorization")))
        if request.headers.get("authorization") == self.reject_token:
            return httpx.Response(401, text="do not log this secret response body")
        if method == "initialize":
            self.initialize_count += 1
            return httpx.Response(200, json=_initialize_response(req_id))
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            self.list_count += 1
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": req_id,
                "result": {"tools": [
                    {"name": name, "inputSchema": {"type": "object"}, "outputSchema": None}
                    for name in ("get_game_state", "play_action", "wait_for_update")
                ]},
            })
        if method == "tools/call":
            if body["params"]["name"] == "play_action":
                if self.fail_play:
                    self.fail_play = False
                    raise httpx.ReadError("response lost after action might have been accepted")
                if self.reject_play_once:
                    self.reject_play_once = False
                    return httpx.Response(401)
                if self.block_play:
                    await asyncio.sleep(20)
            payload = {"error": "STALE_STATE"} if self.application_error else {"ok": True}
            return httpx.Response(200, json=_tool_call_response(req_id, payload))
        return httpx.Response(404)

    def factory(self, headers=None, timeout=None, auth=None):
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(self.handle), headers=headers, timeout=timeout, auth=auth,
        )
        self.clients.append(client)
        return client


@pytest.fixture
def persistent(monkeypatch):
    monkeypatch.setenv("ALTRUAGENT_PERSISTENT_MCP", "1")
    client = FakeClient(["jwt-1", "jwt-2", "jwt-3"])
    server = Server()
    # Preserve factory identity so the second request uses the same session.
    factory = server.factory
    yield client, server, factory
    close_persistent_sessions(client)
    assert all(http.is_closed for http in server.clients)


def test_reuses_handshake_connection_and_schema(persistent):
    client, server, factory = persistent
    for name in ("get_game_state", "play_action", "get_game_state"):
        assert call_tool(client, MCP_URL, name, {}, httpx_client_factory=factory) == {"ok": True}
    owner = client._mcp_persistent_sessions[MCP_URL]
    assert len(server.clients) == 1
    assert server.initialize_count == server.list_count == 1
    methods = [method for method, _ in server.calls]
    assert methods.index("tools/list") < methods.index("tools/call")
    assert methods.count("tools/call") == 3
    close_persistent_sessions(client)
    close_persistent_sessions(client)
    assert not owner._thread.is_alive()


def test_401_refreshes_same_client_once(persistent):
    client, server, factory = persistent
    server.reject_token = "Bearer jwt-1"
    assert call_tool(client, MCP_URL, "play_action", {}, httpx_client_factory=factory) == {"ok": True}
    assert client._relogin_calls == 1
    assert len(server.clients) == 2
    assert sum(method == "tools/call" for method, _ in server.calls) == 1
    assert server.clients[0].is_closed


def test_401_on_tool_refreshes_once_without_extra_action(persistent):
    client, server, factory = persistent
    server.reject_play_once = True
    assert call_tool(client, MCP_URL, "play_action", {}, httpx_client_factory=factory) == {"ok": True}
    assert client._relogin_calls == 1
    assert sum(method == "tools/call" for method, _ in server.calls) == 2
    assert server.initialize_count == 2


def test_repeated_401_stops_after_one_refresh(persistent):
    client, server, factory = persistent
    client._tokens = ["jwt-1"]
    server.reject_token = "Bearer jwt-1"
    with pytest.raises(MCPToolError) as caught:
        call_tool(client, MCP_URL, "play_action", {}, httpx_client_factory=factory)
    assert caught.value.status_code == 401
    assert client._relogin_calls == 1
    assert len(server.clients) == 2
    assert "secret" not in str(caught.value)
    assert "jwt-1" not in str(caught.value)


def test_disconnect_never_replays_action_and_next_read_reconnects(persistent):
    client, server, factory = persistent
    server.fail_play = True
    with pytest.raises(MCPToolError):
        call_tool(client, MCP_URL, "play_action", {}, httpx_client_factory=factory)
    assert sum(method == "tools/call" for method, _ in server.calls) == 1
    assert client._relogin_calls == 0
    assert call_tool(client, MCP_URL, "get_game_state", {}, httpx_client_factory=factory) == {"ok": True}
    assert server.initialize_count == 2
    assert len(server.clients) == 2


def test_application_error_keeps_healthy_connection(persistent):
    client, server, factory = persistent
    server.application_error = True
    with pytest.raises(MCPToolError) as caught:
        call_tool(client, MCP_URL, "play_action", {}, httpx_client_factory=factory)
    assert caught.value.error_code == "STALE_STATE"
    server.application_error = False
    assert call_tool(client, MCP_URL, "get_game_state", {}, httpx_client_factory=factory) == {"ok": True}
    assert server.initialize_count == 1


def test_unsendable_arguments_never_open_session(persistent):
    client, server, factory = persistent
    with pytest.raises(MCPToolError) as caught:
        call_tool(client, MCP_URL, "play_action", {"bad": object()}, httpx_client_factory=factory)
    assert caught.value.local_error
    assert server.clients == []


def test_unknown_tool_fails_before_mutation(persistent):
    from altruagent.runner import _is_unknown_tool_error

    client, server, factory = persistent
    with pytest.raises(MCPToolError) as caught:
        call_tool(client, MCP_URL, "unknown_mutation", {}, httpx_client_factory=factory)
    assert caught.value.protocol_error
    assert _is_unknown_tool_error(caught.value)
    assert sum(method == "tools/call" for method, _ in server.calls) == 0
    assert call_tool(client, MCP_URL, "get_game_state", {}, httpx_client_factory=factory) == {"ok": True}
    assert server.initialize_count == 1


def test_schema_401_is_retried_before_any_action(persistent):
    client, server, _ = persistent
    original = server.handle

    async def handler(request):
        body = json.loads(request.content)
        if body.get("method") == "tools/list" and request.headers["authorization"] == "Bearer jwt-1":
            return httpx.Response(401)
        return await original(request)

    server.handle = handler
    factory = server.factory
    assert call_tool(client, MCP_URL, "play_action", {}, httpx_client_factory=factory) == {"ok": True}
    assert client._relogin_calls == 1
    assert sum(method == "tools/call" for method, _ in server.calls) == 1


def test_unrelated_401_after_action_started_cannot_trigger_replay():
    from altruagent.mcp_transport import _PersistentCallFailure

    request = httpx.Request("POST", MCP_URL, json={"method": "tools/list"})
    response = httpx.Response(401, request=request)
    failure = _PersistentCallFailure(
        httpx.HTTPStatusError("unauthorized", request=request, response=response), tool_started=True,
    )
    assert not failure.may_refresh_auth()


def test_token_change_reconnects_without_cross_token_reuse(persistent):
    client, server, factory = persistent
    call_tool(client, MCP_URL, "get_game_state", {}, httpx_client_factory=factory)
    client._current_access_token(force_relogin=True)
    call_tool(client, MCP_URL, "get_game_state", {}, httpx_client_factory=factory)
    assert len(server.clients) == 2
    assert server.clients[0].is_closed
    assert server.calls[-1][1] == "Bearer jwt-2"


def test_actual_client_close_cleans_worker(monkeypatch):
    monkeypatch.setenv("ALTRUAGENT_PERSISTENT_MCP", "1")
    server = Server()
    factory = server.factory
    with AltruAgentClient(control_url="https://control.example.test", api_key="unused", load_env_file=False) as client:
        client._access_token = "memory-token"
        call_tool(client, MCP_URL, "get_game_state", {}, httpx_client_factory=factory)
        owner = client._mcp_persistent_sessions[MCP_URL]
    assert not owner._thread.is_alive()
    assert all(http.is_closed for http in server.clients)
    assert client._http.is_closed


def test_timeout_does_not_replay_and_session_can_be_closed(persistent, monkeypatch):
    from altruagent import mcp_transport

    monkeypatch.setattr(mcp_transport, "MCP_SESSION_TIMEOUT_SECONDS", 0.1)
    client, server, factory = persistent
    server.block_play = True
    with pytest.raises(MCPToolError):
        call_tool(client, MCP_URL, "play_action", {}, httpx_client_factory=factory)
    assert sum(method == "tools/call" for method, _ in server.calls) == 1
    assert client._relogin_calls == 0


def _spawn_probe(queue):
    os.environ["ALTRUAGENT_PERSISTENT_MCP"] = "1"
    client, server = FakeClient(), Server()
    factory = server.factory
    try:
        call_tool(client, MCP_URL, "get_game_state", {}, httpx_client_factory=factory)
        call_tool(client, MCP_URL, "play_action", {}, httpx_client_factory=factory)
        owner = client._mcp_persistent_sessions[MCP_URL]
        close_persistent_sessions(client)
        queue.put((server.initialize_count, len(server.clients), owner._thread.is_alive(), all(c.is_closed for c in server.clients)))
    finally:
        close_persistent_sessions(client)


def test_multiprocessing_spawn_owns_and_closes_its_loop():
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    process = context.Process(target=_spawn_probe, args=(queue,))
    process.start()
    try:
        assert queue.get(timeout=15) == (1, 1, False, True)
        process.join(timeout=10)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        queue.close()
        queue.join_thread()
