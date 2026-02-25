# src/tth/adapters/tts/openai_tts.py
from __future__ import annotations
import time
from typing import Any, AsyncIterator
import httpx
from tth.adapters.base import AdapterBase
from tth.control.mapper import map_emotion_to_openai_tts
from tth.core.config import settings
from tth.core.registry import register
from tth.core.types import (
    AdapterCapabilities,
    AudioChunk,
    HealthStatus,
    TurnControl,
    estimate_pcm_duration_ms,
)

_OPENAI_PCM_SAMPLE_RATE = 24000  # OpenAI TTS PCM output is 24kHz 16-bit mono


@register("openai_tts")
class OpenAITTSAdapter(AdapterBase):
    """
    Streams PCM chunks from OpenAI TTS.
    Reuses OPENAI_API_KEY — no extra credentials needed.
    PCM format (24kHz, 16-bit, mono) enables low-latency streaming playback.
    """

    _BASE = "https://api.openai.com/v1"

    async def infer_stream(
        self, input: str, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[AudioChunk]:
        tts_params = map_emotion_to_openai_tts(control.emotion, control.character)
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
        payload = {
            "model": self.config.get("model", "tts-1"),
            "input": input,
            "voice": tts_params["voice"],
            "speed": tts_params["speed"],
            "response_format": "pcm",
        }
        wall_ms = time.monotonic() * 1000

        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST",
                f"{self._BASE}/audio/speech",
                headers=headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for raw in resp.aiter_bytes(chunk_size=4096):
                    if not raw:
                        continue
                    duration = estimate_pcm_duration_ms(raw, _OPENAI_PCM_SAMPLE_RATE)
                    yield AudioChunk(
                        data=raw,
                        timestamp_ms=wall_ms,
                        duration_ms=duration,
                        sample_rate=24000,
                        encoding="pcm",
                    )
                    wall_ms += duration  # advance wall clock by this chunk's duration

    async def health(self) -> HealthStatus:
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(
                    f"{self._BASE}/models",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                )
            return HealthStatus(
                healthy=r.status_code == 200,
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        except Exception as exc:
            return HealthStatus(
                healthy=False,
                latency_ms=(time.monotonic() - t0) * 1000,
                detail=str(exc),
            )

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_emotion=True,  # via voice selection + speed
            supported_emotions=["neutral", "happy", "sad", "angry", "surprised", "fearful"],
        )
