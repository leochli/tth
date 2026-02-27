# src/tth/core/__init__.py
"""Core types, config, and registry."""

from tth.core.types import (
    EmotionLabel,
    EmotionControl,
    CharacterControl,
    TurnControl,
    AudioChunk,
    VideoFrame,
    HealthStatus,
    AdapterCapabilities,
    TextDeltaEvent,
    AudioChunkEvent,
    VideoFrameEvent,
    TurnCompleteEvent,
    ErrorEvent,
    UserTextEvent,
    InterruptEvent,
    ControlUpdateEvent,
    InboundEvent,
)
from tth.core.config import settings
from tth.core.registry import register, get, create, list_registered

__all__ = [
    # Types
    "EmotionLabel",
    "EmotionControl",
    "CharacterControl",
    "TurnControl",
    "AudioChunk",
    "VideoFrame",
    "HealthStatus",
    "AdapterCapabilities",
    # Outbound events
    "TextDeltaEvent",
    "AudioChunkEvent",
    "VideoFrameEvent",
    "TurnCompleteEvent",
    "ErrorEvent",
    # Inbound events
    "UserTextEvent",
    "InterruptEvent",
    "ControlUpdateEvent",
    "InboundEvent",
    # Config
    "settings",
    # Registry
    "register",
    "get",
    "create",
    "list_registered",
]
