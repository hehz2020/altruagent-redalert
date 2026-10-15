from __future__ import annotations

import os
import random
import time
from functools import partial
from typing import TYPE_CHECKING, Callable, NamedTuple

from .client import AltruAgentClient
from .console import print_line
from .errors import AuthenticationError, PlatformError, is_transient_error
from .mcp_game import MCPGameSession
from .models import Match
from .runner import DecisionError, UnsupportedGameFlowError, _is_transient
from .runner import run_match as _default_run_match

if TYPE_CHECKING:
    from .models import GameState
    from .official import OfficialAgentClient

EXIT_SUCCESS = 0
EXIT_MATCH_FAILURE = 1
EXIT_UNEXPECTED = 2
EXIT_SEAT_BUSY = 3
EXIT_NOT_CONNECTED = 4
EXIT_REGISTRATION_INCOMPLETE = 5
EXIT_CONNECTION_LOST = 6
EXIT_KEY_REFUSED = 7

FIRST_GRANT_RETRY_SECONDS = 60.0
FIRST_GRANT_RETRY_FIRST_SECONDS = 3.0
FIRST_GRANT_RETRY_MAX_SECONDS = 15.0

_MATCH_SCOPED_ERRORS = (DecisionError, UnsupportedGameFlowError, PlatformError)


class WorkerInput(NamedTuple):


    session_id: str
    tournament_id: str | None
    game_type: str | None
    agent_id: str


def run_worker(
    worker_input: WorkerInput,
    *,
    client_factory: Callable[[], AltruAgentClient] = AltruAgentClient,
    match_factory: Callable[..., Match] = Match.from_dict,
    agent_module: object | None = None,
    run_match_fn: Callable[..., "GameState"] = _default_run_match,
) -> int:

    pid = os.getpid()
    print_line(f"[worker pid={pid}] starting session_id={worker_input.session_id}")

    client: AltruAgentClient | None = None
    try:
        if agent_module is None:
            import agent.agent as agent_module

        create_agent = getattr(agent_module, "create_agent", None)
        if not callable(create_agent):
            print_line(
                f"[worker pid={pid}] agent.agent.create_agent is missing or "
                "not callable — nothing to play this match with."
            )
            return EXIT_UNEXPECTED

        client = client_factory()
        match = match_factory(
            {
                "session_id": worker_input.session_id,
                "tournament_id": worker_input.tournament_id,
                "game_type": worker_input.game_type,
                "status": "in_progress",
            },
            client=client,
        )

        contestant = create_agent()
        final_state = run_match_fn(match, worker_input.agent_id, contestant)
        print_line(
            f"[worker pid={pid}] match finished session_id={worker_input.session_id} "
            f"termination_reason={final_state.termination_reason}"
        )
        return EXIT_SUCCESS
    except KeyboardInterrupt:
        print_line(f"[worker pid={pid}] interrupted, stopping")
        return EXIT_SUCCESS
    except _MATCH_SCOPED_ERRORS as exc:
        print_line(
            f"[worker pid={pid}] match failed session_id={worker_input.session_id}: {exc}"
        )
        return EXIT_MATCH_FAILURE
    except Exception as exc:
        print_line(f"[worker pid={pid}] unexpected error: {exc!r}")
        return EXIT_UNEXPECTED
    finally:
        if client is not None:
            client.close()


_OUTCOME_WORDS = {"win": "won", "loss": "lost", "draw": "drew", "resigned": "resigned", "timed_out": "timed out"}


def _number(value) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _score(final_state, agent_id: str) -> float | None:
    result = getattr(final_state, "final_result", None) or {}
    score = _number(result.get("your_return"))
    if score is None:
        score = _number((getattr(final_state, "returns", None) or {}).get(agent_id))
    return score


