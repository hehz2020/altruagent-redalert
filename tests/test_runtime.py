from __future__ import annotations

import pytest

from altruagent.errors import AuthenticationError, PlatformError
from altruagent.models import AgentSessions, Match
from altruagent.runner import DecisionError, UnsupportedGameFlowError
from altruagent.runtime import run_forever, run_once

AGENT_ID = "agent-1"


def match(session_id: str, **overrides) -> Match:
    payload = {"session_id": session_id, "status": "in_progress", "game_type": "tic_tac_toe"}
    payload.update(overrides)
    return Match.from_dict(payload)


def sessions_with_active(*matches: Match) -> AgentSessions:
    return AgentSessions(waiting=[], active=list(matches), completed=[])


class FakeClient:


    def __init__(self, *responses: AgentSessions) -> None:
        self._responses = list(responses)
        self.calls = 0

    def sessions(self) -> AgentSessions:
        self.calls += 1
        index = min(self.calls - 1, len(self._responses) - 1)
        return self._responses[index]


def no_sleep(_seconds: float) -> None:
    pass


def make_clock(start: float = 0.0, step: float = 1.0):
    state = {"t": start}

    def now() -> float:
        state["t"] += step
        return state["t"]

    return now




def test_run_once_no_active_sessions_returns_false_without_running_a_match():
    client = FakeClient(sessions_with_active())
    calls = []

    result = run_once(
        client,
        lambda s, c: 0,
        agent_id=AGENT_ID,
        failed_until={},
        run_match_fn=lambda *a, **k: calls.append(a) or pytest.fail("should not run"),
    )

    assert result is False
    assert calls == []


def test_run_once_waiting_and_completed_sessions_are_ignored():
    sessions = AgentSessions(
        waiting=[match("s-waiting")], active=[], completed=[match("s-done")]
    )
    client = FakeClient(sessions)

    result = run_once(
        client,
        lambda s, c: 0,
        agent_id=AGENT_ID,
        failed_until={},
        run_match_fn=lambda *a, **k: pytest.fail("waiting/completed must not be run"),
    )

    assert result is False


def test_run_once_one_active_match_is_serviced_via_run_match_fn():
    m = match("s-1")
    client = FakeClient(sessions_with_active(m))
    run_match_calls = []

    class FinalState:
        termination_reason = "completed"

    def fake_run_match(passed_match, agent_id, choose_action):
        run_match_calls.append((passed_match.session_id, agent_id))
        return FinalState()

    result = run_once(
        client,
        lambda s, c: 0,
        agent_id=AGENT_ID,
        failed_until={},
        run_match_fn=fake_run_match,
    )

    assert result is True
    assert run_match_calls == [("s-1", AGENT_ID)]




def test_run_once_picks_first_eligible_match_in_server_order():
    m1, m2 = match("s-1"), match("s-2")
    client = FakeClient(sessions_with_active(m1, m2))
    serviced = []

    def fake_run_match(m, agent_id, choose_action):
        serviced.append(m.session_id)

        class FinalState:
            termination_reason = "completed"

        return FinalState()

    run_once(client, lambda s, c: 0, agent_id=AGENT_ID, failed_until={}, run_match_fn=fake_run_match)

    assert serviced == ["s-1"]


def test_run_once_skips_match_in_cooldown_for_the_next_eligible_one():
    m1, m2 = match("s-1"), match("s-2")
    client = FakeClient(sessions_with_active(m1, m2))
    serviced = []

    def fake_run_match(m, agent_id, choose_action):
        serviced.append(m.session_id)

        class FinalState:
            termination_reason = "completed"

        return FinalState()

    result = run_once(
        client,
        lambda s, c: 0,
        agent_id=AGENT_ID,
        failed_until={"s-1": 1000.0},
        now=lambda: 5.0,
        run_match_fn=fake_run_match,
    )

    assert result is True
    assert serviced == ["s-2"]


