from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from altruagent import GameState, LegalAction


class InvalidChoice(ValueError):
    pass


class UnsupportedStructuredAction(ValueError):
    pass


@dataclass
class Choice:
    kind: str
    prompt: dict
    schema: dict
    build: Callable[[dict], Any]
    fallback: Callable[[], Any]


AdapterFactory = Callable[[LegalAction, GameState], Choice]


def object_schema(properties: dict, *, reasoning: bool = True) -> dict:

    if reasoning:
        properties = {**properties, "reasoning_summary": {"type": "string"}}
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
