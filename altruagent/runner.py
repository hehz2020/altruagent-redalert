from __future__ import annotations

import linecache
import os
import math
import random
import re
import sysconfig
import time
import traceback
from dataclasses import replace
from typing import Any, Callable, NamedTuple, Protocol, Union

from .errors import AltruAgentError, is_transient_error
from .mcp_game import MCPGameSession
from .mcp_transport import MCPToolError
from .models import DecisionContext, GameState, LegalAction, Match

DEFAULT_WAIT_SECONDS = 5.0
REALTIME_FALLBACK_WAIT_SECONDS = 0.2

TRANSIENT_RETRY_FIRST_SECONDS = 1.0
TRANSIENT_RETRY_MAX_SECONDS = 5.0
TRANSIENT_GIVE_UP_SECONDS = 90.0

_WAIT_BUSY_ERROR_CODE = "TOO_MANY_WAITS"

WAIT_FOR_UPDATE_TIMEOUT_SECONDS = 20.0

_RACE_ERROR_CODES = frozenset(
    {
        "STALE_STATE",
        "NOT_YOUR_TURN",
        "WRONG_PHASE",
        "GAME_ALREADY_COMPLETE",
        "PLAYER_ELIMINATED",
    }
)

_MESSAGE_SCOPED_ERROR_CODES = frozenset(
    {
        "INVALID_RECIPIENTS",
        "MESSAGE_TOO_LONG",
        "TOO_MANY_WORDS",
        "INVALID_CONTENT",
        "MESSAGES_QUOTA_EXCEEDED",
        "MESSAGING_DISABLED",
    }
)

_ACTION_SCOPED_ERROR_CODES = frozenset({"INVALID_ACTION"})

_REALTIME_TRANSIENT_ERROR_CODES = frozenset({"RUNTIME_TEMPORARILY_UNAVAILABLE"})
REALTIME_RETRY_SECONDS = 1.0
_REALTIME_PACING = "realtime"

GAME_CONFIG_RETRY_FIRST_SECONDS = 5.0
GAME_CONFIG_RETRY_MAX_SECONDS = 30.0

_CAPABILITY_ERROR_CODE = "RUNTIME_UNAVAILABLE"

_MESSAGING_PHASE = "messaging"


class _Resign:


    __slots__ = ()

    def __repr__(self) -> str:
        return "RESIGN"


RESIGN = _Resign()


class _Wait:


    __slots__ = ()

    def __repr__(self) -> str:
        return "WAIT"


WAIT = _Wait()


class _TerminateMessaging:


    __slots__ = ()

    def __repr__(self) -> str:
        return "TERMINATE_MESSAGING"


TERMINATE_MESSAGING = _TerminateMessaging()


class SendMessage:


    __slots__ = ("content", "recipients")

    def __init__(self, content: str, recipients: list[int] | None = None) -> None:
        self.content = content
        self.recipients = list(recipients) if recipients else []

    def __repr__(self) -> str:
        return f"SendMessage(content={self.content!r}, recipients={self.recipients!r})"


class WithReasoning:


    __slots__ = ("action", "reasoning_summary")

    def __init__(self, action: Any, reasoning_summary: str | None) -> None:
        self.action = action
        text = reasoning_summary.strip() if isinstance(reasoning_summary, str) else ""
        self.reasoning_summary = text or None

    def __repr__(self) -> str:
        return f"WithReasoning(action={self.action!r}, reasoning_summary={self.reasoning_summary!r})"


Decision = Union[int, str, LegalAction, dict, _Resign, _Wait, WithReasoning]
MessageDecision = Union[SendMessage, _TerminateMessaging]


class ChoosesAction(Protocol):


    def choose_action(self, state: GameState, context: DecisionContext) -> Decision: ...


DecisionFn = Callable[[GameState, DecisionContext], Decision]
MessageDecisionFn = Callable[[GameState, DecisionContext], MessageDecision]


class RunnerError(Exception):
    pass


class DecisionError(RunnerError):
    pass


