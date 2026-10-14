"""Offline checks run inside the actual Windows EXE before it is released."""

from __future__ import annotations

import multiprocessing
import json
import os
import sys


def _persistent_mcp_check() -> dict:
    """Run the real MCP SDK/event loop with an entirely mocked HTTP layer."""
    import httpx
    from altruagent.client import AltruAgentClient
    from altruagent.mcp_transport import call_tool

    calls: list[str] = []
    clients: list[httpx.AsyncClient] = []

    async def handler(request):
        assert request.method == "POST", "Unexpected offline MCP request"
        body = json.loads(request.content)
        method, request_id = body.get("method"), body.get("id")
        calls.append(method)
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "offline-exe-check", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [{"name": name, "inputSchema": {"type": "object"}}
                                for name in ("get_game_state", "play_action")]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": '{"ok":true}'}],
                      "structuredContent": {"ok": True}, "isError": False}
        else:
            raise AssertionError("Unexpected offline MCP method")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": request_id, "result": result})

    def factory(headers=None, timeout=None, auth=None):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                  headers=headers, timeout=timeout, auth=auth)
        clients.append(client)
        return client

    def reject_control_request(_request):
        raise AssertionError("Offline self-test must not authenticate or make control-plane requests")

    previous = os.environ.get("ALTRUAGENT_PERSISTENT_MCP")
    os.environ["ALTRUAGENT_PERSISTENT_MCP"] = "1"
    try:
        with AltruAgentClient(control_url="https://offline.invalid", api_key="offline-only",
                              load_env_file=False,
                              transport=httpx.MockTransport(reject_control_request)) as client:
            client._access_token = "offline-test-token"
            url = "https://offline.invalid/mcp"
            for name in ("get_game_state", "play_action"):
                assert call_tool(client, url, name, {}, httpx_client_factory=factory) == {"ok": True}
            owner = client._mcp_persistent_sessions[url]
            assert calls.count("initialize") == calls.count("tools/list") == len(clients) == 1
            assert calls.count("tools/call") == 2
        assert client._http.is_closed and all(item.is_closed for item in clients)
        assert not owner._thread.is_alive(), "Persistent MCP thread did not close"
        return {"ok": True, "initializations": 1, "http_clients": 1,
                "tool_calls": 2, "clean_close": True}
    finally:
        if previous is None:
            os.environ.pop("ALTRUAGENT_PERSISTENT_MCP", None)
        else:
            os.environ["ALTRUAGENT_PERSISTENT_MCP"] = previous


def _controller_check() -> dict:
    # Exercise dynamic agent imports plus the runtime transport dependency
    # graph. Importing is intentionally offline: no client is authenticated.
    import certifi
    import httpx
    import mcp.client.streamable_http
    import altruagent.worker
    import altruagent.supervisor
    from altruagent.agent_loader import load_agent_factory
    from altru_redalert.core import Controller

    assert os.path.isfile(certifi.where()), "CA certificate bundle missing"
    assert load_agent_factory("altru_redalert")() is not None
    assert load_agent_factory("examples.llm_agent") is not None
    raw = {
        "session_id": "offline-exe-check", "game_type": "red_alert",
        "phase": "playing", "is_current_actor": True,
        "is_terminal": False, "state_version": 0,
        "map": {"id": "sidestep", "bounds": [2, 2, 96, 96]},
        "time": {"game_seconds": 0, "remaining_seconds": 1200},
        "legal_actions": {"build": [], "train": [], "enemy_base": [64, 12]},
        "observation": {
            "tick": 0, "base_center": [12, 12],
            "units": [{"id": 1, "type": "mcv", "x": 12, "y": 12, "hp": 100, "idle": True}],
            "buildings": [], "production": [], "visible_enemies": [],
            "visible_enemy_buildings": [],
            "economy": {"cash": 5000, "ore": 0, "power_provided": 0, "power_drained": 0},
            "military": {"kills_cost": 0, "deaths_cost": 0},
        },
    }
    decision = Controller().decide(raw)
    assert decision and {"cmd": "deploy", "units": [1]} in decision["orders"], "MCV deployment failed"
    return {"controller": "ok", "dynamic_imports": "ok", "certificate_bundle": "ok", "httpx": httpx.__version__}


def _spawned_check(connection) -> None:
    try:
        connection.send({"ok": True, "pid": os.getpid(), **_controller_check(),
                         "persistent_mcp": _persistent_mcp_check()})
    except BaseException as exc:
        # Offline inputs only; include the class, not arbitrary repr data.
        connection.send({"ok": False, "error_type": type(exc).__name__})
        raise
    finally:
        connection.close()


def run_self_test() -> dict:
    parent = _controller_check()
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_spawned_check, args=(send,))
    process.start()
    send.close()
    try:
        child = receive.recv() if receive.poll(45) else {"ok": False, "error_type": "SpawnTimeout"}
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
        ok = child.get("ok") and child.get("pid") != os.getpid() and process.exitcode == 0
        return {"ok": bool(ok), "frozen": bool(getattr(sys, "frozen", False)),
                "platform": sys.platform, "parent": parent, "spawn_worker": child,
                "worker_exit_code": process.exitcode}
    finally:
        receive.close()
        if process.is_alive():
            process.terminate()
            process.join(5)
