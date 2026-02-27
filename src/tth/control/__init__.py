# src/tth/control/__init__.py
"""Control plane: emotion and character mapping."""

from tth.control.mapper import resolve as resolve_controls
from tth.control.personas import get_persona_defaults, get_persona_name

__all__ = ["resolve_controls", "get_persona_defaults", "get_persona_name"]