class UnsupportedGameFlowError(RunnerError):
    pass


class _PlayAction(NamedTuple):


    action_id: str | None
    action: dict | None
    reasoning_summary: str | None = None


def _resolve_decision_fn(choose_action: Any) -> DecisionFn:

    if callable(choose_action):
        return choose_action
    method = getattr(choose_action, "choose_action", None)
    if callable(method):
        return method
    raise DecisionError(
        f"{choose_action!r} is not callable and has no callable 'choose_action' "
        "method. Expected a function like choose_action(state, context), or an "
        "object exposing one."
    )


def _resolve_message_decision_fn(choose_action: Any) -> MessageDecisionFn:

    method = getattr(choose_action, "choose_message", None)
    if callable(method):
        return method
    return _default_choose_message


def _default_choose_message(state: GameState, context: DecisionContext) -> MessageDecision:
    return TERMINATE_MESSAGING


_GAME_NAMES = {"red_alert": "Red Alert"}


def _cant_play_realtime_message(context: DecisionContext) -> str:

    game_type = context.game_type or ""
    name = _GAME_NAMES.get(game_type) or (f"this real-time game ({game_type})" if game_type else "this real-time game")
    return (
        f"Your agent can't play {name}: it picks its move from state.legal_actions, which is empty "
        "in a real-time game (a move there is a batch of orders your agent writes itself). The "
        "placeholder agent/agent.py works this way. See GAMES.md, or run with --agent "
        "examples.llm_agent, which can play it."
    )


_STDLIB_DIRS = tuple(
    {
        os.path.realpath(path) + os.sep
        for path in (sysconfig.get_path("stdlib"), sysconfig.get_path("platstdlib"))
        if path
    }
)
_NAMES_LEGAL_ACTIONS = re.compile(r"\blegal_actions\b")


def _is_stdlib_file(filename: str) -> bool:
    if filename.startswith("<frozen "):
        return True
    path = os.path.realpath(filename)
    return path.startswith(_STDLIB_DIRS) and "site-packages" not in path and "dist-packages" not in path


def _failing_expression(frame: traceback.FrameSummary) -> str:

    line = linecache.getline(frame.filename, frame.lineno or 0)
    if line and frame.end_lineno == frame.lineno and frame.colno is not None and frame.end_colno is not None:
        return line.encode("utf-8")[frame.colno : frame.end_colno].decode("utf-8", "replace")
    return line


def _picked_from_legal_actions(exc: BaseException) -> bool:

    for frame in reversed(traceback.extract_tb(exc.__traceback__)):
        if not _is_stdlib_file(frame.filename):
            return bool(_NAMES_LEGAL_ACTIONS.search(_failing_expression(frame)))
    return False


def _invoke_decision(decision_fn: DecisionFn, state: GameState, context: DecisionContext) -> Any:
    try:
        return decision_fn(state, context)
    except Exception as exc:
        if (
            isinstance(exc, IndexError)
            and not state.legal_actions
            and _is_realtime(state)
            and _picked_from_legal_actions(exc)
        ):
            raise DecisionError(_cant_play_realtime_message(context)) from exc
        raise DecisionError(
            f"choose_action raised {exc!r} for session {context.session_id!r}."
        ) from exc


def _invoke_message_decision(
    decision_fn: MessageDecisionFn, state: GameState, context: DecisionContext
) -> Any:
    try:
        return decision_fn(state, context)
    except Exception as exc:
        raise DecisionError(
            f"choose_message raised {exc!r} for session {context.session_id!r}."
        ) from exc


def _is_realtime(state: GameState) -> bool:

    pacing = state.raw.get("pacing")
    return isinstance(pacing, dict) and pacing.get("mode") == _REALTIME_PACING


def _fallback_wait_seconds(state: GameState, turn_based_wait: float) -> float:

    if not _is_realtime(state):
        return turn_based_wait
    pacing = state.raw.get("pacing") or {}
    interval = pacing.get("min_batch_interval_s", REALTIME_FALLBACK_WAIT_SECONDS)
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval):
        interval = REALTIME_FALLBACK_WAIT_SECONDS
    return max(REALTIME_FALLBACK_WAIT_SECONDS, interval)


