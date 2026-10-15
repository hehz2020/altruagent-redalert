from __future__ import annotations

import asyncio
import json
import os
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import httpx
from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client
from pydantic_core import PydanticSerializationError

from .errors import PlatformError

if TYPE_CHECKING:
    from .client import AltruAgentClient

MCP_CONNECT_TIMEOUT_SECONDS = 10.0
MCP_READ_TIMEOUT_SECONDS = 40.0
MCP_SESSION_TIMEOUT_SECONDS = 45.0


class MCPToolError(PlatformError):


    def __init__(
        self, message: str, *, protocol_error: bool = False, local_error: bool = False, **kwargs: Any
    ) -> None:
        super().__init__(message, **kwargs)
        self.protocol_error = protocol_error
        self.local_error = local_error


def _unsendable_arguments(name: str, exc: BaseException) -> MCPToolError:
    return MCPToolError(
        f"MCP tool {name!r} can't send its arguments as JSON: {exc}",
        status_code=None,
        error_code=None,
        local_error=True,
    )


def _check_arguments(name: str, arguments: dict) -> None:

    try:
        types.CallToolRequestParams(name=name, arguments=arguments).model_dump(
            by_alias=True, mode="json", exclude_none=True
        )
    except ValueError as exc:
        raise _unsendable_arguments(name, exc) from exc


def _find_serialization_error(exc: BaseException) -> PydanticSerializationError | None:

    if isinstance(exc, PydanticSerializationError):
        return exc
    for sub in getattr(exc, "exceptions", None) or ():
        found = _find_serialization_error(sub)
        if found is not None:
            return found
    return None


async def _call_tool_once(
    mcp_url: str, token: str, name: str, arguments: dict, *, httpx_client_factory=None
) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    kwargs: dict[str, Any] = {
        "headers": headers,
        "timeout": MCP_CONNECT_TIMEOUT_SECONDS,
        "sse_read_timeout": MCP_READ_TIMEOUT_SECONDS,
    }
    if httpx_client_factory is not None:
        kwargs["httpx_client_factory"] = httpx_client_factory
    async with streamablehttp_client(mcp_url, **kwargs) as (read, write, _):
        async with ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=MCP_SESSION_TIMEOUT_SECONDS)
        ) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)

    return _parse_result(name, result)


def _parse_result(name: str, result: Any) -> dict:
    if result.isError:
        raise MCPToolError(
            f"MCP tool {name!r} failed at the protocol level: {_extract_text(result)}",
            status_code=None,
            error_code=None,
            protocol_error=True,
        )

    payload = result.structuredContent
    if payload is None:
        text = _extract_text(result)
        try:
            payload = json.loads(text) if text else {}
        except ValueError:
            payload = {}

    if isinstance(payload, dict) and "error" in payload:
        raise MCPToolError(
            payload.get("detail") or f"MCP tool {name!r} returned error {payload['error']!r}.",
            status_code=None,
            error_code=payload["error"],
            next_action=(payload.get("next_actions") or [None])[0],
        )

    return payload if isinstance(payload, dict) else {}


def _extract_text(result: Any) -> str:
    content = getattr(result, "content", None)
    if content:
        text = getattr(content[0], "text", None)
        if text is not None:
            return str(text)
    return str(result)


def _find_http_status_error(exc: BaseException) -> httpx.HTTPStatusError | None:

    if isinstance(exc, httpx.HTTPStatusError):
        return exc
    for sub in getattr(exc, "exceptions", None) or ():
        found = _find_http_status_error(sub)
        if found is not None:
            return found
    return None


def _wrap_http_status_error(name: str, exc: httpx.HTTPStatusError) -> MCPToolError:

    try:
        body = exc.response.text
        detail = body[:500] if body else str(exc)
    except httpx.ResponseNotRead:
        detail = str(exc)
    return MCPToolError(
        f"MCP tool {name!r} request failed with HTTP {exc.response.status_code}: {detail}",
        status_code=exc.response.status_code,
        error_code=None,
    )


@dataclass
class _ToolRequest:
    token: str = field(repr=False)
    name: str
    arguments: dict = field(repr=False)
    future: Future


class _PersistentCallFailure(Exception):


    def __init__(self, cause: BaseException, *, tool_started: bool) -> None:
        super().__init__(type(cause).__name__)
        self.cause = cause
        self.tool_started = tool_started

    def may_refresh_auth(self) -> bool:
        error = _find_http_status_error(self.cause)
        if error is None or error.response.status_code != 401:
            return False
        if not self.tool_started:
            return True
        try:
            request = error.request
            body = json.loads(request.content)
            return request.method == "POST" and body.get("method") == "tools/call"
        except (ValueError, httpx.RequestNotRead, AttributeError):
            return False


