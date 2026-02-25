# src/tth/core/registry.py
from __future__ import annotations
from typing import Any

_registry: dict[str, type] = {}


def register(name: str):
    """Decorator: @register("openai_chat") on an AdapterBase subclass."""

    def decorator(cls: type) -> type:
        _registry[name] = cls
        return cls

    return decorator


def get(name: str) -> type:
    if name not in _registry:
        raise KeyError(f"No adapter registered for '{name}'. Available: {sorted(_registry)}")
    return _registry[name]


def create(name: str, config: dict[str, Any]) -> Any:
    """Instantiate a registered adapter with given config dict."""
    return get(name)(config)


def list_registered() -> list[str]:
    """Return all registered adapter names."""
    return sorted(_registry.keys())
