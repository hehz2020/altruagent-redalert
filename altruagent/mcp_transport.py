"""Synchronous official-MCP transport, with an optional persistent session.

The compatibility path opens a fresh official SDK connection for each call.
Set ``ALTRUAGENT_PERSISTENT_MCP=1`` to reuse one connection, MCP handshake,
and tool-schema cache per client/URL. This matters for real-time games.

A persistent connection lives in a dedicated thread. One coroutine owns its
async context managers from entry through exit (required by AnyIO's cancel
scopes), and executes requests sequentially. No asyncio objects cross worker
processes. ``AltruAgentClient.close()`` closes its sessions and their threads.

Transport failures are returned without replaying a possibly accepted action.
The next caller reconnects. A rejected HTTP 401 may refresh the client's own
auth state and retry once; it never creates an independent authentication
system. Initialization and schema loading occur before any tool mutation.
"""

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

# How long one tool call may take. The SDK's own defaults are 30 s to connect
# and 300 s to read, so a connection that silently died (a Wi-Fi or VPN
# switch, a laptop waking up) would freeze the agent for five minutes. The
# longest healthy call is wait_for_update: the server holds it at most 25 s
# (GameAPI's WAIT_MAX_TIMEOUT_SECONDS), so the read timeout stays well above
# that plus network time. The session timeout is a backstop for an answer
# that trickles in without ever finishing. A call that times out raises
# MCPToolError (no error code), which the runner retries in place.
MCP_CONNECT_TIMEOUT_SECONDS = 10.0
MCP_READ_TIMEOUT_SECONDS = 40.0
MCP_SESSION_TIMEOUT_SECONDS = 45.0


class MCPToolError(PlatformError):
    """A tool call reached the server but failed — either a structured
    application-level error the tool itself returned (``error_code`` is one
    of MCP's own codes, e.g. ``STALE_STATE``/``GAME_ALREADY_COMPLETE``), or a
    protocol/transport-level failure (``error_code`` is ``None`` in that
    case — including an HTTP-level rejection, surfaced with its
    ``status_code``).

    ``protocol_error`` is True when the server answered, but with an MCP tool
    error (``isError``) rather than a result: the tool's arguments failed
    validation, or the tool itself crashed. GameAPI sends every game error
    as a normal result with an ``error`` code, so this is a call the server
    can't handle, likely to fail the same way again. It is not a connection
    problem (``errors.is_transient_error`` is False for it).

    ``local_error`` is True when the call never left this process: its
    arguments can't be sent as JSON (for example a numpy number, bytes, or an
    object of the agent's own class inside a move). Neither a connection nor
    a server problem; sending the same arguments again fails the same way
    (``errors.is_transient_error`` is False for it too).
    """

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
    """Raise ``MCPToolError(local_error=True)`` if the SDK couldn't send
    ``arguments``: the same JSON conversion ``ClientSession.call_tool`` does,
    done before any connection is opened. Inside the SDK that failure would
    surface wrapped in anyio ExceptionGroups, indistinguishable from a
    dropped connection.
    """
    try:
        types.CallToolRequestParams(name=name, arguments=arguments).model_dump(
            by_alias=True, mode="json", exclude_none=True
        )
    except ValueError as exc:  # PydanticSerializationError, UnicodeDecodeError, ValidationError
        raise _unsendable_arguments(name, exc) from exc


