# src/tth/adapters/avatar/cloud_base.py
"""Base class for cloud-based avatar services."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any, AsyncIterator

import websockets
from websockets.connection import State as WsState

from tth.adapters.avatar.buffer import AudioChunkBuffer
from tth.adapters.base import AdapterBase
from tth.core.types import (
    AdapterCapabilities,
    AudioChunk,
    HealthStatus,
    TurnControl,
    VideoFrame,
)

logger = logging.getLogger(__name__)


class CloudAvatarAdapterBase(AdapterBase):
    """Base class for cloud-based avatar services.

    Handles WebSocket connection management, reconnection, health checks,
    and audio buffering/resampling.

    Subclasses must implement:
        - _get_auth_headers(): Return headers for authentication
        - _send_session_init(): Initialize session with avatar selection
        - _send_audio_chunk(): Send audio to cloud service
        - _parse_video_frame(): Parse cloud message into VideoFrame

    Configuration:
        endpoint_url: WebSocket URL of the cloud service
        api_key_env: Environment variable name for API key
        timeout_ms: Connection timeout in milliseconds
        resolution: [width, height] of output frames
        fps: Frames per second
        default_avatar: Default avatar ID
        min_chunk_ms: Minimum audio chunk duration before sending
    """

    MAX_RETRIES = 3
    RETRY_DELAY_BASE_MS = 100
    WS_TIMEOUT_S = 30

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.endpoint_url = config.get("endpoint_url", "")
        self.timeout_ms = config.get("timeout_ms", 5000)
        self.resolution = config.get("resolution", [512, 512])
        self.fps = config.get("fps", 25)
        self.default_avatar = config.get("default_avatar", "default_avatar_01")

        # WebSocket state
        self._ws: Any = None
        self._session_id: str | None = None
        self._current_avatar_id: str | None = None

        # Audio buffer
        self._buffer = AudioChunkBuffer(
            min_chunk_ms=config.get("min_chunk_ms", 200)
        )

        # Frame queue for async reception
        self._pending_frames: asyncio.Queue[VideoFrame] = asyncio.Queue(maxsize=64)

        # Background listener task
        self._listener_task: asyncio.Task[None] | None = None

        # Health tracking
        self._is_healthy = False
        self._last_frame_time: float = 0
        self._connection_attempts = 0

    def _get_auth_headers(self) -> dict[str, str]:
        """Return headers for authentication. Override in subclass."""
        return {}

    async def _connect(self) -> None:
        """Establish WebSocket connection with retries."""
        for attempt in range(self.MAX_RETRIES):
            try:
                self._ws = await asyncio.wait_for(
                    websockets.connect(
                        self.endpoint_url,
                        additional_headers=self._get_auth_headers(),
                        ping_interval=20,
                        ping_timeout=10,
                    ),
                    timeout=self.WS_TIMEOUT_S,
                )
                self._listener_task = asyncio.create_task(self._listen())
                self._is_healthy = True
                self._connection_attempts = 0
                logger.info(f"Connected to cloud avatar service: {self.endpoint_url}")
                return
            except Exception as e:
                self._connection_attempts += 1
                logger.warning(
                    f"Connection attempt {attempt + 1}/{self.MAX_RETRIES} failed: {e}"
                )
                if attempt == self.MAX_RETRIES - 1:
                    self._is_healthy = False
                    raise ConnectionError(
                        f"Failed to connect to cloud avatar after {self.MAX_RETRIES} "
                        f"attempts: {e}"
                    )
                delay = self.RETRY_DELAY_BASE_MS * (2**attempt) / 1000
                await asyncio.sleep(delay)

    async def _reconnect(self) -> bool:
        """Attempt to reconnect, return success.

        Tries to re-establish connection and resume session.
        """
        try:
            # Cancel old listener task
            if self._listener_task and not self._listener_task.done():
                self._listener_task.cancel()
                try:
                    await self._listener_task
                except asyncio.CancelledError:
                    pass

            await self._connect()

            # Re-initialize session with current avatar
            if self._session_id and self._current_avatar_id:
                await self._send_session_init(self._current_avatar_id)

            return True
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")
            self._is_healthy = False
            return False

    async def _listen(self) -> None:
        """Background task: receive messages from cloud."""
        try:
            if self._ws is None:
                return

            async for message in self._ws:
                try:
                    msg: dict[str, Any] = json.loads(message)
                    msg_type = msg.get("type")

                    if msg_type == "video_frame":
                        frame = self._parse_video_frame(msg)
                        # Drop frames if queue is full (backpressure)
                        try:
                            self._pending_frames.put_nowait(frame)
                        except asyncio.QueueFull:
                            logger.warning("Frame queue full, dropping frame")
                        self._last_frame_time = time.monotonic()

                    elif msg_type == "session_ready":
                        logger.info(
                            f"Cloud session ready: session_id={msg.get('session_id')}, "
                            f"avatar_id={msg.get('avatar_id')}"
                        )

                    elif msg_type == "error":
                        error_code = msg.get("code", "unknown")
                        error_msg = msg.get("message", "Unknown error")
                        logger.error(f"Cloud avatar error: [{error_code}] {error_msg}")

                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse cloud message: {e}")

        except websockets.ConnectionClosed as e:
            logger.warning(f"Cloud avatar WebSocket closed: code={e.code}, reason={e.reason}")
            self._is_healthy = False
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Listener task error: {e}")
            self._is_healthy = False

    def _parse_video_frame(self, msg: dict[str, Any]) -> VideoFrame:
        """Parse cloud message into VideoFrame. Override in subclass."""
        return VideoFrame(
            data=base64.b64decode(msg["data"]),
            timestamp_ms=msg["timestamp_ms"],
            frame_index=msg["frame_index"],
            width=self.resolution[0],
            height=self.resolution[1],
            content_type="jpeg",
        )

    async def _send_session_init(self, avatar_id: str) -> None:
        """Initialize session with avatar selection. Override in subclass."""
        if self._ws is None:
            return

        msg: dict[str, Any] = {
            "type": "session_init",
            "session_id": self._session_id,
            "avatar_id": avatar_id,
            "emotion_config": {},
        }
        await self._ws.send(json.dumps(msg))
        self._current_avatar_id = avatar_id
        logger.debug(f"Sent session_init for avatar: {avatar_id}")

    async def _send_audio_chunk(
        self, pcm_data: bytes, timestamp_ms: float, emotion: dict[str, Any]
    ) -> None:
        """Send audio chunk to cloud. Override in subclass."""
        if self._ws is None:
            return

        msg: dict[str, Any] = {
            "type": "audio_chunk",
            "session_id": self._session_id,
            "data": base64.b64encode(pcm_data).decode(),
            "timestamp_ms": timestamp_ms,
            "emotion": emotion,
        }
        await self._ws.send(json.dumps(msg))

    async def _fallback_to_stub(
        self, input: AudioChunk, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[VideoFrame]:
        """Generate stub frames when cloud unavailable."""
        from tth.adapters.avatar.stub import StubAvatarAdapter

        logger.warning("Falling back to stub avatar adapter")
        stub = StubAvatarAdapter({})
        async for frame in stub.infer_stream(input, control, context):
            yield frame

    async def interrupt(self) -> None:
        """Handle interrupt - clear buffers and reset state."""
        logger.info("Avatar adapter interrupted")

        # Clear audio buffer
        self._buffer.reset()

        # Clear pending frames
        while not self._pending_frames.empty():
            try:
                self._pending_frames.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Send interrupt to cloud if connected
        if self._ws and self._ws.state is WsState.OPEN and self._session_id:
            try:
                await self._ws.send(json.dumps({
                    "type": "interrupt",
                    "session_id": self._session_id,
                }))
            except Exception as e:
                logger.warning(f"Failed to send interrupt to cloud: {e}")

    async def health(self) -> HealthStatus:
        """Check adapter health."""
        if not self._is_healthy:
            return HealthStatus(
                healthy=False,
                detail="WebSocket not connected",
            )

        # Check for stale connection (no frames for 10s)
        if self._last_frame_time > 0:
            elapsed = (time.monotonic() - self._last_frame_time) * 1000
            if elapsed > 10000:
                return HealthStatus(
                    healthy=False,
                    latency_ms=elapsed,
                    detail=f"No frames received for {elapsed:.0f}ms",
                )

        return HealthStatus(
            healthy=True,
            detail="connected",
        )

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_emotion=True,
            supports_identity=True,
        )

    async def close(self) -> None:
        """Close WebSocket connection."""
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        if self._ws and self._ws.state is WsState.OPEN:
            # Send session end if we have an active session
            if self._session_id:
                try:
                    await self._ws.send(json.dumps({
                        "type": "session_end",
                        "session_id": self._session_id,
                    }))
                except Exception:
                    pass

            await self._ws.close()
            self._ws = None
            self._is_healthy = False
            logger.info("Cloud avatar WebSocket closed")
