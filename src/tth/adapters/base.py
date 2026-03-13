# src/tth/adapters/base.py
from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator
from tth.core.types import (
    TurnControl,
    HealthStatus,
    AdapterCapabilities,
    AudioChunk,
    VideoFrame,
)


class AdapterBase(ABC):
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    async def load(self) -> None:
        """Load model weights or establish connection. Called once at startup."""

    async def warmup(self) -> None:
        """Send a throwaway inference request to prime caches. Optional."""

    @abstractmethod
    async def infer_stream(
        self,
        input: str | bytes | AudioChunk,
        control: TurnControl,
        context: dict[str, Any],
    ) -> AsyncIterator[str | AudioChunk | VideoFrame]:
        """Stream output tokens/chunks/frames. Must be an async generator."""
        ...

    async def interrupt(self) -> None:
        """Interrupt current inference and clear buffers. Optional.

        Override in subclasses that support interruptible streaming.
        Called when user sends InterruptEvent or new user_text arrives.
        """
        pass  # Default: no-op for adapters that don't support interruption

    async def relay_frames(self, stop: asyncio.Event) -> AsyncIterator[VideoFrame]:
        """Yield frames from background stream. Override in push-model adapters."""
        return
        yield  # makes this an async generator

    @abstractmethod
    async def health(self) -> HealthStatus: ...

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities()
