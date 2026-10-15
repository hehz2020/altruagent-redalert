from __future__ import annotations

import multiprocessing
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Collection

from .console import print_line
from .errors import AuthenticationError, PlatformError
from .official import is_fatal_auth_error, is_registration_incomplete, new_execution_id, registration_wait_message
from .runner import TRANSIENT_GIVE_UP_SECONDS
from .worker import (
    EXIT_CONNECTION_LOST,
    EXIT_KEY_REFUSED,
    EXIT_NOT_CONNECTED,
    EXIT_REGISTRATION_INCOMPLETE,
    EXIT_SEAT_BUSY,
    EXIT_SUCCESS,
    TournamentWorkerInput,
    WorkerInput,
    _process_entry,
    _tournament_process_entry,
)

if TYPE_CHECKING:
    from .client import AltruAgentClient
    from .models import OfficialAssignment
    from .official import OfficialAgentClient

DEFAULT_DISCOVERY_INTERVAL_SECONDS = 15.0
DEFAULT_COOLDOWN_SECONDS = 60.0
DEFAULT_SHUTDOWN_JOIN_TIMEOUT_SECONDS = 5.0

_MP_CONTEXT = multiprocessing.get_context("spawn")


def _log(message: str) -> None:
    print(f"[agent] {message}")


class WorkerRegistry:


    def __init__(self) -> None:
        self._processes: dict[str, "multiprocessing.process.BaseProcess"] = {}

    def is_active(self, session_id: str) -> bool:
        return session_id in self._processes

    def pids(self) -> dict[str, int]:

        return {session_id: process.pid for session_id, process in self._processes.items()}

    def start(self, session_id: str, process: "multiprocessing.process.BaseProcess") -> None:
        self._processes[session_id] = process

    def reap_finished(self) -> dict[str, int]:

        finished: dict[str, int] = {}
        for session_id, process in list(self._processes.items()):
            if not process.is_alive():
                process.join()
                finished[session_id] = process.exitcode
                del self._processes[session_id]
        return finished

    def terminate(self, session_id: str, timeout: float) -> None:

        process = self._processes.pop(session_id, None)
        if process is None:
            return
        if process.is_alive():
            process.terminate()
        process.join(timeout)

    def keys(self) -> list[str]:
        return list(self._processes)

    def terminate_all(self, timeout: float) -> None:

        for process in self._processes.values():
            if process.is_alive():
                process.terminate()
        for process in self._processes.values():
            process.join(timeout)
        self._processes.clear()

    def __len__(self) -> int:
        return len(self._processes)


def run_once_concurrent(
    client: "AltruAgentClient",
    *,
    registry: WorkerRegistry,
    failed_until: dict,
    agent_id: str,
    now: Callable[[], float] = time.monotonic,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    process_factory: Callable[..., "multiprocessing.process.BaseProcess"] = _MP_CONTEXT.Process,
) -> None:

    current_time = now()

    for session_id, exitcode in registry.reap_finished().items():
        if exitcode != EXIT_SUCCESS:
            failed_until[session_id] = current_time + cooldown_seconds
            _log(
                f"worker for session_id={session_id} exited with code {exitcode} — "
                f"cooling down for {cooldown_seconds:.0f}s"
            )
        else:
            failed_until.pop(session_id, None)
            _log(f"worker for session_id={session_id} finished")

    sessions = client.sessions()
    for match in sessions.active:
        if registry.is_active(match.session_id):
            continue
        retry_at = failed_until.get(match.session_id)
        if retry_at is not None and current_time < retry_at:
            continue

        worker_input = WorkerInput(
            session_id=match.session_id,
            tournament_id=match.tournament_id,
            game_type=match.game_type,
            agent_id=agent_id,
        )
        process = process_factory(target=_process_entry, args=(worker_input,), daemon=True)
        process.start()
        registry.start(match.session_id, process)
        _log(
            f"started worker pid={process.pid} for session_id={match.session_id} "
            f"game_type={match.game_type} tournament_id={match.tournament_id}"
        )