def _find_serialization_error(exc: BaseException) -> PydanticSerializationError | None:
    """A ``PydanticSerializationError`` anywhere in anyio's ExceptionGroup
    wrapping: the SDK failed to turn this call's arguments into JSON (a
    backstop for ``_check_arguments``)."""
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
        # The SDK builds httpx.Timeout(timeout, read=sse_read_timeout) from these.
        "timeout": MCP_CONNECT_TIMEOUT_SECONDS,
        "sse_read_timeout": MCP_READ_TIMEOUT_SECONDS,
    }
    if httpx_client_factory is not None:
        # Test-only seam: lets unit tests exercise the real streamablehttp_client
        # / ClientSession code paths (JSON-RPC framing, error unwrapping) against
        # an httpx.MockTransport-backed AsyncClient instead of real sockets,
        # rather than replacing the SDK's classes with hand-built fakes.
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
    """Unwrap anyio's ExceptionGroup wrapping.

    Confirmed empirically (not assumed): ``streamablehttp_client`` runs its
    read/write loops inside ``anyio.create_task_group()``
    (mcp/client/streamable_http.py), so an HTTP-level failure — including
    the "Invalid Host header" 421 this module's docstring describes — never
    arrives as a bare ``httpx.HTTPStatusError``; it's always wrapped in an
    ``ExceptionGroup``/``BaseExceptionGroup``, one or more levels deep. A
    plain ``except httpx.HTTPStatusError`` here would silently never match,
    which would have made the 401-retry-once behavior in ``call_tool`` dead
    code — probed directly against a real ``httpx.MockTransport`` before
    trusting this, not inferred from documentation.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc
    for sub in getattr(exc, "exceptions", None) or ():
        found = _find_http_status_error(sub)
        if found is not None:
            return found
    return None


def _wrap_http_status_error(name: str, exc: httpx.HTTPStatusError) -> MCPToolError:
    """Build a clean ``MCPToolError`` from an HTTP-level failure.

    ``exc.response`` is a *streaming* response: the SDK's own transport
    (``mcp.client.streamable_http``'s ``stream_within_origin``) calls
    ``raise_for_status()`` while the response is still open, then closes it
    via its own ``finally: await response.aclose()`` as this exception
    unwinds — before it ever reaches ``call_tool()``'s except clause, and
    without the body ever having been read. Accessing ``.text``/``.content``
    on a closed, never-read streaming response raises
    ``httpx.ResponseNotRead`` — confirmed empirically (a real 421/401
    response body is fully drained by the time it gets here) — which would
    otherwise mask the original HTTP status behind an unrelated crash. We
    have no way to read the body earlier (that would mean patching the SDK's
    own transport), so fall back to ``str(exc)`` instead: httpx's own
    ``HTTPStatusError`` message already includes the status code, reason
    phrase, and URL, which is enough to act on even without the body.
    """
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
    """Carry an SDK failure without discarding whether an action was sent."""

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
        # A 401 for the actual tool POST rejects that action. A 401 in an
        # unrelated GET/notification/schema request does not prove that an
        # in-flight action was rejected, so it must never cause a replay.
        try:
            request = error.request
            body = json.loads(request.content)
            return request.method == "POST" and body.get("method") == "tools/call"
        except (ValueError, httpx.RequestNotRead, AttributeError):
            return False


class _PersistentSession:
    """One SDK owner task, in one private loop, for this client and URL.

    This deliberately does not enter a context manager through one
    ``run_coroutine_threadsafe`` call and exit it through another: those
    calls would run in different tasks and corrupt AnyIO's cancel scopes.
    """

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
        # Created here, never at import time or before multiprocessing spawn.
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
                    # GameAPI is stateless HTTP. A best-effort DELETE during
                    # teardown adds no value and can delay shutdown by 40 s.
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
                            # The SDK otherwise fetches schemas *after* its
                            # first tool result. Prefetching makes all setup
                            # failures occur before any possibly mutating call.
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
                except Exception as exc:  # SDK task-group errors arrive here after safe scope exit.
                    if self._active is not None and not self._active.future.done():
                        self._active.future.set_exception(_PersistentCallFailure(
                            exc, tool_started=self._tool_started,
                        ))
                    # Never replay the interrupted request. Only a later call
                    # opens a fresh transport; the runner first reconciles state.
                    pending = None
                    self._active = None
                    self._tool_started = False
        except asyncio.CancelledError:
            pass  # All SDK context managers have already unwound in this task.
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
        # Public callers are synchronous. Keep requests sequential even if a
        # user's custom agent happens to call from multiple threads.
        with self._call_lock:
            future: Future = Future()
            with self._state_lock:
                if self._closed or self.pid != os.getpid() or not self._thread.is_alive():
                    raise _PersistentCallFailure(RuntimeError("MCP session is closed"), tool_started=False)
                self._loop.call_soon_threadsafe(
                    self._queue.put_nowait, _ToolRequest(token, name, arguments, future),
                )
            try:
                # Initialization, schema load, and the actual request each
                # have an SDK timeout. This is also a total wall-time backstop.
                return future.result(timeout=3 * MCP_SESSION_TIMEOUT_SECONDS + MCP_CONNECT_TIMEOUT_SECONDS + 5)
            except FutureTimeoutError as exc:
                future.cancel()
                self.close()
                raise _PersistentCallFailure(TimeoutError("MCP request exceeded total timeout"), tool_started=True) from exc

    def close(self) -> None:
        # A fork cannot safely use locks/loops inherited from other threads.
        # Production uses spawn, but dropping an inherited owner is still safe.
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
    """Idempotent client-lifecycle cleanup, also useful to standalone callers."""
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
                # Do not echo response bodies, URLs, tokens or SDK exception
                # reprs into match logs. The status suffices for recovery.
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
    """Call one MCP tool and return its parsed result payload as a plain dict.

    ``mcp_url`` is ``{game_server_url}/mcp`` (see ``MCPGameSession``). Raises
    ``MCPToolError`` (a ``PlatformError`` subclass) for both application-level
    tool errors and transport/HTTP-level failures, so callers only need one
    except clause. A 401 triggers exactly one re-login + retry, reusing
    ``AltruAgentClient``'s own auth state — see the module docstring.

    ``httpx_client_factory`` is a test-only seam (see ``_call_tool_once``) —
    production callers never pass it.
    """
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
    except Exception as exc:  # noqa: BLE001 - deliberately broad: network errors,
        # anyio ExceptionGroups, or any other mcp-SDK-internal failure should
        # all surface as an AltruAgentError, not a raw third-party exception
        # leaking out of this SDK. _find_http_status_error unwraps whatever
        # anyio's task-group wrapping did, so the 401 check below still works
        # regardless of how many ExceptionGroup layers deep it's nested.
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
        except Exception as exc2:  # noqa: BLE001
            http_exc2 = _find_http_status_error(exc2)
            if http_exc2 is not None:
                raise _wrap_http_status_error(name, http_exc2) from exc2
            raise MCPToolError(
                f"MCP tool {name!r} failed after re-login: {exc2!r}", status_code=None, error_code=None
            ) from exc2
