# src/tth/adapters/avatar/simli.py
"""Simli real-time audio-to-avatar adapter."""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any, AsyncIterator

import httpx
import websockets

from tth.adapters.avatar.cloud_base import CloudAvatarAdapterBase
from tth.core.registry import register
from tth.core.types import AudioChunk, TurnControl, VideoFrame

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://api.simli.ai/compose/token"
_WS_BASE = "wss://api.simli.ai/compose/webrtc/p2p"


@register("simli")
class SimliAvatarAdapter(CloudAvatarAdapterBase):
    """Real-time audio-to-avatar adapter via Simli's API.

    Accepts PCM audio (resampled from OpenAI Realtime 24kHz to 16kHz) and returns
    lip-synced JPEG frames over a binary WebSocket.

    Pipeline:
        OpenAI Realtime API → 24kHz PCM
            → AudioChunkBuffer (resamples to 16kHz)
                → Simli WebSocket (binary audio)
                    → binary JPEG frames
                        → VideoFrame events

    Configuration:
        face_id: Simli face UUID (see docs.simli.com/api-reference/preset-faces)
        api_key_env: Environment variable for Simli API key (default: SIMLI_API_KEY)
        resolution: [width, height] of output frames
        fps: Target frames per second
        min_chunk_ms: Minimum audio buffer before sending
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.api_key_env = config.get("api_key_env", "SIMLI_API_KEY")
        self.face_id = config.get("face_id", "5514e24d-6086-46a3-ace4-6a7264e5cb7c")
        self._frame_index = 0

    async def load(self) -> None:
        if not os.environ.get(self.api_key_env):
            logger.warning(
                f"Missing {self.api_key_env} — Simli adapter will be inactive. "
                "Set this environment variable to enable Simli avatars."
            )
            return
        self._is_healthy = True
        logger.info(f"Simli adapter loaded (face_id={self.face_id})")

    async def _connect(self) -> None:
        """Fetch session token via HTTP, then open binary WebSocket."""
        api_key = os.environ.get(self.api_key_env, "")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _TOKEN_URL,
                headers={"x-simli-api-key": api_key},
                json={
                    "faceId": self.face_id,
                    "audioInputFormat": "pcm16",
                    "isJPG": True,
                    "handleSilence": True,
                    "maxSessionLength": 3600,
                    "maxIdleTime": 300,
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            session_token = resp.json()["session_token"]

        ws_url = f"{_WS_BASE}?session_token={session_token}"
        self._ws = await websockets.connect(ws_url)
        self._listener_task = asyncio.create_task(self._listen())
        self._is_healthy = True
        logger.info("Simli WebSocket connected")

    async def _listen(self) -> None:
        """Binary JPEG frame listener — overrides base class JSON loop."""
        try:
            if self._ws is None:
                return
            async for message in self._ws:
                if isinstance(message, bytes):
                    frame = VideoFrame(
                        data=message,
                        timestamp_ms=time.monotonic() * 1000,
                        frame_index=self._frame_index,
                        width=self.resolution[0],
                        height=self.resolution[1],
                        content_type="jpeg",
                    )
                    self._frame_index += 1
                    self._last_frame_time = time.monotonic()
                    try:
                        self._pending_frames.put_nowait(frame)
                    except asyncio.QueueFull:
                        logger.warning("Frame queue full, dropping frame")
        except websockets.ConnectionClosed as e:
            logger.warning(f"Simli WebSocket closed: code={e.code}, reason={e.reason}")
            self._is_healthy = False
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Simli listen loop ended: {e}")
            self._is_healthy = False

    async def _send_session_init(self, avatar_id: str) -> None:
        """No-op: Simli session is initialized via HTTP token exchange."""
        pass

    async def _send_audio_chunk(
        self, pcm_data: bytes, timestamp_ms: float, emotion: dict[str, Any]
    ) -> None:
        """Send raw PCM audio as binary WebSocket message."""
        if self._ws is not None:
            await self._ws.send(pcm_data)

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
        # 1. Ensure connection
        if self._ws is None or not self._ws.open:
            try:
                await self._connect()
            except Exception as e:
                logger.error(f"Failed to connect to Simli: {e}")
                async for frame in self._fallback_to_stub(input, control, context):
                    yield frame
                return

        # 2. Set session ID on first chunk
        if self._session_id is None:
            self._session_id = context.get("session_id", str(uuid.uuid4()))

        # 3. Buffer and resample audio (24kHz → 16kHz)
        ready, resampled = self._buffer.add(input)
        if not ready or resampled is None:
            return

        # 4. Send binary audio to Simli
        try:
            await self._send_audio_chunk(resampled, input.timestamp_ms, {})
        except Exception as e:
            logger.error(f"Failed to send audio to Simli: {e}")
            if await self._reconnect():
                try:
                    await self._send_audio_chunk(resampled, input.timestamp_ms, {})
                except Exception as e2:
                    logger.error(f"Simli retry failed: {e2}")
            return

        # 5. Yield any available frames (non-blocking)
        while not self._pending_frames.empty():
            try:
                yield self._pending_frames.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def close(self) -> None:
        """Close Simli WebSocket and reset state."""
        # Flush remaining audio before closing
        remaining = self._buffer.flush_remaining()
        if remaining and self._ws is not None and self._ws.open:
            try:
                await self._ws.send(remaining)
            except Exception:
                pass

        # Cancel listener task
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        # Close WebSocket directly (no JSON session_end — Simli uses binary protocol)
        if self._ws is not None and self._ws.open:
            await self._ws.close()
            self._ws = None
            self._is_healthy = False
            logger.info("Simli WebSocket closed")

        self._session_id = None
        self._frame_index = 0
