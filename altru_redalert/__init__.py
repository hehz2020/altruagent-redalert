"""Scripted Red Alert player; policy modules can be imported without the SDK."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__version__ = "2.3"

if TYPE_CHECKING:
    from .adapter import RedAlertAgent

__all__ = ["RedAlertAgent", "create_agent"]


def create_agent() -> RedAlertAgent:
    """Load the SDK adapter when the official runtime asks for an agent."""
    from .adapter import RedAlertAgent

    return RedAlertAgent()


def __getattr__(name: str) -> Any:
    if name == "RedAlertAgent":
        from .adapter import RedAlertAgent

        return RedAlertAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
