# src/tth/adapters/avatar/stub.py
from __future__ import annotations

import asyncio
import colorsys
import io
from typing import Any, AsyncIterator

from PIL import Image, ImageDraw

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
_frame_counter = 0


def _generate_color_frame(hue: float = 0.0, frame_index: int = 0) -> bytes:
    """Generate a JPEG frame with a cycling color pattern.

    Creates a simple test pattern that shows animation is working.
    """
    # Create image
    img = Image.new("RGB", (_W, _H))
    draw = ImageDraw.Draw(img)

    # Background color cycles through hues
    r, g, b = colorsys.hsv_to_rgb(hue % 1.0, 0.6, 0.9)
    bg_color = (int(r * 255), int(g * 255), int(b * 255))
    draw.rectangle([(0, 0), (_W, _H)], fill=bg_color)

    # Draw frame number as text (centered)
    text = f"Frame {frame_index}"
    text_color = (255, 255, 255) if sum(bg_color) < 400 else (0, 0, 0)

    # Use a simple approach - draw a circle that pulses
    center = _W // 2
    radius = 30 + int(20 * (1 + (hue * 10 % 1)))
    draw.ellipse(
        [(center - radius, center - radius), (center + radius, center + radius)],
        fill=text_color,
        outline=(100, 100, 100),
        width=2,
    )

    # Draw frame counter bar at bottom
    bar_width = int((_W - 20) * ((frame_index % 100) / 100))
    draw.rectangle([(10, _H - 30), (10 + bar_width, _H - 10)], fill=(200, 200, 200))

    # Convert to JPEG
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


@register("stub_avatar")
class StubAvatarAdapter(AdapterBase):
    """Emits placeholder video frames for testing.

    Generates color-cycling JPEG frames that exercise the full pipeline
    without requiring actual avatar generation.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.fps = config.get("fps", 25)

    async def infer_stream(
        self, input: AudioChunk, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[VideoFrame]:
        """Yield frames at configured FPS based on audio duration."""
        global _frame_counter

        # Calculate number of frames needed
        frames = max(1, round(input.duration_ms / 1000 * self.fps))
        frame_duration_ms = 1000 / self.fps
        base_idx = context.get("frame_counter", 0)

        for i in range(frames):
            # Cycle through colors (hue 0-1)
            hue = _frame_counter * 0.03
            jpeg_data = _generate_color_frame(hue, _frame_counter)
            _frame_counter += 1

            yield VideoFrame(
                data=jpeg_data,
                timestamp_ms=input.timestamp_ms + i * frame_duration_ms,
                frame_index=base_idx + i,
                width=_W,
                height=_H,
                content_type="jpeg",
            )
            # Small delay to not overwhelm the client
            await asyncio.sleep(0.001)

    async def health(self) -> HealthStatus:
        return HealthStatus(healthy=True, detail="stub adapter — always healthy")

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_emotion=False,
            supports_identity=False,
        )
