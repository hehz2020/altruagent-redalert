from __future__ import annotations

import argparse
import getpass
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from altruagent.client import AltruAgentClient
from altruagent.errors import AltruAgentError, ConfigurationError
from altruagent.runner import RESIGN
from altruagent.runtime import run_once

from _agent_file_swap import AgentFileSwapError, temporary_agent

COMPETITION_GAME_TYPE = "tic_tac_toe"
DEFAULT_POLL_TIMEOUT_SECONDS = 60.0
DEFAULT_POLL_INTERVAL_SECONDS = 3.0
HTTP_TIMEOUT_SECONDS = 10.0


class SmokeTestError(RuntimeError):
    pass


def _checkpoint(label: str) -> None:
    print(f"[OK] {label}")


def _fail(message: str) -> None:
    raise SmokeTestError(message)


def _json_or_fail(response: httpx.Response, what: str) -> dict:
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.status_code >= 400:
        detail = None
        if isinstance(body, dict):
            detail = body.get("detail") or body.get("error")
        detail = detail or (response.text[:300] if response.text else None)
        _fail(f"{what} failed (HTTP {response.status_code}): {detail}")
    if not isinstance(body, dict):
        _fail(f"{what} returned a non-JSON or unexpected response body.")
    return body


def signup_temporary_agent(http: httpx.Client, control_url: str) -> tuple[str, str, str]:

    name = f"smoke-test-{uuid.uuid4().hex[:10]}"
    response = http.post(
        f"{control_url}/auth/agent/signup",
        json={"name": name, "description": "Milestone 2 smoke-test opponent (safe to ignore/delete)"},
    )
    body = _json_or_fail(response, "temporary agent signup")
    api_key = body.get("api_key")
    claim_token = body.get("claim_token")
    if not api_key or not claim_token:
        _fail("Signup response did not include both api_key and claim_token.")
    return name, api_key, claim_token


def claim_temporary_agent(
    http: httpx.Client, control_url: str, claim_token: str, human_token: str
) -> None:

    response = http.post(
        f"{control_url}/auth/human/claim",
        json={"claim_token": claim_token},
        headers={"Authorization": f"Bearer {human_token}"},
    )
    _json_or_fail(response, "claiming the temporary agent")


def create_competition(http: httpx.Client, control_url: str, human_token: str) -> str:

    response = http.post(
        f"{control_url}/admin/competitions/create",
        json={"game_type": COMPETITION_GAME_TYPE, "max_participants": 2},
        headers={"Authorization": f"Bearer {human_token}"},
    )
    body = _json_or_fail(response, "competition creation")
    session_id = body.get("session_id")
    if not session_id:
        _fail("Competition creation response did not include session_id.")
    return session_id


def join_competition(client: AltruAgentClient, session_id: str) -> None:

    client.request("POST", f"/competitions/{session_id}/join")


def create_tournament(http: httpx.Client, control_url: str, human_token: str) -> str:

    response = http.post(
        f"{control_url}/admin/tournaments/create",
        json={"game_type": COMPETITION_GAME_TYPE, "max_participants": 2},
        headers={"Authorization": f"Bearer {human_token}"},
    )
    body = _json_or_fail(response, "tournament creation")
    tournament_id = body.get("tournament_id")
    if not tournament_id:
        _fail("Tournament creation response did not include tournament_id.")
    return tournament_id


def _poll_until(
    poll: Callable[[], dict],
    is_ready: Callable[[dict], bool],
    *,
    timeout_seconds: float,
    interval_seconds: float,
    sleep: Callable[[float], None],
    now: Callable[[], float],
    timeout_message: Callable[[dict], str],
) -> dict:

    deadline = now() + timeout_seconds
    last = poll()
    while True:
        if is_ready(last):
            return last
        if now() >= deadline:
            _fail(timeout_message(last))
        sleep(interval_seconds)
        last = poll()


