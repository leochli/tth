# src/tth/adapters/avatar/stub.py
from __future__ import annotations
import asyncio
from typing import Any, AsyncIterator
from tth.adapters.base import AdapterBase
from tth.core.registry import register
from tth.core.types import (
    AdapterCapabilities,
    AudioChunk,
    HealthStatus,
    TurnControl,
    VideoFrame,
)

_W, _H = 256, 256
# 256×256 solid black raw RGB frame (not JPEG — content_type="raw_rgb")
_BLACK_FRAME = bytes(_W * _H * 3)


@register("stub_avatar")
class StubAvatarAdapter(AdapterBase):
    """
    Emits placeholder VideoFrame events timed to match audio duration.
    Exercises the full pipeline + drift controller without a real avatar API.
    Replace by changing avatar.primary in config — no code changes needed.
    content_type="raw_rgb" signals clients that this is raw bytes, not JPEG.
    """

    FPS: int = 25

    async def infer_stream(
        self, input: AudioChunk, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[VideoFrame]:
        # Use actual duration_ms (always > 0 with corrected TTS adapter)
        frames = max(1, round(input.duration_ms / 1000 * self.FPS))
        frame_duration_ms = 1000 / self.FPS
        base_idx = context.get("frame_counter", 0)

        for i in range(frames):
            yield VideoFrame(
                data=_BLACK_FRAME,
                timestamp_ms=input.timestamp_ms + i * frame_duration_ms,
                frame_index=base_idx + i,
                width=_W,
                height=_H,
                content_type="raw_rgb",
            )
            await asyncio.sleep(frame_duration_ms / 1000)

    async def health(self) -> HealthStatus:
        return HealthStatus(healthy=True, detail="stub adapter — always healthy")

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_emotion=False,
            supports_identity=False,
        )
