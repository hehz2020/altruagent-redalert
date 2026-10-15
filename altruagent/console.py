from __future__ import annotations

import sys


def print_line(message: str) -> None:

    stream = sys.stdout
    if stream is None:
        return
    stream.write(f"{message}\n")
    stream.flush()