def wait_for_in_progress(
    poll: Callable[[], dict],
    *,
    timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
    interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> dict:

    return _poll_until(
        poll,
        lambda last: last.get("status") == "in_progress" and bool(last.get("game_server_url")),
        timeout_seconds=timeout_seconds,
        interval_seconds=interval_seconds,
        sleep=sleep,
        now=now,
        timeout_message=lambda last: (
            "Competition did not reach in_progress with a game_server_url "
            f"within {timeout_seconds:.0f}s (last status: {last.get('status')!r})."
        ),
    )


def wait_for_tournament_in_progress(
    poll: Callable[[], dict],
    *,
    timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
    interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> dict:

    return _poll_until(
        poll,
        lambda last: last.get("status") == "in_progress",
        timeout_seconds=timeout_seconds,
        interval_seconds=interval_seconds,
        sleep=sleep,
        now=now,
        timeout_message=lambda last: (
            f"Tournament did not reach in_progress within {timeout_seconds:.0f}s "
            f"(last status: {last.get('status')!r})."
        ),
    )


_DETERMINISTIC_RESIGN_AGENT_SOURCE = '''"""TEMPORARY FILE — written by scripts/smoke_game.py --concurrent for the
duration of the Milestone 4C concurrency check, and restored automatically
when it finishes. If you are reading this and did not just run that check,
something went wrong: restore agent/agent.py.smoke_test_backup over this
file (scripts/smoke_game.py --concurrent also does this automatically the
next time it runs, before doing anything else).
"""

from altruagent import RESIGN


def create_agent():
    return lambda state, context: RESIGN
'''


WORKER_COMPLETION_TIMEOUT_SECONDS = 30.0
WORKER_REAP_POLL_INTERVAL_SECONDS = 1.0


def run_concurrent_check(primary: AltruAgentClient, http: httpx.Client, control_url: str) -> int:

    from altruagent.supervisor import WorkerRegistry, run_once_concurrent

    opponent: AltruAgentClient | None = None
    registry: WorkerRegistry | None = None
    try:
        primary_agent = primary.me()
        if not primary_agent.is_claimed:
            _fail(
                f"Primary agent '{primary_agent.name}' is not claimed "
                f"(status={primary_agent.status}). Claim it before running this test."
            )
        _checkpoint(f"primary agent authenticated ({primary_agent.name})")

        opp_name, opp_api_key, opp_claim_token = signup_temporary_agent(http, control_url)
        human_token = getpass.getpass(
            "Human/admin bearer token (used only for this run — never stored, "
            "logged, or echoed): "
        )
        if not human_token:
            _fail("A human/admin bearer token is required to claim the temporary agent.")

        claim_temporary_agent(http, control_url, opp_claim_token, human_token)
        opponent = AltruAgentClient(control_url=control_url, api_key=opp_api_key)
        opponent_agent = opponent.me()
        if not opponent_agent.is_claimed:
            _fail(f"Temporary agent '{opp_name}' was not claimed successfully.")
        _checkpoint(f"temporary opponent created and claimed ({opp_name})")

        session_ids: list[str] = []
        for i in range(2):
            session_id = create_competition(http, control_url, human_token)
            join_competition(primary, session_id)
            join_competition(opponent, session_id)
            wait_for_in_progress(
                lambda sid=session_id: primary.request("GET", f"/competitions/{sid}")
            )
            session_ids.append(session_id)
            _checkpoint(f"competition {i + 1}/2 created and active (session_id={session_id})")

        sessions = primary.sessions()
        matches_by_id = {m.session_id: m for m in sessions.active if m.session_id in session_ids}
        if set(matches_by_id) != set(session_ids):
            _fail(
                f"Expected both {session_ids} in client.sessions().active, found "
                f"{sorted(m.session_id for m in sessions.active)}."
            )
        _checkpoint("both matches confirmed simultaneously active via client.sessions()")

        game_sessions_by_id = {sid: matches_by_id[sid].rest_game() for sid in session_ids}
        _checkpoint("game_server_url resolved for both matches ahead of time")

        registry = WorkerRegistry()
        try:
            with temporary_agent(_DETERMINISTIC_RESIGN_AGENT_SOURCE):
                _checkpoint(
                    "temporary deterministic-RESIGN agent/agent.py installed "
                    "(restored automatically at the end of this run)"
                )

                run_once_concurrent(
                    primary, registry=registry, failed_until={}, agent_id=primary_agent.id
                )
                pids = registry.pids()
                if set(pids) != set(session_ids):
                    _fail(f"Expected a worker for each of {session_ids}, got {pids}.")
                if len(set(pids.values())) != 2:
                    _fail(f"Expected two DISTINCT process PIDs, got {pids}.")
                _checkpoint(f"two distinct worker processes started concurrently (pids={pids})")

                deadline = time.monotonic() + WORKER_COMPLETION_TIMEOUT_SECONDS
                reaped: dict[str, int] = {}
                while len(reaped) < 2 and time.monotonic() < deadline:
                    reaped.update(registry.reap_finished())
                    if len(reaped) < 2:
                        time.sleep(WORKER_REAP_POLL_INTERVAL_SECONDS)

                if len(reaped) < 2:
                    _fail(
                        f"Only {len(reaped)}/2 workers exited naturally within "
                        f"{WORKER_COMPLETION_TIMEOUT_SECONDS:.0f}s (reaped so far: {reaped})."
                    )
                if any(exitcode != 0 for exitcode in reaped.values()):
                    _fail(f"One or more workers exited with a non-success code: {reaped}")
                _checkpoint(f"both workers exited naturally after resigning (exit codes={reaped})")

                if len(registry) != 0:
                    _fail(
                        "Expected the registry to be empty after reaping both workers, "
                        f"still tracking {len(registry)}."
                    )
                _checkpoint("supervisor registry confirms both workers reaped — none remaining")
        except AgentFileSwapError as exc:
            _fail(str(exc))
        _checkpoint("cleanup: real agent/agent.py restored")

        for session_id, game in game_sessions_by_id.items():
            final_state = game.state()
            if not final_state.is_terminal:
                _fail(
                    f"session_id={session_id} is not terminal after its worker "
                    f"exited (status={final_state.status!r})."
                )
        _checkpoint("both server-side matches confirmed terminal")

        print(
            f"\n[NOTE] Temporary agent '{opp_name}' remains claimed — the current "
            "backend has no safe agent-deletion endpoint, so it was not deleted."
        )
        print("\nMILESTONE 4C LIVE CONCURRENCY SMOKE TEST PASSED")
        return 0
    except (SmokeTestError, AltruAgentError) as exc:
        print(f"\nSMOKE TEST FAILED: {exc}")
        return 1
    finally:
        if registry is not None and len(registry) > 0:
            print(f"[WARN] cleanup: terminating {len(registry)} still-running worker(s)")
            registry.terminate_all(timeout=10.0)
        if opponent is not None:
            opponent.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Milestone 2 + 3A/3B/4A/4B/4C LIVE end-to-end smoke test — developer/manual tool only.\n\nRETIRED: this drives the platform-agent APIs (/auth/agent/*, /auth/human/claim,\n/competitions, /tournaments/{id}/join), which the platform turned off (HTTP\n410). It no longer runs against the deployed platform; it is kept for\nreference, and tests/test_smoke_game.py still covers its polling helpers.\n\nProves the starter SDK can play a real match against the REAL deployed\nAltruAgent platform (Agent_ACP), not a mock. This is not contestant-facing\nfunctionality — it's an integration check for people working on the SDK\nitself. It creates real, if disposable, platform state: one or two\ntemporary second agents and one or two temporary competitions/tournaments.\n\nMilestone 6 note: since `Match.game()` now builds an `MCPGameSession` (MCP\nis the production path — see `altruagent.runner`), this script's own direct\nstate-inspection calls use `match.rest_game()` instead, deliberately keeping\ntheir REST-shaped assertions (`next_actions`, `.state()`) exactly as\noriginally written. The actual play/resign these checks exercise still goes\nthrough the real production path (`run_once`/`run_once_concurrent`, which\ncall `run_match` -> `match.game()` -> MCP) regardless — so this script now\nincidentally proves REST and MCP reads agree on the same underlying session,\nin addition to its original purpose. `scripts/acceptance_test.py --mcp` is\nthe dedicated, purpose-built MCP proof (see its own docstring).\n\nThree modes. The default and `--tournament` share all of their setup/\ncleanup machinery; `--concurrent` (Milestone 4C) is a self-contained,\nseparate check with its own two-competition setup (see\n`run_concurrent_check`) — it doesn't fit the single-match mover/RESIGN\nshape the other two modes share, since its whole point is proving *two*\nmatches run at once.\n\n**Default (standalone competition, Milestones 2 + 3A):**\n\n1. Uses your existing primary agent (ALTRUAGENT_CONTROL_URL / ALTRUAGENT_API_KEY).\n2. Creates a temporary second agent via the real `POST /auth/agent/signup`.\n3. Prompts (via getpass — never echoed, stored, or logged) for a human/admin\n   bearer token, and uses it to claim the temporary agent\n   (`POST /auth/human/claim`) and to create a two-player `tic_tac_toe`\n   competition (`POST /admin/competitions/create`).\n4. Joins both agents (`POST /competitions/{id}/join`) and polls\n   `GET /competitions/{id}` (bounded timeout) until it reports\n   `status=in_progress` with a `game_server_url`.\n5. Milestone 3A check: calls `primary.sessions()` (`GET /agents/me/sessions`),\n   confirms the new competition shows up in `.active` with the right\n   `status`/`game_type`, and confirms its `game_server_url` starts out\n   unresolved (this endpoint never includes it). Then opens the primary's\n   `GameSession` via `discovered_match.game()` — the lazy-resolution path\n   (`GET /competitions/{id}` -> cache on the `Match` -> `GameSession`) —\n   instead of `client.game(...)` directly, and confirms the URL is now\n   cached and normalized.\n6. Fetches the initial state and determines whose turn it is from\n   `next_actions`.\n7. Milestone 4B check: hands the mover's *client* (not an already-resolved\n   GameSession) to the production `altruagent.runtime.run_once()`, which\n   itself calls `client.sessions()`, finds the active match, and hands it to\n   `run_match()` — instead of constructing a `GameSession` directly the way\n   Milestone 4A's version of this check did. `run_once()` specifically,\n   never `run_forever()`: it returns after at most one match attempt and\n   never sleeps/loops, so this cannot hang. The decision function still\n   always returns `RESIGN` — the one decision guaranteed to end the match\n   without needing the *other* agent to keep moving too (real multi-agent\n   scheduling stays out of scope until a later milestone). This exercises\n   the real discovery -> `run_match()` -> state -> next_actions ->\n   choose_action -> submit path against the real platform (never the\n   unauthenticated `/games/{id}/cancel`), leaving the human's hosting slot\n   free again. Ordinary move submission was already proven live in\n   Milestones 2/3A and isn't re-proven here.\n\n**`--tournament` (Milestone 3B):** identical agent setup (steps 1-3 above,\nsubstituting `POST /admin/tournaments/create` for the competition create\ncall), then:\n\n4. Joins both agents via the new `client.join_tournament(tournament_id)`\n   (not the low-level competition-join path) and confirms the second join\n   causes (or already sees) the tournament reach `in_progress`.\n5. Uses `primary.sessions()` to find the *tournament-spawned* child match by\n   `tournament_id` (not by an already-known `session_id` — that's the thing\n   this mode proves that the default mode doesn't), then resolves it via\n   `match.game()` exactly as before.\n6-7. Same state-fetch / run_once()-driven-RESIGN as the default mode.\n8. Best-effort (single, non-looping) check of the tournament's final status\n   after cleanup — not a fragile polling loop.\n\n**`--concurrent` (Milestone 4C):** see `run_concurrent_check`'s own\ndocstring for the full flow — in short: two independent standalone\ncompetitions, one shared temporary opponent, confirms both matches are\nsimultaneously `active` via `client.sessions()`, temporarily swaps\n`agent/agent.py`'s contents for a hardcoded deterministic-RESIGN\n`create_agent()` (backed up and always restored — see below), calls the\nproduction `run_once_concurrent()` directly to prove it starts two\ndistinct real worker *processes* (verified via distinct OS PIDs), then\nwaits (bounded) for **both workers to exit on their own** after each\nindependently reaches `run_match()` and resigns its own match — the\ncomplete production path, not a parent-driven shortcut.\n\nThe temporary agent(s) are left claimed — the current backend has no safe\nagent-deletion endpoint, so this script does not invent one.\n\nRun:\n    python scripts/smoke_game.py\n    python scripts/smoke_game.py --tournament\n    python scripts/smoke_game.py --concurrent\n")
    parser.add_argument(
        "--tournament",
        action="store_true",
        help=(
            "Run the tournament-registration smoke test (Milestone 3B) instead "
            "of the default standalone-competition one (Milestones 2 + 3A)."
        ),
    )
    parser.add_argument(
        "--concurrent",
        action="store_true",
        help=(
            "Run the Milestone 4C concurrency check instead: two independent "
            "standalone competitions, proving the supervisor runs two real "
            "worker processes for them at once. Mutually exclusive with "
            "--tournament."
        ),
    )
    args = parser.parse_args()

    if args.concurrent and args.tournament:
        print("--concurrent and --tournament cannot be combined.")
        return 1

    if args.concurrent:
        print("=== Milestone 4C LIVE concurrency smoke test ===")
        print("This calls the REAL deployed AltruAgent platform. It is a developer")
        print("diagnostic tool, not contestant-facing functionality.\n")
        try:
            primary = AltruAgentClient()
        except ConfigurationError as exc:
            print(f"Configuration error: {exc}")
            return 1
        http = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
        try:
            return run_concurrent_check(primary, http, primary.control_url)
        finally:
            primary.close()
            http.close()

    mode_label = "tournament" if args.tournament else "standalone competition"
    print(f"=== Milestone 2 + 3A/3B LIVE smoke test ({mode_label} mode) ===")
    print("This calls the REAL deployed AltruAgent platform. It is a developer")
    print("diagnostic tool, not contestant-facing functionality.\n")

    try:
        primary = AltruAgentClient()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}")
        return 1

    http = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
    opponent: AltruAgentClient | None = None
    primary_session = None
    tournament_id: str | None = None
    cleaned_up = False

    try:
        primary_agent = primary.me()
        if not primary_agent.is_claimed:
            _fail(
                f"Primary agent '{primary_agent.name}' is not claimed "
                f"(status={primary_agent.status}). Claim it before running this test."
            )
        _checkpoint(f"primary agent authenticated ({primary_agent.name})")

        control_url = primary.control_url
        name, opp_api_key, claim_token = signup_temporary_agent(http, control_url)

        human_token = getpass.getpass(
            "Human/admin bearer token (used only for this run — never stored, "
            "logged, or echoed): "
        )
        if not human_token:
            _fail("A human/admin bearer token is required to claim the temporary agent.")

        claim_temporary_agent(http, control_url, claim_token, human_token)
        opponent = AltruAgentClient(control_url=control_url, api_key=opp_api_key)
        opponent_agent = opponent.me()
        if not opponent_agent.is_claimed:
            _fail(f"Temporary agent '{name}' was not claimed successfully.")
        _checkpoint(f"temporary opponent created and claimed ({name})")

        if args.tournament:
            tournament_id = create_tournament(http, control_url, human_token)
            _checkpoint(f"tournament created (tournament_id={tournament_id})")

            primary.join_tournament(tournament_id)
            opponent.join_tournament(tournament_id)
            _checkpoint("both agents joined tournament (via client.join_tournament)")

            wait_for_tournament_in_progress(
                lambda: primary.request("GET", f"/tournaments/{tournament_id}")["tournament"]
            )
            _checkpoint("tournament reached in_progress")

            discovered_match = next(
                (m for m in primary.sessions().active if m.tournament_id == tournament_id),
                None,
            )
            if discovered_match is None:
                _fail(
                    f"client.sessions() did not list an active match with "
                    f"tournament_id={tournament_id!r}."
                )
            session_id = discovered_match.session_id
            _checkpoint(
                f"active match discovered via client.sessions() (session_id={session_id})"
            )

            primary_session = discovered_match.rest_game()
            _checkpoint("GameAPI URL resolved lazily via match.rest_game()")

            opponent_session = opponent.game(
                session_id=session_id, game_server_url=primary_session.game_server_url
            )
        else:
            session_id = create_competition(http, control_url, human_token)
            _checkpoint(f"competition created (session_id={session_id})")

            join_competition(primary, session_id)
            join_competition(opponent, session_id)
            _checkpoint("both agents joined")

            competition = wait_for_in_progress(
                lambda: primary.request("GET", f"/competitions/{session_id}")
            )
            game_server_url = competition["game_server_url"]
            _checkpoint(f"GameAPI session started (game_server_url={game_server_url})")

            discovered_match = next(
                (m for m in primary.sessions().active if m.session_id == session_id), None
            )
            if discovered_match is None:
                _fail(
                    f"client.sessions() did not list session_id={session_id!r} in "
                    "active_sessions after the competition started."
                )
            if discovered_match.status != "in_progress" or discovered_match.game_type != COMPETITION_GAME_TYPE:
                _fail(
                    "Discovered match has unexpected fields (status="
                    f"{discovered_match.status!r}, game_type={discovered_match.game_type!r})."
                )
            if discovered_match.game_server_url is not None:
                _fail(
                    "Expected the freshly discovered Match to have no resolved "
                    f"game_server_url yet, but got {discovered_match.game_server_url!r} — "
                    "GET /agents/me/sessions is not expected to include one."
                )
            _checkpoint("active match discovered via client.sessions()")

            primary_session = discovered_match.rest_game()
            if not discovered_match.game_server_url:
                _fail("discovered_match.game_server_url was not populated after match.rest_game().")
            if not primary_session.game_server_url.startswith(("http://", "https://")):
                _fail(
                    "GameSession.game_server_url is not a normalized URL: "
                    f"{primary_session.game_server_url!r}"
                )
            _checkpoint("GameAPI URL resolved lazily via match.rest_game()")

            opponent_session = opponent.game(session_id=session_id, game_server_url=game_server_url)

        primary_state = primary_session.state()
        _checkpoint("initial state fetched")
        mover_name = primary_state.current_player.name if primary_state.current_player else None
        print(
            f"    game_name={primary_state.game_name} phase={primary_state.phase} "
            f"current_player={mover_name} move_count={primary_state.move_count}"
        )

        if mover_name == primary_agent.name:
            mover_client, mover_session, mover_state, mover_agent_id = (
                primary,
                primary_session,
                primary_state,
                primary_agent.id,
            )
        elif mover_name == opponent_agent.name:
            mover_client, mover_session, mover_state, mover_agent_id = (
                opponent,
                opponent_session,
                opponent_session.state(),
                opponent_agent.id,
            )
        else:
            _fail(f"Could not determine which agent should move (current_player={mover_name!r}).")

        move_action_kinds = {a.action for a in mover_state.next_actions}
        if "make_move" not in move_action_kinds or not mover_state.legal_actions:
            _fail(
                "Mover's next_actions does not include make_move, or legal_actions is "
                f"empty (next_actions={sorted(move_action_kinds)}, "
                f"legal_actions={mover_state.legal_actions})."
            )

        serviced = run_once(
            mover_client,
            lambda state, context: RESIGN,
            agent_id=mover_agent_id,
            failed_until={},
        )
        if not serviced:
            _fail(
                "run_once() did not find the active match through "
                "client.sessions() discovery — nothing was serviced."
            )
        final_state = mover_session.state()
        if not final_state.is_terminal:
            _fail(
                "Match is not terminal after run_once() serviced it "
                f"(status={final_state.status!r})."
            )
        _checkpoint(f"match discovered and resigned via run_once() (by {mover_name})")
        print("[OK] cleanup: match ended via runtime-driven discovery + resign")
        cleaned_up = True

        if args.tournament:
            try:
                final_tournament = primary.tournament(tournament_id)
                print(f"[INFO] tournament status after cleanup: {final_tournament.status}")
            except AltruAgentError as exc:
                print(f"[INFO] could not fetch final tournament status (non-fatal): {exc}")

        print(
            f"\n[NOTE] Temporary agent '{name}' remains claimed — the current backend "
            "has no safe agent-deletion endpoint, so it was not deleted."
        )

        if args.tournament:
            print("\nMILESTONE 3B + 4A/4B LIVE TOURNAMENT SMOKE TEST PASSED")
        else:
            print("\nMILESTONE 3A + 4A/4B LIVE SMOKE TEST PASSED")
        return 0

    except (SmokeTestError, AltruAgentError) as exc:
        print(f"\nSMOKE TEST FAILED: {exc}")
        return 1
    finally:
        if not cleaned_up and primary_session is not None:
            try:
                state = primary_session.state()
                if not state.is_terminal:
                    primary_session.resign()
                    print("[OK] cleanup (failure path): match resigned")
            except AltruAgentError:
                pass
        primary.close()
        if opponent is not None:
            opponent.close()
        http.close()


if __name__ == "__main__":
    raise SystemExit(main())
