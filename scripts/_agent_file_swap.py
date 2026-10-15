from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

AGENT_FILE = Path(__file__).resolve().parent.parent / "agent" / "agent.py"
AGENT_FILE_BACKUP = AGENT_FILE.with_suffix(".py.smoke_test_backup")


class AgentFileSwapError(RuntimeError):
    pass


def _atomic_write(path: Path, text: str) -> None:

    tmp_path = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def install_temporary_agent(source_text: str) -> None:

    if AGENT_FILE_BACKUP.exists():
        raise AgentFileSwapError(
            f"{AGENT_FILE_BACKUP} already exists, which means a previous run "
            "of a test script (smoke_game.py --concurrent or "
            "acceptance_test.py) did not restore agent/agent.py cleanly, or "
            "another run is using it right now. Refusing to guess which of "
            f"{AGENT_FILE.name} or {AGENT_FILE_BACKUP.name} holds your real "
            f"agent code — compare the two files yourself, make sure "
            f"{AGENT_FILE.name} has the version you want to keep, then "
            f"delete {AGENT_FILE_BACKUP.name} before re-running."
        )

    real_text = AGENT_FILE.read_text(encoding="utf-8")
    _atomic_write(AGENT_FILE_BACKUP, real_text)
    _atomic_write(AGENT_FILE, source_text)


def restore_real_agent() -> None:

    if AGENT_FILE_BACKUP.exists():
        os.replace(AGENT_FILE_BACKUP, AGENT_FILE)


@contextmanager
def temporary_agent(source_text: str) -> Iterator[None]:

    install_temporary_agent(source_text)
    try:
        yield
    finally:
        restore_real_agent()