def run_forever_concurrent(
    client: "AltruAgentClient",
    *,
    agent_id: str,
    discovery_interval: float = DEFAULT_DISCOVERY_INTERVAL_SECONDS,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    shutdown_join_timeout: float = DEFAULT_SHUTDOWN_JOIN_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    process_factory: Callable[..., "multiprocessing.process.BaseProcess"] = _MP_CONTEXT.Process,
    max_iterations: int | None = None,
) -> None:

    registry = WorkerRegistry()
    failed_until: dict = {}
    ticks = 0
    try:
        while max_iterations is None or ticks < max_iterations:
            run_once_concurrent(
                client,
                registry=registry,
                failed_until=failed_until,
                agent_id=agent_id,
                now=now,
                cooldown_seconds=cooldown_seconds,
                process_factory=process_factory,
            )
            ticks += 1
            sleep(discovery_interval)
    finally:
        if len(registry) > 0:
            _log(f"stopping {len(registry)} active worker(s)...")
            registry.terminate_all(shutdown_join_timeout)



DEFAULT_TOURNAMENT_POLL_SECONDS = 10.0
MISSING_POLLS_BEFORE_STOP = 2
WAITING_MESSAGE = "Waiting for your next game..."
KEY_REFUSED_MESSAGE = (
    "Your Official Agent Key is no longer accepted, so no new game will start. Put your new key in .env "
    "(ALTRUAGENT_OFFICIAL_AGENT_KEY) and restart this process; check too that your agent is still Self-hosted. "
    "Games already running keep playing for now."
)
SEAT_BUSY_RETRY_SECONDS = 35.0
SEAT_FAILURE_BACKOFF_MAX_SECONDS = 600.0
WORKER_PLAYED_SECONDS = 30.0
RESTART_AFTER_PLAY_SECONDS = 10.0
NOT_CONNECTED_RETRY_SECONDS = 0.0
MIN_CONNECT_WINDOW_SECONDS = 300.0
REGISTRATION_RETRY_SECONDS = 30.0
REGISTRATION_REMINDER_SECONDS = 300.0
AUTH_RETRY_BASE_SECONDS = 10.0
AUTH_RETRY_MAX_SECONDS = 60.0
AUTH_RATE_LIMIT_WAIT_SECONDS = 60.0


TESTING = "testing"
TOURNAMENT = "tournament"
ALL_KINDS = frozenset({TESTING, TOURNAMENT})
TEST_MATCH_WAITING_NOTE = "Test match waiting: run with --match to play it"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_MAX_TEXT = 80


def _clean(text: str | None) -> str:
    cleaned = "".join(ch for ch in (text or "") if ch.isprintable()).strip()
    return cleaned if len(cleaned) <= _MAX_TEXT else cleaned[: _MAX_TEXT - 3].rstrip() + "..."