def game_outcome(final_state, agent_id: str) -> str | None:

    result = getattr(final_state, "final_result", None) or {}
    structured = result.get("result")
    players = structured.get("seats") if isinstance(structured, dict) else None
    mine = players.get(agent_id) if isinstance(players, dict) else None
    if isinstance(mine, dict) and mine.get("outcome") in _OUTCOME_WORDS:
        return _OUTCOME_WORDS[mine["outcome"]]
    if result.get("status") == "failed" or result.get("failure_reason"):
        return "no result"
    winner = result.get("winner_agent_id")
    if winner:
        return "won" if winner == agent_id else "lost"
    score = _score(final_state, agent_id)
    if score is None:
        return None
    return "won" if score > 0.5 else "lost" if score < 0.5 else "drew"


def finished_line(final_state, agent_id: str, seat_position: int | None = None) -> str:

    score = _score(final_state, agent_id)
    detail = f"termination_reason={getattr(final_state, 'termination_reason', None)}" + (
        f", score={score}" if score is not None else "")
    outcome = game_outcome(final_state, agent_id)
    if outcome is None:
        return f"finished ({detail})"
    if outcome == "no result":
        return f"finished with no result ({detail})"
    player = f" (player {seat_position + 1})" if isinstance(seat_position, int) else ""
    return f"finished: your agent{player} {outcome} ({detail})"


class TournamentWorkerInput(NamedTuple):


    seat_id: str
    match_id: str
    game_type: str | None
    agent_spec: str
    execution_id: str
    tournament_id: str | None = None
    agent_session: str | None = None

    def __repr__(self) -> str:
        return (
            f"TournamentWorkerInput(seat_id={self.seat_id!r}, match_id={self.match_id!r}, "
            f"game_type={self.game_type!r}, agent_spec={self.agent_spec!r}, "
            f"tournament_id={self.tournament_id!r})"
        )