def _resolve_result_hook(choose_action: Any) -> Callable[[dict, DecisionContext], Any] | None:

    method = getattr(choose_action, "on_action_result", None)
    return method if callable(method) else None


def _report_result(hook, result: dict, context: DecisionContext) -> None:
    if hook is None:
        return
    try:
        hook(result, context)
    except Exception as exc:
        raise DecisionError(
            f"on_action_result raised {exc!r} for session {context.session_id!r}."
        ) from exc


def _with_game_config(game: Any, context: DecisionContext) -> DecisionContext:

    getter = getattr(game, "get_game_config", None)
    if context.game_config is not None or not context.game_type or not callable(getter):
        return context
    try:
        config = getter(context.game_type)
    except AltruAgentError as exc:
        if isinstance(exc, MCPToolError) or _is_transient(exc):
            return context
        raise
    return replace(context, game_config=config) if isinstance(config, dict) and config else context


def _validate_decision(decision: Any, legal_actions: list[LegalAction]) -> Union[_Resign, _Wait, _PlayAction]:
    if isinstance(decision, WithReasoning):
        inner = decision.action
        if inner is RESIGN or inner is WAIT or isinstance(inner, WithReasoning):
            raise DecisionError(
                "WithReasoning(...) must wrap a move (a LegalAction, action_id, "
                f"int, or structured dict), not {inner!r}."
            )
        return _validate_decision(inner, legal_actions)._replace(
            reasoning_summary=decision.reasoning_summary
        )

    if decision is RESIGN:
        return RESIGN

    if decision is WAIT:
        return WAIT

    if isinstance(decision, bool):
        raise DecisionError(
            "choose_action must return a LegalAction, its action_id (str), a "
            "matching int, a structured dict action, or altruagent.RESIGN — "
            f"got {decision!r} (bool)."
        )

    if isinstance(decision, LegalAction):
        candidate = decision.action_id
    elif isinstance(decision, str):
        candidate = decision
    elif isinstance(decision, int):
        candidate = str(decision)
    elif isinstance(decision, dict):
        if not decision:
            raise DecisionError(
                "choose_action returned an empty dict — provide the structured "
                "action payload the server expects (e.g. "
                "{'type': 'submit_team', 'team': [...]})."
            )
        return _PlayAction(action_id=None, action=decision)
    else:
        raise DecisionError(
            "choose_action must return a LegalAction from state.legal_actions, "
            "its action_id (str), a matching int, a structured dict action, or "
            f"altruagent.RESIGN — got {decision!r} ({type(decision).__name__})."
        )

    matched = next((a for a in legal_actions if a.action_id == candidate), None)
    if matched is None:
        raise DecisionError(
            f"choose_action returned {decision!r}, which does not match any "
            f"current legal action's action_id (tried {candidate!r} against "
            f"{[a.action_id for a in legal_actions]!r}). An int is only valid "
            "for OpenSpiel-family games whose action_ids are stringified "
            "integers — never guessed/coerced for other games."
        )
    return _PlayAction(action_id=matched.action_id, action=None)


def _validate_message_decision(decision: Any) -> MessageDecision:
    if decision is TERMINATE_MESSAGING:
        return decision
    if not isinstance(decision, SendMessage):
        raise DecisionError(
            "choose_message must return an altruagent.SendMessage(...) or "
            f"altruagent.TERMINATE_MESSAGING — got {decision!r} "
            f"({type(decision).__name__})."
        )
    return decision


def _last_message_seq(state: GameState, extra: dict | None = None) -> int | None:

    seqs = [m.index for m in state.new_messages]
    if extra:
        messages = list(extra.get("new_messages") or [])
        if isinstance(extra.get("message"), dict):
            messages.append(extra["message"])
        seqs += [m["seq"] for m in messages if isinstance(m, dict) and isinstance(m.get("seq"), int)]
    return max(seqs) if seqs else None