def test_run_once_returns_false_when_every_active_match_is_in_cooldown():
    m1 = match("s-1")
    client = FakeClient(sessions_with_active(m1))

    result = run_once(
        client,
        lambda s, c: 0,
        agent_id=AGENT_ID,
        failed_until={"s-1": 1000.0},
        now=lambda: 5.0,
        run_match_fn=lambda *a, **k: pytest.fail("should not run a cooling-down match"),
    )

    assert result is False




@pytest.mark.parametrize(
    "error",
    [
        DecisionError("contestant bug"),
        UnsupportedGameFlowError("messaging not supported"),
        PlatformError("boom", status_code=500, error_code="server_error"),
    ],
)
def test_match_scoped_errors_do_not_propagate_and_set_cooldown(error):
    m = match("s-1")
    client = FakeClient(sessions_with_active(m))
    failed_until: dict = {}

    def failing_run_match(*a, **k):
        raise error

    result = run_once(
        client,
        lambda s, c: 0,
        agent_id=AGENT_ID,
        failed_until=failed_until,
        now=lambda: 100.0,
        cooldown_seconds=60.0,
        run_match_fn=failing_run_match,
    )

    assert result is True
    assert failed_until["s-1"] == 160.0


def test_authentication_error_propagates_as_fatal():
    m = match("s-1")
    client = FakeClient(sessions_with_active(m))

    def failing_run_match(*a, **k):
        raise AuthenticationError("bad key")

    with pytest.raises(AuthenticationError):
        run_once(
            client,
            lambda s, c: 0,
            agent_id=AGENT_ID,
            failed_until={},
            run_match_fn=failing_run_match,
        )


def test_cooldown_prevents_tight_retry_loop_across_run_forever_ticks():
    m = match("s-1")
    client = FakeClient(sessions_with_active(m))
    attempts = []

    def always_fails(*a, **k):
        attempts.append(1)
        raise DecisionError("deterministically broken")

    sleeps = []
    run_forever(
        client,
        lambda s, c: 0,
        agent_id=AGENT_ID,
        discovery_interval=15.0,
        cooldown_seconds=60.0,
        sleep=sleeps.append,
        now=make_clock(start=0.0, step=1.0),
        run_match_fn=always_fails,
        max_iterations=5,
    )

    assert len(attempts) == 1
    assert sleeps == [15.0, 15.0, 15.0, 15.0]




def test_run_forever_services_matches_one_at_a_time_across_ticks():
    m1, m2 = match("s-1"), match("s-2")
    client = FakeClient(sessions_with_active(m1, m2))
    in_flight = {"count": 0}
    max_concurrent = {"seen": 0}
    serviced_order = []

    def fake_run_match(m, agent_id, choose_action):
        in_flight["count"] += 1
        max_concurrent["seen"] = max(max_concurrent["seen"], in_flight["count"])
        serviced_order.append(m.session_id)
        in_flight["count"] -= 1

        class FinalState:
            termination_reason = "completed"

        return FinalState()

    run_forever(
        client,
        lambda s, c: 0,
        agent_id=AGENT_ID,
        sleep=no_sleep,
        now=make_clock(),
        run_match_fn=fake_run_match,
        max_iterations=4,
    )

    assert max_concurrent["seen"] == 1
    assert serviced_order == ["s-1", "s-1", "s-1", "s-1"]


def test_run_forever_refreshes_sessions_after_each_match_rather_than_reusing_stale_state():
    m1 = match("s-1")
    client = FakeClient(sessions_with_active(m1), sessions_with_active())
    calls = []

    def fake_run_match(m, agent_id, choose_action):
        calls.append(m.session_id)

        class FinalState:
            termination_reason = "completed"

        return FinalState()

    sleeps = []
    run_forever(
        client,
        lambda s, c: 0,
        agent_id=AGENT_ID,
        sleep=sleeps.append,
        now=make_clock(),
        run_match_fn=fake_run_match,
        max_iterations=2,
    )

    assert calls == ["s-1"]
    assert client.calls == 2
    assert sleeps == [15.0]