class _PersistentSession:


    def __init__(self, url: str, httpx_client_factory=None) -> None:
        self.url = url
        self.httpx_client_factory = httpx_client_factory
        self.pid = os.getpid()
        self._ready = threading.Event()
        self._state_lock = threading.Lock()
        self._call_lock = threading.Lock()
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._owner: asyncio.Task | None = None
        self._active: _ToolRequest | None = None
        self._tool_started = False
        self._thread = threading.Thread(target=self._thread_main, name="altruagent-mcp", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            self.close()
            raise TimeoutError("MCP session worker did not start")

    def _thread_main(self) -> None:
        asyncio.run(self._serve())

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._owner = asyncio.current_task()
        self._ready.set()
        pending: _ToolRequest | None = None
        try:
            while not self._closed:
                request = pending if pending is not None else await self._queue.get()
                pending = None
                if request is None:
                    return
                self._active = request
                self._tool_started = False
                token = request.token
                kwargs: dict[str, Any] = {
                    "headers": {"Authorization": f"Bearer {token}"},
                    "timeout": MCP_CONNECT_TIMEOUT_SECONDS,
                    "sse_read_timeout": MCP_READ_TIMEOUT_SECONDS,
                    "terminate_on_close": False,
                }
                if self.httpx_client_factory is not None:
                    kwargs["httpx_client_factory"] = self.httpx_client_factory
                try:
                    async with streamablehttp_client(self.url, **kwargs) as (read, write, _):
                        async with ClientSession(
                            read, write,
                            read_timeout_seconds=timedelta(seconds=MCP_SESSION_TIMEOUT_SECONDS),
                        ) as session:
                            await session.initialize()
                            known_tools: set[str] = set()
                            cursor = None
                            for _ in range(32):
                                listing = await session.list_tools(cursor=cursor)
                                known_tools.update(tool.name for tool in listing.tools)
                                cursor = listing.nextCursor
                                if not cursor:
                                    break
                            else:
                                raise RuntimeError("MCP tool listing exceeded pagination limit")
                            while True:
                                if not request.future.cancelled():
                                    if request.name not in known_tools:
                                        request.future.set_exception(MCPToolError(
                                            f"Unknown tool: {request.name!r} (not advertised by the server).",
                                            status_code=None,
                                            protocol_error=True,
                                        ))
                                    else:
                                        self._tool_started = True
                                        result = await session.call_tool(request.name, request.arguments)
                                        try:
                                            payload = _parse_result(request.name, result)
                                        except MCPToolError as exc:
                                            if not request.future.done():
                                                request.future.set_exception(exc)
                                        else:
                                            if not request.future.done():
                                                request.future.set_result(payload)
                                self._active = None
                                self._tool_started = False
                                request = await self._queue.get()
                                if request is None:
                                    return
                                self._active = request
                                if request.token != token:
                                    pending = request
                                    break
                except Exception as exc:
                    if self._active is not None and not self._active.future.done():
                        self._active.future.set_exception(_PersistentCallFailure(
                            exc, tool_started=self._tool_started,
                        ))
                    pending = None
                    self._active = None
                    self._tool_started = False
        except asyncio.CancelledError:
            pass
        finally:
            failure = _PersistentCallFailure(RuntimeError("MCP session closed"), tool_started=True)
            if self._active is not None and not self._active.future.done():
                self._active.future.set_exception(failure)
            while not self._queue.empty():
                queued = self._queue.get_nowait()
                if queued is not None and not queued.future.done():
                    queued.future.set_exception(failure)
            self._active = None
            self._closed = True

    def call(self, token: str, name: str, arguments: dict) -> dict:
        with self._call_lock:
            future: Future = Future()
            with self._state_lock:
                if self._closed or self.pid != os.getpid() or not self._thread.is_alive():
                    raise _PersistentCallFailure(RuntimeError("MCP session is closed"), tool_started=False)
                self._loop.call_soon_threadsafe(
                    self._queue.put_nowait, _ToolRequest(token, name, arguments, future),
                )
            try:
                return future.result(timeout=3 * MCP_SESSION_TIMEOUT_SECONDS + MCP_CONNECT_TIMEOUT_SECONDS + 5)
            except FutureTimeoutError as exc:
                future.cancel()
                self.close()
                raise _PersistentCallFailure(TimeoutError("MCP request exceeded total timeout"), tool_started=True) from exc

    def close(self) -> None:
        if self.pid != os.getpid():
            self._closed = True
            return
        with self._state_lock:
            if not self._closed:
                self._closed = True
                if self._loop is not None and self._loop.is_running():
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
        if threading.current_thread() is self._thread:
            return
        self._thread.join(timeout=5.0)
        if self._thread.is_alive() and self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._owner.cancel)
            self._thread.join(timeout=5.0)


