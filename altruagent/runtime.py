from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable

from .errors import PlatformError
from .runner import DecisionError, UnsupportedGameFlowError
from .runner import run_match as _default_run_match

if TYPE_CHECKING:
    from .client import AltruAgentClient
    from .models import GameState

DEFAULT_DISCOVERY_INTERVAL_SECONDS = 15.0
DEFAULT_COOLDOWN_SECONDS = 60.0

_MATCH_SCOPED_ERRORS = (DecisionError, UnsupportedGameFlowError, PlatformError)


def _log(message: str) -> None:
    print(f"[agent] {message}")


def run_once(
    client: "AltruAgentClient",
    choose_action,
    *,
    agent_id: str,
    failed_until: dict,
    now: Callable[[], float] = time.monotonic,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    run_match_fn: Callable[..., "GameState"] = _default_run_match,
) -> bool:

    sessions = client.sessions()
    current_time = now()

    match = None
    for candidate in sessions.active:
        retry_at = failed_until.get(candidate.session_id)
        if retry_at is not None and current_time < retry_at:
            continue
        match = candidate
        break

    if match is None:
        return False

    _log(
        f"starting match session_id={match.session_id} game_type={match.game_type} "
        f"tournament_id={match.tournament_id}"
    )
    try:
        final_state = run_match_fn(match, agent_id, choose_action)
    except _MATCH_SCOPED_ERRORS as exc:
        failed_until[match.session_id] = current_time + cooldown_seconds
        _log(
            f"match failed, skipping session_id={match.session_id} for "
            f"{cooldown_seconds:.0f}s: {exc}"
        )
        return True

    failed_until.pop(match.session_id, None)
    _log(
        f"match finished session_id={match.session_id} "
        f"termination_reason={final_state.termination_reason}"
    )
    return True


def run_forever(
    client: "AltruAgentClient",
    choose_action,
    *,
    agent_id: str,
    discovery_interval: float = DEFAULT_DISCOVERY_INTERVAL_SECONDS,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    run_match_fn: Callable[..., "GameState"] = _default_run_match,
    max_iterations: int | None = None,
) -> None:

    failed_until: dict = {}
    ticks = 0
    while max_iterations is None or ticks < max_iterations:
        serviced = run_once(
            client,
            choose_action,
            agent_id=agent_id,
            failed_until=failed_until,
            now=now,
            cooldown_seconds=cooldown_seconds,
            run_match_fn=run_match_fn,
        )
        ticks += 1
        if not serviced:
            _log(f"no active matches — checking again in {discovery_interval:.0f}s")
            sleep(discovery_interval)
