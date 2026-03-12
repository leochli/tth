# src/tth/adapters/avatar/simli.py
"""Simli real-time audio-to-avatar adapter using the Simli Python SDK (aiortc/WebRTC)."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from typing import Any, AsyncIterator

from PIL import Image
from simli import SimliClient, SimliConfig

from tth.adapters.avatar.buffer import AudioChunkBuffer
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


def _av_frame_to_jpeg(av_frame: Any) -> bytes:
    """Convert a PyAV VideoFrame (rgb24) to JPEG bytes via Pillow."""
    img: Image.Image = av_frame.to_image()
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@register("simli")
class SimliAvatarAdapter(AdapterBase):
    """Real-time audio-to-avatar adapter via Simli's WebRTC API.

    Uses the simli-ai Python SDK which handles:
      - WebRTC ICE negotiation and SDP exchange (aiortc)
      - Audio transmission via WebSocket binary (16kHz PCM)
      - Video reception via WebRTC video track → PyAV VideoFrame

    Pipeline:
        OpenAI Realtime API → 24kHz PCM
            → AudioChunkBuffer (resamples to 16kHz)
                → SimliClient.send() (WebSocket binary)
                    → Simli WebRTC video track
                        → JPEG frames → VideoFrame events

    Configuration:
        face_id: Simli face UUID (see docs.simli.com/api-reference/preset-faces)
        api_key_env: Environment variable for Simli API key (default: SIMLI_API_KEY)
        resolution: [width, height] of output frames
        fps: Target frames per second
        min_chunk_ms: Minimum audio buffer before sending (ms)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.api_key_env = config.get("api_key_env", "SIMLI_API_KEY")
        self.face_id = config.get("face_id", "5514e24d-6086-46a3-ace4-6a7264e5cb7c")
        self.resolution = config.get("resolution", [512, 512])
        self.fps = config.get("fps", 25)

        self._client: Any = None  # SimliClient instance
        self._pending_frames: asyncio.Queue[VideoFrame] = asyncio.Queue(maxsize=64)
        self._frame_consumer_task: asyncio.Task[None] | None = None
        self._frame_index = 0
        self._is_healthy = False
        self._buffer = AudioChunkBuffer(min_chunk_ms=config.get("min_chunk_ms", 100))

    async def load(self) -> None:
        api_key = os.environ.get(self.api_key_env, "")
        if not api_key:
            logger.warning(
                f"Missing {self.api_key_env} — Simli adapter inactive. "
                "Set this environment variable to enable Simli avatars."
            )
            return
        await self._start_client(api_key)

    async def _start_client(self, api_key: str) -> None:
        """Create and connect SimliClient. Starts frame consumer task."""
        try:
            self._client = SimliClient(
                api_key=api_key,
                config=SimliConfig(
                    faceId=self.face_id,
                    handleSilence=True,
                    maxSessionLength=3600,
                    maxIdleTime=300,
                ),
                enableSFU=True,
            )
            await self._client.start()
            # Bootstrap: send silence so Simli primes the video pipeline
            await self._client.sendSilence(0.2)
            self._frame_consumer_task = asyncio.create_task(self._consume_frames())
            self._is_healthy = True
            logger.info(f"Simli connected (face_id={self.face_id})")
        except Exception as e:
            logger.error(f"Simli failed to connect: {e}")
            self._is_healthy = False

    async def _consume_frames(self) -> None:
        """Background task: receive WebRTC video frames and enqueue as JPEG."""
        if self._client is None:
            return
        try:
            async for av_frame in self._client.getVideoStreamIterator("rgb24"):
                try:
                    jpeg_bytes = _av_frame_to_jpeg(av_frame)
                except Exception as e:
                    logger.warning(f"Frame JPEG conversion failed: {e}")
                    continue

                frame = VideoFrame(
                    data=jpeg_bytes,
                    timestamp_ms=time.monotonic() * 1000,
                    frame_index=self._frame_index,
                    width=av_frame.width,
                    height=av_frame.height,
                    content_type="jpeg",
                )
                self._frame_index += 1

                if self._pending_frames.full():
                    # Drop the oldest to make room
                    try:
                        self._pending_frames.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    self._pending_frames.put_nowait(frame)
                except asyncio.QueueFull:
                    pass

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Simli frame consumer ended: {e}")
        finally:
            self._is_healthy = False

    async def _reconnect(self) -> bool:
        """Attempt to reconnect the Simli client. Returns True on success."""
        api_key = os.environ.get(self.api_key_env, "")
        if not api_key:
            return False

        # Clean up old state
        if self._frame_consumer_task and not self._frame_consumer_task.done():
            self._frame_consumer_task.cancel()
            try:
                await self._frame_consumer_task
            except asyncio.CancelledError:
                pass

        if self._client:
            try:
                await self._client.stop()
            except Exception:
                pass
            self._client = None

        logger.info("Simli reconnecting...")
        await self._start_client(api_key)
        return self._is_healthy

    async def infer_stream(
        self, input: AudioChunk, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[VideoFrame]:
        """Stream audio to Simli, yield lip-synced JPEG frames.

        Args:
            input: AudioChunk (PCM, 24kHz — resampled to 16kHz by AudioChunkBuffer)
            control: TurnControl with emotion/character settings
            context: Pipeline context with session_id

        Yields:
            VideoFrame objects (JPEG encoded)
        """
        # Reconnect if unhealthy
        if not self._is_healthy:
            if not await self._reconnect():
                async for frame in self._fallback_to_stub(input, control, context):
                    yield frame
                return

        # Drain any frames that arrived since the last call (Simli has inherent
        # latency, so frames from previously-sent audio batches accumulate here).
        while not self._pending_frames.empty():
            try:
                yield self._pending_frames.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Buffer and resample audio (24kHz → 16kHz)
        ready, resampled = self._buffer.add(input)
        if not ready or resampled is None:
            return

        # Send binary PCM audio to Simli via WebSocket
        try:
            await self._client.send(resampled)
        except Exception as e:
            logger.error(f"Failed to send audio to Simli: {e}")
            self._is_healthy = False
            return

        # After sending audio, wait for the first frame that Simli generates
        # in response.  Simli has 200-400 ms of latency, so a simple non-blocking
        # drain misses all of these frames.  We block up to _FRAME_WAIT_S so the
        # orchestrator doesn't move on before Simli has produced anything.
        _FRAME_WAIT_S = 0.5
        try:
            frame = await asyncio.wait_for(self._pending_frames.get(), timeout=_FRAME_WAIT_S)
            yield frame
        except asyncio.TimeoutError:
            logger.debug("Simli: no frame within %.0f ms after audio send", _FRAME_WAIT_S * 1000)
            return

        # Drain any additional frames that also arrived during the wait.
        while not self._pending_frames.empty():
            try:
                yield self._pending_frames.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _fallback_to_stub(
        self, input: AudioChunk, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[VideoFrame]:
        from tth.adapters.avatar.stub import StubAvatarAdapter

        logger.warning("Simli unavailable — falling back to stub")
        stub = StubAvatarAdapter({})
        async for frame in stub.infer_stream(input, control, context):
            yield frame

    async def interrupt(self) -> None:
        self._buffer.reset()
        while not self._pending_frames.empty():
            try:
                self._pending_frames.get_nowait()
            except asyncio.QueueEmpty:
                break
        if self._client:
            try:
                await self._client.clearBuffer()
            except Exception:
                pass

    async def health(self) -> HealthStatus:
        if not self._is_healthy:
            return HealthStatus(healthy=False, detail="Simli not connected")
        return HealthStatus(healthy=True, detail="connected")

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_emotion=False,
            supports_identity=True,
        )

    async def close(self) -> None:
        if self._frame_consumer_task and not self._frame_consumer_task.done():
            self._frame_consumer_task.cancel()
            try:
                await self._frame_consumer_task
            except asyncio.CancelledError:
                pass

        if self._client:
            try:
                await self._client.stop()
            except Exception:
                pass
            self._client = None

        self._is_healthy = False
        logger.info("Simli adapter closed")
