from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import smoke_game


def _clock(values):
    it = iter(values)
    return lambda: next(it)


def test_wait_for_in_progress_returns_as_soon_as_ready():
    poll_results = iter(
        [
            {"status": "waiting", "game_server_url": None},
            {"status": "in_progress", "game_server_url": "host:8000"},
        ]
    )
    sleep_calls = []

    result = smoke_game.wait_for_in_progress(
        lambda: next(poll_results),
        timeout_seconds=10.0,
        interval_seconds=1.0,
        sleep=sleep_calls.append,
        now=_clock([0.0, 1.0]),
    )

    assert result == {"status": "in_progress", "game_server_url": "host:8000"}
    assert sleep_calls == [1.0]


def test_wait_for_in_progress_returns_immediately_without_sleeping():
    poll_results = iter([{"status": "in_progress", "game_server_url": "host:8000"}])
    sleep_calls = []

    result = smoke_game.wait_for_in_progress(
        lambda: next(poll_results),
        timeout_seconds=10.0,
        interval_seconds=1.0,
        sleep=sleep_calls.append,
        now=_clock([0.0]),
    )

    assert result["status"] == "in_progress"
    assert sleep_calls == []


def test_wait_for_in_progress_times_out_without_looping_forever():
    poll_results = itertools.repeat({"status": "waiting", "game_server_url": None})
    sleep_calls = []
    clock = _clock([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0])

    with pytest.raises(smoke_game.SmokeTestError):
        smoke_game.wait_for_in_progress(
            lambda: next(poll_results),
            timeout_seconds=5.0,
            interval_seconds=1.0,
            sleep=sleep_calls.append,
            now=clock,
        )

    assert len(sleep_calls) <= 6


def test_wait_for_in_progress_ignores_in_progress_without_game_server_url():
    poll_results = iter(
        [
            {"status": "in_progress", "game_server_url": None},
            {"status": "in_progress", "game_server_url": "host:8000"},
        ]
    )
    sleep_calls = []

    result = smoke_game.wait_for_in_progress(
        lambda: next(poll_results),
        timeout_seconds=10.0,
        interval_seconds=1.0,
        sleep=sleep_calls.append,
        now=_clock([0.0, 1.0]),
    )

    assert result["game_server_url"] == "host:8000"
    assert sleep_calls == [1.0]


def test_wait_for_tournament_in_progress_returns_as_soon_as_ready():
    poll_results = iter([{"status": "waiting"}, {"status": "in_progress"}])
    sleep_calls = []

    result = smoke_game.wait_for_tournament_in_progress(
        lambda: next(poll_results),
        timeout_seconds=10.0,
        interval_seconds=1.0,
        sleep=sleep_calls.append,
        now=_clock([0.0, 1.0]),
    )

    assert result == {"status": "in_progress"}
    assert sleep_calls == [1.0]


def test_wait_for_tournament_in_progress_does_not_require_game_server_url():
    poll_results = iter([{"status": "in_progress"}])
    sleep_calls = []

    result = smoke_game.wait_for_tournament_in_progress(
        lambda: next(poll_results),
        timeout_seconds=10.0,
        interval_seconds=1.0,
        sleep=sleep_calls.append,
        now=_clock([0.0]),
    )

    assert result["status"] == "in_progress"
    assert sleep_calls == []


def test_wait_for_tournament_in_progress_times_out_without_looping_forever():
    poll_results = itertools.repeat({"status": "waiting"})
    sleep_calls = []
    clock = _clock([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0])

    with pytest.raises(smoke_game.SmokeTestError):
        smoke_game.wait_for_tournament_in_progress(
            lambda: next(poll_results),
            timeout_seconds=5.0,
            interval_seconds=1.0,
            sleep=sleep_calls.append,
            now=clock,
        )

    assert len(sleep_calls) <= 6