def _is_unknown_tool_error(exc: MCPToolError) -> bool:

    return exc.error_code is None and "unknown tool" in str(exc).lower()


def _is_transient(exc: BaseException) -> bool:

    if isinstance(exc, MCPToolError):
        if _is_unknown_tool_error(exc):
            return False
        if exc.error_code == _WAIT_BUSY_ERROR_CODE:
            return True
    return is_transient_error(exc)


def _is_tool_failure(exc: BaseException) -> bool:

    return (
        isinstance(exc, MCPToolError)
        and getattr(exc, "protocol_error", False)
        and not _is_unknown_tool_error(exc)
    )


_UNSENDABLE_HINT = (
    "Use plain Python values only: str, int, float, bool, None, lists and dicts "
    "(for example int(x) for a numpy number)."
)


def _is_unsendable(exc: BaseException) -> bool:
    return isinstance(exc, MCPToolError) and getattr(exc, "local_error", False)


def _is_retried(exc: BaseException) -> bool:

    return _is_transient(exc) or _is_tool_failure(exc)


class _TransientRetry:


    def __init__(self, *, sleep: Callable[[float], None], now: Callable[[], float],
                 log: Callable[[str], None]) -> None:
        self._sleep = sleep
        self._now = now
        self._log = log
        self._since: float | None = None
        self._back = ""
        self._streak = 0
        self._tool_failure_retried = False

    def failed(self, exc: BaseException, *, read: bool = False) -> None:

        current = self._now()
        if _is_tool_failure(exc) and not read:
            if self._tool_failure_retried:
                raise exc
            self._tool_failure_retried = True
            self._log(f"The game server couldn't handle that call ({exc}); trying once more.")
        elif self._since is None:
            self._since = current
            if _is_tool_failure(exc):
                self._back = "The game server answers again; the game goes on."
                self._log(f"The game server couldn't answer ({exc}); retrying for up to "
                          f"{TRANSIENT_GIVE_UP_SECONDS:.0f}s.")
            else:
                self._back = "Connection back; the game goes on."
                self._log(f"Connection problem ({exc}); retrying for up to {TRANSIENT_GIVE_UP_SECONDS:.0f}s.")
        elif current - self._since >= TRANSIENT_GIVE_UP_SECONDS:
            raise exc
        delay = min(TRANSIENT_RETRY_MAX_SECONDS, TRANSIENT_RETRY_FIRST_SECONDS * 2 ** self._streak)
        self._streak += 1
        self._sleep(delay * random.uniform(0.5, 1.0))

    def succeeded(self) -> None:
        if self._since is not None:
            self._log(self._back)
        self._since = None
        self._streak = 0
        self._tool_failure_retried = False


def _resign_left_game_running(result: Any) -> bool:

    return isinstance(result, dict) and result.get("is_terminal") is False


def _terminal_game_state(last_state: GameState, result: dict) -> GameState:

    return GameState.from_mcp_state(last_state.raw, result=result)