_PERSISTENT_CACHE_LOCK = threading.Lock()


def close_persistent_sessions(client: "AltruAgentClient") -> None:

    with _PERSISTENT_CACHE_LOCK:
        sessions = list(getattr(client, "_mcp_persistent_sessions", {}).values())
        client._mcp_persistent_sessions = {}
    for session in sessions:
        session.close()


def _persistent_session(client: "AltruAgentClient", url: str, httpx_client_factory) -> _PersistentSession:
    with _PERSISTENT_CACHE_LOCK:
        sessions = getattr(client, "_mcp_persistent_sessions", None)
        if sessions is None:
            sessions = client._mcp_persistent_sessions = {}
        session = sessions.get(url)
        if session is not None and (
            session.pid != os.getpid() or session._closed or
            session.httpx_client_factory is not httpx_client_factory
        ):
            session.close()
            session = None
        if session is None:
            session = sessions[url] = _PersistentSession(url, httpx_client_factory)
        return session


def _call_persistent(client: "AltruAgentClient", url: str, name: str, arguments: dict, *, httpx_client_factory=None) -> dict:
    token = client._current_access_token()
    session = _persistent_session(client, url, httpx_client_factory)
    for attempt in range(2):
        try:
            return session.call(token, name, arguments)
        except MCPToolError:
            raise
        except _PersistentCallFailure as exc:
            cause = exc.cause
            serialization = _find_serialization_error(cause)
            if serialization is not None:
                raise _unsendable_arguments(name, serialization) from None
            if attempt == 0 and exc.may_refresh_auth():
                token = client._current_access_token(force_relogin=True)
                continue
            http_error = _find_http_status_error(cause)
            if http_error is not None:
                raise MCPToolError(
                    f"MCP tool {name!r} request failed with HTTP {http_error.response.status_code}.",
                    status_code=http_error.response.status_code,
                ) from None
            raise MCPToolError(
                f"MCP tool {name!r} transport failed ({type(cause).__name__}); reconcile state before retrying an action.",
                status_code=None,
            ) from None
    raise AssertionError("unreachable")


def call_tool(
    client: "AltruAgentClient",
    mcp_url: str,
    name: str,
    arguments: dict,
    *,
    httpx_client_factory=None,
) -> dict:

    _check_arguments(name, arguments)
    if os.environ.get("ALTRUAGENT_PERSISTENT_MCP", "").strip().lower() in {"1", "true", "yes", "on"}:
        return _call_persistent(client, mcp_url, name, arguments, httpx_client_factory=httpx_client_factory)
    token = client._current_access_token()
    try:
        return asyncio.run(
            _call_tool_once(mcp_url, token, name, arguments, httpx_client_factory=httpx_client_factory)
        )
    except MCPToolError:
        raise
    except Exception as exc:
        serialization_exc = _find_serialization_error(exc)
        if serialization_exc is not None:
            raise _unsendable_arguments(name, serialization_exc) from exc
        http_exc = _find_http_status_error(exc)
        if http_exc is None:
            raise MCPToolError(
                f"MCP tool {name!r} failed: {exc!r}", status_code=None, error_code=None
            ) from exc
        if http_exc.response.status_code != 401:
            raise _wrap_http_status_error(name, http_exc) from exc

        token = client._current_access_token(force_relogin=True)
        try:
            return asyncio.run(
                _call_tool_once(mcp_url, token, name, arguments, httpx_client_factory=httpx_client_factory)
            )
        except MCPToolError:
            raise
        except Exception as exc2:
            http_exc2 = _find_http_status_error(exc2)
            if http_exc2 is not None:
                raise _wrap_http_status_error(name, http_exc2) from exc2
            raise MCPToolError(
                f"MCP tool {name!r} failed after re-login: {exc2!r}", status_code=None, error_code=None
            ) from exc2