def run_tournament_worker(
    worker_input: TournamentWorkerInput,
    *,
    official_factory: Callable[[], "OfficialAgentClient"] | None = None,
    run_game_fn: Callable[..., "GameState"] | None = None,
    lease_renew_seconds: float | None = None,
    lease_retry_seconds: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> int:

    from .agent_loader import load_agent_factory
    from .models import DecisionContext
    from .official import (
        LEASE_RENEW_SECONDS,
        LEASE_RETRY_SECONDS,
        OfficialAgentClient,
        OfficialAgentError,
        OfficialSeatAuth,
        SeatLeaseKeeper,
        SeatLeaseLost,
        is_fatal_auth_error,
        is_registration_incomplete,
        registration_wait_message,
    )
    from .runner import _resolve_decision_fn, run_game

    pid = os.getpid()
    label = f"[match {worker_input.game_type or 'unknown'} seat={worker_input.seat_id}]"
    official_factory = official_factory or OfficialAgentClient
    run_game_fn = run_game_fn or partial(run_game, log=lambda message: print_line(f"{label} {message}"))
    print_line(f"{label} starting (pid={pid})")

    official = None
    game_client = None
    keeper = None
    game = None
    try:
        contestant = load_agent_factory(worker_input.agent_spec)()
        _resolve_decision_fn(contestant)

        official = official_factory()
        adopt = getattr(official, "use_session_token", None)
        if worker_input.agent_session and callable(adopt):
            adopt(worker_input.agent_session)
        seat_auth = OfficialSeatAuth(official, worker_input.seat_id, worker_input.execution_id)
        game_client = AltruAgentClient(control_url=official.control_url, auth=seat_auth, load_env_file=False)
        give_up_at = now() + FIRST_GRANT_RETRY_SECONDS
        attempt = 0
        while True:
            try:
                game_client.login()
                break
            except (PlatformError, AuthenticationError) as exc:
                code = exc.error_code if isinstance(exc, OfficialAgentError) else None
                if code == "assignment_not_grantable":
                    print_line(f"{label} assignment already ended; nothing to play")
                    return EXIT_SUCCESS
                if code == "seat_busy":
                    print_line(f"{label} seat is held by another runtime; not playing it")
                    return EXIT_SEAT_BUSY
                if not is_transient_error(exc) or now() >= give_up_at:
                    raise
                error = exc
            if attempt == 0:
                print_line(f"{label} couldn't get into the game yet ({error}); trying again for up to "
                      f"{FIRST_GRANT_RETRY_SECONDS:.0f}s")
            delay = min(FIRST_GRANT_RETRY_MAX_SECONDS, FIRST_GRANT_RETRY_FIRST_SECONDS * 2 ** attempt)
            attempt += 1
            sleep(delay * random.uniform(0.75, 1.25))
        grant = seat_auth.grant

        keeper = SeatLeaseKeeper(
            official,
            worker_input.seat_id,
            worker_input.execution_id,
            renew_seconds=lease_renew_seconds or LEASE_RENEW_SECONDS,
            retry_seconds=lease_retry_seconds or LEASE_RETRY_SECONDS,
            log=lambda message: print_line(f"{label} {message}"),
        )
        keeper.start()
        game = _LeaseGuardedGameSession(
            game_client, lost=keeper.lost, session_id=grant.game_session_id, game_server_url=grant.gameapi_server_url
        )
        context = DecisionContext(
            session_id=grant.game_session_id,
            tournament_id=worker_input.tournament_id,
            game_type=grant.game_type,
            agent_id=grant.agent_id,
            seat_position=grant.seat_position,
        )
        final_state = run_game_fn(game, context, contestant)
        print_line(f"{label} {finished_line(final_state, grant.agent_id, grant.seat_position)}")
        return EXIT_SUCCESS
    except KeyboardInterrupt:
        print_line(f"{label} interrupted, stopping")
        return EXIT_SUCCESS
    except SeatLeaseLost:
        print_line(f"{label} stopped: another runtime now holds this seat")
        return EXIT_SEAT_BUSY
    except Exception as exc:
        code = exc.error_code if isinstance(exc, (PlatformError, AuthenticationError)) else None
        if (keeper is not None and keeper.lost.is_set()) or (isinstance(exc, OfficialAgentError) and code == "seat_busy"):
            print_line(f"{label} stopped: another runtime now holds this seat")
            return EXIT_SEAT_BUSY
        if isinstance(exc, OfficialAgentError) and code == "assignment_not_grantable":
            print_line(f"{label} the game has ended; nothing more to play")
            return EXIT_SUCCESS
        if is_registration_incomplete(exc):
            print_line(f"{label} {registration_wait_message(exc)}")
            return EXIT_REGISTRATION_INCOMPLETE
        if is_fatal_auth_error(exc):
            print_line(f"{label} {exc}")
            return EXIT_KEY_REFUSED
        if _is_transient(exc):
            if not getattr(game, "contacted", False):
                print_line(f"{label} couldn't reach the game because of a temporary problem ({exc}); trying again shortly")
                return EXIT_NOT_CONNECTED
            print_line(f"{label} lost the connection to the game ({exc}); reconnecting shortly")
            return EXIT_CONNECTION_LOST
        if isinstance(exc, _MATCH_SCOPED_ERRORS):
            print_line(f"{label} match failed: {exc}")
            return EXIT_MATCH_FAILURE
        print_line(f"{label} unexpected error: {exc!r}")
        return EXIT_UNEXPECTED
    finally:
        if keeper is not None:
            keeper.stop()
        for client in (game_client, official):
            if client is not None:
                client.close()


class _LeaseGuardedGameSession(MCPGameSession):


    def __init__(self, client, *, lost, **kwargs) -> None:
        super().__init__(client, **kwargs)
        self._lost = lost
        self.contacted = False

    def _call(self, tool: str, arguments: dict) -> dict:
        if self._lost.is_set():
            from .official import SeatLeaseLost

            raise SeatLeaseLost("Another runtime now holds this seat's execution lease.")
        answer = super()._call(tool, arguments)
        self.contacted = True
        return answer


def _tournament_process_entry(worker_input: TournamentWorkerInput) -> None:

    raise SystemExit(run_tournament_worker(worker_input))


def _process_entry(worker_input: WorkerInput) -> None:

    raise SystemExit(run_worker(worker_input))