def run_game(
    game: MCPGameSession,
    context: DecisionContext,
    choose_action: DecisionFn,
    *,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = print,
) -> GameState:

    decision_fn = _resolve_decision_fn(choose_action)
    message_decision_fn = _resolve_message_decision_fn(choose_action)
    result_hook = _resolve_result_hook(choose_action)
    timing_hook = getattr(choose_action, "on_runtime_timing", None)
    timing_hook = timing_hook if callable(timing_hook) else None
    timing_started = now() if timing_hook is not None else 0.0

    def report_timing(record: dict) -> None:
        if timing_hook is not None:
            try:
                timing_hook(record, context)
            except Exception:
                pass

    def timed(phase: str, call: Callable[[], Any]) -> Any:
        if timing_hook is None:
            return call()
        started = now()
        succeeded = False
        answer = None
        try:
            answer = call()
            succeeded = True
            return answer
        finally:
            ended = now()
            record = {"phase": phase, "elapsed_s": max(0.0, ended - started),
                      "since_start_s": max(0.0, ended - timing_started), "ok": succeeded}
            if isinstance(answer, GameState):
                record["state_version"] = answer.state_version
                game_time = answer.raw.get("time")
                if isinstance(game_time, dict):
                    seconds = game_time.get("game_seconds")
                    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and math.isfinite(seconds):
                        record["game_seconds"] = seconds
            report_timing(record)

    long_poll_supported = True
    config_retry_at = float("-inf")
    config_retry_delay = GAME_CONFIG_RETRY_FIRST_SECONDS
    config_unavailable_logged = False
    retry = _TransientRetry(sleep=sleep, now=now, log=log)

    def read(call: Callable[[], Any], *, settles: bool = True, phase: str | None = None) -> Any:

        while True:
            try:
                answer = timed(phase or getattr(call, "__name__", "read"), call)
            except AltruAgentError as exc:
                if not _is_retried(exc):
                    raise
                retry.failed(exc, read=True)
                continue
            if settles:
                retry.succeeded()
            return answer

    def recover(exc: AltruAgentError) -> GameState:

        retry.failed(exc)
        return read(game.get_state, settles=False)

    def wait(current: GameState, message_seq: int | None) -> GameState:
        nonlocal long_poll_supported
        if long_poll_supported:
            try:
                return read(
                    lambda: game.wait_for_update(
                        since_version=current.state_version,
                        since_message_seq=message_seq,
                        since_is_current_actor=bool(current.is_current_actor),
                        since_phase=current.phase,
                        timeout_seconds=WAIT_FOR_UPDATE_TIMEOUT_SECONDS,
                    ),
                    phase="wait_for_update",
                )
            except MCPToolError as exc:
                if not _is_unknown_tool_error(exc):
                    raise
                long_poll_supported = False
        timed("fallback_wait", lambda: sleep(_fallback_wait_seconds(current, wait_seconds)))
        return read(game.get_state)

    state = read(game.get_state)

    while True:
        if state.is_terminal:
            result = read(game.get_result)
            return _terminal_game_state(state, result)

        if state.raw.get("eliminated"):
            state = wait(state, _last_message_seq(state))
            continue

        if state.phase == _MESSAGING_PHASE:
            decision = _validate_message_decision(
                _invoke_message_decision(message_decision_fn, state, context)
            )
            try:
                if decision is TERMINATE_MESSAGING:
                    result = game.send_message(message_type="terminate")
                else:
                    result = game.send_message(
                        message_type="chat",
                        content=decision.content,
                        recipients=decision.recipients,
                    )
            except AltruAgentError as exc:
                code = exc.error_code if isinstance(exc, MCPToolError) else None
                if code in _RACE_ERROR_CODES:
                    state = read(game.get_state)
                    continue
                if code == _CAPABILITY_ERROR_CODE:
                    raise UnsupportedGameFlowError(
                        f"Match {context.session_id!r} reported phase="
                        f"{_MESSAGING_PHASE!r}, but its adapter does not support "
                        "messaging tools — a runner/adapter mismatch, not a "
                        "contestant bug."
                    ) from exc
                if code in _MESSAGE_SCOPED_ERROR_CODES:
                    raise DecisionError(
                        f"choose_message produced an invalid messaging action "
                        f"for session {context.session_id!r}: {exc}"
                    ) from exc
                if _is_unsendable(exc):
                    raise DecisionError(
                        f"choose_message produced a message that can't be sent "
                        f"for session {context.session_id!r} ({exc}). {_UNSENDABLE_HINT}"
                    ) from exc
                if _is_retried(exc):
                    state = recover(exc)
                    continue
                raise
            retry.succeeded()
            if result.get("phase") == "moving":
                state = read(game.get_state)
            else:
                state = wait(state, _last_message_seq(state, result))
            continue

        if state.is_current_actor:
            realtime = _is_realtime(state)
            if realtime and context.game_config is None and now() >= config_retry_at:
                context = timed("get_game_config", lambda: _with_game_config(game, context))
                if context.game_config is None:
                    config_retry_at = now() + config_retry_delay
                    config_retry_delay = min(config_retry_delay * 2, GAME_CONFIG_RETRY_MAX_SECONDS)
                    if not config_unavailable_logged:
                        log("Game configuration unavailable; continuing play and retrying with backoff.")
                        config_unavailable_logged = True
                elif config_unavailable_logged:
                    log("Game configuration recovered; subsequent decisions have the rules and map.")
            if state.raw.get("legal_actions") is None:
                legal = read(game.get_legal_actions, settles=False)
                state.legal_actions = [
                    LegalAction.from_dict(a) for a in legal.get("actions") or []
                ]
                state.state_version = int(legal.get("state_version", state.state_version))

            decision = _validate_decision(
                timed("decision", lambda: _invoke_decision(decision_fn, state, context)), state.legal_actions
            )
            if decision is WAIT:
                if not realtime:
                    raise DecisionError(
                        "choose_action returned altruagent.WAIT in a turn-based game "
                        f"(session {context.session_id!r}); WAIT is only for real-time "
                        "games, where nothing needs to be sent right now."
                    )
                state = wait(state, _last_message_seq(state))
                continue
            left_the_game = False
            try:
                if decision is RESIGN:
                    result = game.resign()
                    if not _resign_left_game_running(result):
                        return _terminal_game_state(state, result)
                    left_the_game = True
                else:
                    reasoning = (
                        {"reasoning_summary": decision.reasoning_summary}
                        if decision.reasoning_summary
                        else {}
                    )
                    result = timed("play_action", lambda: game.play_action(
                        action_id=decision.action_id,
                        action=decision.action,
                        state_version=state.state_version,
                        **reasoning,
                    ))
            except AltruAgentError as exc:
                code = exc.error_code if isinstance(exc, MCPToolError) else None
                recovered = code in _RACE_ERROR_CODES or (
                    realtime
                    and code in _ACTION_SCOPED_ERROR_CODES | _REALTIME_TRANSIENT_ERROR_CODES
                )
                if recovered:
                    _report_result(result_hook, {"error": code, "detail": str(exc)}, context)
                    if code in _REALTIME_TRANSIENT_ERROR_CODES:
                        sleep(REALTIME_RETRY_SECONDS)
                    state = read(game.get_state)
                    continue
                if code == _CAPABILITY_ERROR_CODE:
                    raise UnsupportedGameFlowError(
                        f"Match {context.session_id!r} reported it was this "
                        "agent's turn, but its adapter rejected the move "
                        "capability — a runner/adapter mismatch, not a "
                        "contestant bug."
                    ) from exc
                if code in _ACTION_SCOPED_ERROR_CODES:
                    raise DecisionError(
                        f"choose_action produced an invalid action for session "
                        f"{context.session_id!r}: {exc}"
                    ) from exc
                if _is_unsendable(exc):
                    raise DecisionError(
                        f"choose_action returned a move that can't be sent "
                        f"for session {context.session_id!r} ({exc}). {_UNSENDABLE_HINT}"
                    ) from exc
                if _is_retried(exc):
                    if code is not None:
                        _report_result(result_hook, {"error": code, "detail": str(exc)}, context)
                    state = recover(exc)
                    continue
                raise
            retry.succeeded()
            if left_the_game:
                state = read(game.get_state)
                continue
            if isinstance(result, dict):
                _report_result(result_hook, result, context)
            post_move = result.get("state") if isinstance(result, dict) else None
            state = (
                GameState.from_mcp_state(post_move)
                if isinstance(post_move, dict)
                else read(game.get_state)
            )
            continue

        state = wait(state, _last_message_seq(state))


def run_match(
    match: Match,
    agent_id: str,
    choose_action: DecisionFn,
    *,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> GameState:

    game = match.game()
    context = DecisionContext(
        session_id=match.session_id,
        tournament_id=match.tournament_id,
        game_type=match.game_type,
        agent_id=agent_id,
    )
    return run_game(game, context, choose_action, wait_seconds=wait_seconds, sleep=sleep)
