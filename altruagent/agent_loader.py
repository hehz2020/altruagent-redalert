from __future__ import annotations

import importlib
from typing import Callable

DEFAULT_AGENT_SPEC = "agent.agent:create_agent"


def load_agent_factory(spec: str) -> Callable:

    module_name, _, factory_name = spec.partition(":")
    factory_name = factory_name or "create_agent"
    if (
        not module_name
        or not all(part.isidentifier() for part in module_name.split("."))
        or not factory_name.isidentifier()
    ):
        raise ValueError(
            "--agent expects MODULE[:FACTORY] — a dotted module path such as "
            f"examples.messaging_agent or my_agents.v2:build_agent — got {spec!r}."
        )
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name and (module_name == exc.name or module_name.startswith(exc.name + ".")):
            raise ValueError(
                f"Could not find agent module {module_name!r}. Run from the starter's "
                "root directory and pass a dotted module path, not a file path."
            ) from exc
        raise ValueError(f"Importing agent module {module_name!r} failed: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Importing agent module {module_name!r} raised {exc!r}.") from exc

    factory = getattr(module, factory_name, None)
    if not callable(factory):
        raise ValueError(
            f"{module_name}:{factory_name} is missing or not callable. It must be a "
            "function returning your decision logic (a function, or an object "
            "exposing choose_action(state, context))."
        )
    return factory
