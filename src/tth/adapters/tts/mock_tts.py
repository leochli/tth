# src/tth/adapters/tts/mock_tts.py
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from tth.adapters.base import AdapterBase
from tth.core.registry import register
from tth.core.types import AdapterCapabilities, AudioChunk, HealthStatus, TurnControl


@register("mock_tts")
class MockTTSAdapter(AdapterBase):
    """Deterministic pseudo-audio chunk stream for offline/integration testing."""

    async def infer_stream(
        self, input: str, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[AudioChunk]:
        # Approximate timing so downstream avatar/drift behavior is realistic.
        total_ms = max(250.0, min(1800.0, len(input) * 12.0))
        num_chunks = max(2, min(8, len(input) // 35 + 1))
        chunk_ms = total_ms / num_chunks
        ts = context.get("mock_start_ms", 0.0)

        for i in range(num_chunks):
            payload = (
                f"MOCK_MP3|chunk={i}|speed={control.character.speech_rate:.2f}|{input}".encode(
                    "utf-8"
                )
            )
            # Keep payload non-trivial while bounded.
            payload = payload[:2048]
            yield AudioChunk(
                data=payload,
                timestamp_ms=ts,
                duration_ms=chunk_ms,
                sample_rate=24000,
                encoding="mock_mp3",
            )
            ts += chunk_ms
            await asyncio.sleep(0.01)

    async def health(self) -> HealthStatus:
        return HealthStatus(healthy=True, latency_ms=0.1, detail="mock tts")

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_emotion=True,
            supports_identity=False,
            max_text_length=100000,
            supported_emotions=[
                "neutral",
                "happy",
                "sad",
                "angry",
                "surprised",
                "fearful",
                "disgusted",
            ],
        )
