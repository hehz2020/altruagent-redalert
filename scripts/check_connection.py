from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.__main__ import main as agent_main


def main(argv: list[str] | None = None) -> int:
    return agent_main(["--check-tournament", *(argv or [])])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
