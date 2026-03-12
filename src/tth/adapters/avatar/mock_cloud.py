# src/tth/adapters/avatar/mock_cloud.py
"""Mock cloud avatar adapter for development and CI testing."""
from __future__ import annotations

import asyncio
import logging
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

logger = logging.getLogger(__name__)

# Default test frame dimensions
_W, _H = 512, 512


def _generate_test_frame_jpeg(width: int = _W, height: int = _H) -> bytes:
    """Generate a simple test JPEG frame without external dependencies.

    Creates a minimal valid JPEG with a gray frame. This avoids requiring
    cv2/PIL for the mock adapter.
    """
    # Minimal JPEG structure for a gray frame
    # This is a valid JPEG that decodes to a gray image
    # JPEG format: SOI + APP0 + DQT + SOF0 + DHT + SOS + EOI

    # For simplicity, generate a small valid JPEG and let clients scale it
    # This creates an 8x8 gray JPEG that's valid but minimal
    gray_jpeg = bytes([
        0xFF, 0xD8,  # SOI
        0xFF, 0xE0,  # APP0
        0x00, 0x10,  # Length
        0x4A, 0x46, 0x49, 0x46, 0x00,  # JFIF\0
        0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
        # DQT - Quantization table
        0xFF, 0xDB, 0x00, 0x43, 0x00,
    ] + [0x10] * 64 + [  # All 16s for simple quantization
        # SOF0 - Start of frame
        0xFF, 0xC0, 0x00, 0x0B, 0x08,
        0x00, 0x08,  # Height: 8
        0x00, 0x08,  # Width: 8
        0x01, 0x01, 0x11, 0x00,  # 1 component
        # DHT - Huffman table
        0xFF, 0xC4, 0x00, 0x1F, 0x00,
        0x00, 0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01,
        0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B,
        # SOS - Start of scan
        0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00,
        # Scan data (gray value)
        0xFB, 0xD3, 0x28, 0xA2, 0x80, 0x00,
        # EOI
        0xFF, 0xD9,
    ])
    return gray_jpeg


@register("mock_cloud_avatar")
class MockCloudAvatarAdapter(AdapterBase):
    """Simulates cloud avatar service with configurable latency.

    Use for local development and CI testing without actual Modal deployment.
    Generates simple test frames that exercise the full pipeline.

    Configuration:
        simulated_latency_ms: Network + inference latency to simulate (default: 150)
        resolution: [width, height] of output frames (default: [512, 512])
        fps: Frames per second to generate (default: 25)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.simulated_latency_ms = config.get("simulated_latency_ms", 150)
        self.resolution = config.get("resolution", [_W, _H])
        self.fps = config.get("fps", 25)
        self.frame_index = 0
        self._test_frame: bytes | None = None

    async def load(self) -> None:
        """Load a test frame to return during inference."""
        # Generate a test frame
        self._test_frame = _generate_test_frame_jpeg(
            self.resolution[0], self.resolution[1]
        )
        logger.info(
            f"MockCloudAvatarAdapter loaded (latency={self.simulated_latency_ms}ms, "
            f"resolution={self.resolution})"
        )

    async def infer_stream(
        self, input: AudioChunk, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[VideoFrame]:
        """Simulate cloud inference with configurable latency.

        Args:
            input: AudioChunk (PCM, 24kHz)
            control: TurnControl with emotion/character settings
            context: Pipeline context with session_id, frame_counter

        Yields:
            VideoFrame objects timed to match audio duration
        """
        if self._test_frame is None:
            await self.load()
            assert self._test_frame is not None  # load() sets _test_frame

        # Simulate network + inference latency
        await asyncio.sleep(self.simulated_latency_ms / 1000)

        # Calculate frames based on audio duration
        frames = max(1, round(input.duration_ms / 1000 * self.fps))
        frame_duration_ms = 1000 / self.fps
        base_idx = context.get("frame_counter", 0)

        logger.debug(
            f"MockCloudAvatar generating {frames} frames for "
            f"{input.duration_ms:.0f}ms audio"
        )

        for i in range(frames):
            yield VideoFrame(
                data=self._test_frame,
                timestamp_ms=input.timestamp_ms + i * frame_duration_ms,
                frame_index=base_idx + i,
                width=self.resolution[0],
                height=self.resolution[1],
                content_type="jpeg",
            )
        self.frame_index += frames

    async def interrupt(self) -> None:
        """Handle interrupt - reset frame counter."""
        logger.info("MockCloudAvatarAdapter interrupted")
        self.frame_index = 0

    async def health(self) -> HealthStatus:
        return HealthStatus(
            healthy=True,
            latency_ms=self.simulated_latency_ms,
            detail="mock adapter - simulated",
        )

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_emotion=False,  # Mock doesn't implement emotion
            supports_identity=False,
        )