def _parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_wait(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _kind_label(assignment: "OfficialAssignment") -> str:
    context = (assignment.context or "").strip().lower()
    return {"testing": " (Testing)", "tournament": " (tournament)"}.get(context, "")


def _players_note(players: int, player_count: int | None) -> str:

    if players <= 1:
        return ""
    if player_count == players:
        return f", self-play: your agent plays all {players} players"
    if isinstance(player_count, int) and player_count > players:
        return f", your agent plays {players} of the {player_count} players"
    return f", your agent plays {players} players"


def describe_assignment(assignment: "OfficialAssignment", *, now: datetime | None = None,
                        players: int = 1) -> list[str]:

    game = _clean(assignment.game_type) or "unknown game"
    lines = [f"Match assigned: {game}{_kind_label(assignment)}{_players_note(players, assignment.seat_count)}"]

    name, round_label = _clean(assignment.tournament_name), _clean(assignment.round_label)
    if name and round_label:
        lines.append(f"  Tournament: {name}, {round_label}")
    elif name:
        lines.append(f"  Tournament: {name}")
    elif round_label:
        lines.append(f"  Round: {round_label}")

    opponents = [cleaned for cleaned in (_clean(o) for o in assignment.opponents) if cleaned]
    if opponents:
        lines.append(f"  Opponents: {', '.join(opponents)}")

    if assignment.connect_deadline_at:
        deadline = _parse_utc(assignment.connect_deadline_at)
        if deadline is None:
            lines.append(f"  Connect by: {_clean(assignment.connect_deadline_at)}")
        else:
            at = deadline.strftime("%Y-%m-%d %H:%M:%S UTC")
            left = (deadline - (now or _utc_now())).total_seconds()
            when = f"{_format_wait(left)} left" if left > 0 else "deadline passed"
            lines.append(f"  Connect by: {at} ({when})")
    return lines


def assignment_kind(assignment: "OfficialAssignment") -> str:

    context = (assignment.context or "").strip().lower()
    return TESTING if context == TESTING else TOURNAMENT


def tournament_waiting_warning(assignment: "OfficialAssignment") -> str:

    name, round_label = _clean(assignment.tournament_name), _clean(assignment.round_label)
    where = ", ".join(part for part in (name, round_label) if part) or _clean(assignment.game_type)
    detail = f" ({where})" if where else ""
    return (
        f"You have a tournament game waiting{detail}: run with --tournament to play it — "
        "it counts as a loss if your agent doesn't connect within the window."
    )


class TournamentState:


    def __init__(self) -> None:
        self.execution_id = new_execution_id()
        self.registry = WorkerRegistry()
        self.failed_until: dict[str, float] = {}
        self.seat_failures: dict[str, int] = {}
        self.started_at: dict[str, float] = {}
        self.connect_by: dict[str, tuple[tuple[str, str | None], float]] = {}
        self.registration_noted_at: float | None = None
        self.missing_polls: dict[str, int] = {}
        self.discovery_failing = False
        self.noted_games: set[str] = set()
        self.auth_failures = 0
        self.discovery_retry_at: float | None = None
        self.seat_games: dict[str, "OfficialAssignment"] = {}
        self.stopped: dict[str, "OfficialAssignment"] = {}
        self.key_refused = False


def _auth_retry_delay(exc: AuthenticationError, failures: int) -> float:
    if exc.status_code == 429:
        return AUTH_RATE_LIMIT_WAIT_SECONDS
    return min(AUTH_RETRY_MAX_SECONDS, AUTH_RETRY_BASE_SECONDS * 2 ** failures)


def _connect_by(assignment: "OfficialAssignment", current_time: float, wall: datetime) -> float:

    deadline = _parse_utc(assignment.connect_deadline_at) if assignment.connect_deadline_at else None
    left = (deadline - wall).total_seconds() if deadline is not None else 0.0
    return current_time + max(MIN_CONNECT_WINDOW_SECONDS, left)


def _note_registration(state: TournamentState, current_time: float, message: str, log: Callable[[str], None]) -> None:
    if state.registration_noted_at is None or current_time - state.registration_noted_at >= REGISTRATION_REMINDER_SECONDS:
        state.registration_noted_at = current_time
        log(message)


def _note_other_kind(assignment: "OfficialAssignment", state: TournamentState, log: Callable[[str], None]) -> None:

    game = assignment.match_id or assignment.seat_id
    if game in state.noted_games:
        return
    state.noted_games.add(game)
    if assignment_kind(assignment) == TOURNAMENT:
        log(tournament_waiting_warning(assignment))
    else:
        log(TEST_MATCH_WAITING_NOTE)


def run_tournament_once(
    official: "OfficialAgentClient",
    state: TournamentState,
    *,
    agent_spec: str,
    kinds: Collection[str] = ALL_KINDS,
    now: Callable[[], float] = time.monotonic,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    shutdown_join_timeout: float = DEFAULT_SHUTDOWN_JOIN_TIMEOUT_SECONDS,
    process_factory: Callable[..., "multiprocessing.process.BaseProcess"] = _MP_CONTEXT.Process,
    log: Callable[[str], None] = print_line,
    wall_now: Callable[[], datetime] = _utc_now,
) -> None:

    current_time = now()
    said: set[tuple[str, str]] = set()

    def match_of(seat_id: str) -> str:
        assignment = state.seat_games.get(seat_id)
        return (assignment.match_id if assignment is not None else "") or seat_id

    def say(seat_id: str, line: str) -> None:
        if (match_of(seat_id), line) not in said:
            said.add((match_of(seat_id), line))
            log(line)

    def say_waiting() -> None:
        if ("", WAITING_MESSAGE) not in said and not state.key_refused:
            said.add(("", WAITING_MESSAGE))
            log(WAITING_MESSAGE)

    reaped = state.registry.reap_finished()
    finished: list[str] = []
    idle = False
    for seat_id, exitcode in reaped.items():
        state.missing_polls.pop(seat_id, None)
        started = state.started_at.pop(seat_id, None)
        ran = current_time - started if started is not None else 0.0
        state.failed_until[seat_id] = current_time + cooldown_seconds
        connect_by = state.connect_by[seat_id][1] if seat_id in state.connect_by else None
        if exitcode not in (EXIT_SUCCESS, EXIT_SEAT_BUSY) and seat_id in state.seat_games:
            state.stopped[seat_id] = state.seat_games[seat_id]
        if exitcode == EXIT_SUCCESS:
            state.seat_failures.pop(seat_id, None)
            if match_of(seat_id) not in finished:
                finished.append(match_of(seat_id))
            idle = True
        elif exitcode == EXIT_SEAT_BUSY:
            state.seat_failures.pop(seat_id, None)
            state.failed_until[seat_id] = current_time + SEAT_BUSY_RETRY_SECONDS
            say(seat_id, f"Another runtime is playing this match with your Official Agent Key; checking again in "
                         f"{SEAT_BUSY_RETRY_SECONDS:.0f}s.")
            idle = True
        elif exitcode == EXIT_KEY_REFUSED:
            if not state.key_refused:
                state.key_refused = True
                log(KEY_REFUSED_MESSAGE)
        elif exitcode == EXIT_REGISTRATION_INCOMPLETE:
            state.failed_until[seat_id] = current_time + REGISTRATION_RETRY_SECONDS
            say(seat_id, f"That game can't start until your registration is complete; checking again in "
                         f"{REGISTRATION_RETRY_SECONDS:.0f}s.")
            idle = True
        elif exitcode == EXIT_NOT_CONNECTED and connect_by is not None and current_time < connect_by:
            state.failed_until[seat_id] = current_time + NOT_CONNECTED_RETRY_SECONDS
            say(seat_id, "Couldn't reach that game yet (a temporary problem); trying again now.")
        else:
            if exitcode == EXIT_CONNECTION_LOST and ran >= TRANSIENT_GIVE_UP_SECONDS + WORKER_PLAYED_SECONDS:
                failures = 1
                wait = RESTART_AFTER_PLAY_SECONDS
            else:
                long_run = exitcode != EXIT_NOT_CONNECTED and ran >= SEAT_FAILURE_BACKOFF_MAX_SECONDS
                failures = 1 if long_run else state.seat_failures.get(seat_id, 0) + 1
                wait = min(max(SEAT_FAILURE_BACKOFF_MAX_SECONDS, cooldown_seconds), cooldown_seconds * 2 ** (failures - 1))
            state.seat_failures[seat_id] = failures
            state.failed_until[seat_id] = current_time + wait
            if exitcode == EXIT_CONNECTION_LOST:
                say(seat_id, f"Lost the connection to that game for a while; retrying that game in {wait:.0f}s "
                             "if it is still assigned.")
            elif exitcode == EXIT_NOT_CONNECTED:
                say(seat_id, f"Couldn't reach that game (a temporary problem); retrying in {wait:.0f}s "
                             "if it is still assigned.")
            else:
                say(seat_id, f"Your agent's process for this match stopped with an error (exit code {exitcode}); "
                             f"the match continues. Retrying in {wait:.0f}s if it is still assigned.")
    active_matches = {match_of(seat_id) for seat_id in state.registry.keys()}
    for match in finished:
        for seat_id in [s for s in state.stopped if match_of(s) == match]:
            del state.stopped[seat_id]
        if match not in active_matches:
            log("Match finished.")
    if reaped and idle and len(state.registry) == 0:
        say_waiting()

    if state.discovery_retry_at is not None and current_time < state.discovery_retry_at:
        return
    try:
        assignments = official.assignments()
    except PlatformError as exc:
        if not state.discovery_failing:
            log(f"Could not check tournament assignments ({exc}); will keep retrying.")
        state.discovery_failing = True
        return
    except AuthenticationError as exc:
        if is_registration_incomplete(exc):
            _note_registration(state, current_time, registration_wait_message(exc), log)
            state.discovery_retry_at = current_time + REGISTRATION_RETRY_SECONDS
            state.discovery_failing = True
            return
        if is_fatal_auth_error(exc):
            raise
        delay = _auth_retry_delay(exc, state.auth_failures)
        state.auth_failures += 1
        state.discovery_retry_at = current_time + delay
        if not state.discovery_failing:
            log(f"Could not renew your agent session ({exc}). Games already running keep playing; "
                "retrying automatically.")
        state.discovery_failing = True
        return
    state.auth_failures = 0
    state.discovery_retry_at = None
    if state.discovery_failing:
        log("Assignment discovery recovered.")
        state.discovery_failing = False

    listed = {assignment.seat_id for assignment in assignments}
    for seat_id in [s for s in state.seat_failures if s not in listed and not state.registry.is_active(s)]:
        del state.seat_failures[seat_id]
    for seat_id in [s for s in state.connect_by if s not in listed and not state.registry.is_active(s)]:
        del state.connect_by[seat_id]
    ended = [s for s in state.stopped if s not in listed and not state.registry.is_active(s)]
    for seat_id in ended:
        assignment = state.stopped.pop(seat_id)
        game = _clean(assignment.game_type)
        say(seat_id, f"Your {game + ' ' if game else ''}match{_kind_label(assignment)} has ended while your "
                     "agent's process for it was stopped.")
    if ended and len(state.registry) == 0:
        say_waiting()
    for seat_id in [s for s in state.seat_games if s not in listed and not state.registry.is_active(s)]:
        del state.seat_games[seat_id]

    to_start: dict[str, list["OfficialAssignment"]] = {}
    for assignment in [] if state.key_refused else assignments:
        seat_id = assignment.seat_id
        if not seat_id or state.registry.is_active(seat_id):
            continue
        if assignment_kind(assignment) not in kinds:
            _note_other_kind(assignment, state, log)
            continue
        window = (assignment.match_id, assignment.connect_deadline_at)
        if state.connect_by.get(seat_id, (None, 0.0))[0] != window:
            state.connect_by[seat_id] = (window, _connect_by(assignment, current_time, wall_now()))
        retry_at = state.failed_until.get(seat_id)
        if retry_at is not None and current_time < retry_at:
            continue
        to_start.setdefault(assignment.match_id or seat_id, []).append(assignment)
    session_token = getattr(official, "session_token", None)
    for group in to_start.values():
        for assignment in group:
            seat_id = assignment.seat_id
            worker_input = TournamentWorkerInput(
                seat_id=seat_id, match_id=assignment.match_id, game_type=assignment.game_type,
                agent_spec=agent_spec, execution_id=state.execution_id,
                tournament_id=assignment.tournament_id,
                agent_session=session_token() if callable(session_token) else None,
            )
            process = process_factory(target=_tournament_process_entry, args=(worker_input,), daemon=True)
            process.start()
            state.registry.start(seat_id, process)
            state.started_at[seat_id] = current_time
            state.seat_games[seat_id] = assignment
            state.stopped.pop(seat_id, None)
        for line in describe_assignment(group[0], now=wall_now(), players=len(group)):
            log(line)
        log("Starting match...")

    for seat_id in state.registry.keys():
        if seat_id in listed:
            state.missing_polls.pop(seat_id, None)
            continue
        state.missing_polls[seat_id] = state.missing_polls.get(seat_id, 0) + 1
        if state.missing_polls[seat_id] >= MISSING_POLLS_BEFORE_STOP:
            say(seat_id, "Match is no longer assigned; stopped its worker.")
            state.registry.terminate(seat_id, shutdown_join_timeout)
            state.missing_polls.pop(seat_id, None)
            state.started_at.pop(seat_id, None)
            state.seat_games.pop(seat_id, None)
            if len(state.registry) == 0:
                say_waiting()


def run_tournament_forever(
    official: "OfficialAgentClient",
    *,
    agent_spec: str,
    kinds: Collection[str] = ALL_KINDS,
    poll_interval: float = DEFAULT_TOURNAMENT_POLL_SECONDS,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    shutdown_join_timeout: float = DEFAULT_SHUTDOWN_JOIN_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    process_factory: Callable[..., "multiprocessing.process.BaseProcess"] = _MP_CONTEXT.Process,
    log: Callable[[str], None] = print_line,
    max_iterations: int | None = None,
) -> None:

    state = TournamentState()
    ticks = 0
    try:
        while max_iterations is None or ticks < max_iterations:
            run_tournament_once(
                official, state, agent_spec=agent_spec, kinds=kinds, now=now, cooldown_seconds=cooldown_seconds,
                shutdown_join_timeout=shutdown_join_timeout, process_factory=process_factory, log=log,
            )
            ticks += 1
            sleep(poll_interval)
    finally:
        if len(state.registry) > 0:
            log(f"Stopping {len(state.registry)} active match worker(s)...")
            state.registry.terminate_all(shutdown_join_timeout)
