# src/tth/adapters/realtime/openai_realtime.py
from __future__ import annotations
import asyncio
import base64
import json
import logging
import time
from typing import Any, AsyncIterator
import websockets
from tth.adapters.base import AdapterBase
from tth.core.config import settings
from tth.core.registry import register
from tth.core.types import (
    AdapterCapabilities,
    AudioChunk,
    AudioChunkEvent,
    HealthStatus,
    TextDeltaEvent,
    TurnCompleteEvent,
    TurnControl,
    VideoFrame,
)

logger = logging.getLogger(__name__)


@register("openai_realtime")
class OpenAIRealtimeAdapter(AdapterBase):
    """Combined LLM+TTS via OpenAI Realtime WebSocket API.

    IMPORTANT: WebSocket connection is session-scoped, not turn-scoped.
    Call connect() once at session start, then reuse for multiple turns.

    This adapter streams audio directly from the Realtime API without
    sentence buffering, significantly reducing latency.
    """

    _WS_URL = "wss://api.openai.com/v1/realtime"
    _MODEL = "gpt-4o-realtime-preview-2024-12-17"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config or {})
        self._ws: Any = None
        self._event_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._listener_task: asyncio.Task[None] | None = None
        self._is_connected = False
        self._connect_time: float = 0

    async def connect(self, system_instructions: str, voice: str = "alloy") -> None:
        """Establish WebSocket connection ONCE at session start."""
        if self._is_connected:
            logger.warning("Realtime adapter already connected, skipping reconnect")
            return

        url = f"{self._WS_URL}?model={self._MODEL}"

        try:
            self._ws = await websockets.connect(
                url,
                additional_headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            )
            self._connect_time = time.monotonic()

            # Configure session
            session_update = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": system_instructions,
                    "voice": voice,
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {"model": "whisper-1"},
                    "turn_detection": None,  # Server VAD disabled; we use client text
                    "tools": [],
                    "tool_choice": "auto",
                },
            }
            await self._ws.send(json.dumps(session_update))

            # Wait for session.created event
            response = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
            event = json.loads(response)
            if event.get("type") != "session.created":
                raise RuntimeError(f"Expected session.created, got {event.get('type')}")

            # Start message listener task
            self._listener_task = asyncio.create_task(self._listen())
            self._is_connected = True
            logger.info(f"Realtime adapter connected with voice={voice}")

        except Exception as e:
            logger.error(f"Failed to connect to Realtime API: {e}")
            if self._ws:
                await self._ws.close()
                self._ws = None
            raise

    async def _listen(self) -> None:
        """Background task: listen for WebSocket messages and queue events."""
        try:
            if self._ws is None:
                return
            async for message in self._ws:
                event = json.loads(message)
                await self._handle_server_event(event)
        except websockets.ConnectionClosed as e:
            logger.warning(f"Realtime WebSocket connection closed: code={e.code}")
            self._is_connected = False
        except asyncio.CancelledError:
            logger.debug("Realtime listener task cancelled")
            raise
        except Exception as e:
            logger.error(f"Realtime listener error: {e}")
            self._is_connected = False

    async def _handle_server_event(self, event: dict[str, Any]) -> None:
        """Convert Realtime API events to internal events."""
        event_type = event.get("type")

        if event_type == "response.output_audio.delta":
            # Audio output chunk - base64 encoded PCM
            audio_b64 = event.get("delta", "")
            if audio_b64:
                audio_data = base64.b64decode(audio_b64)
                duration_ms = len(audio_data) / 2 / 24000 * 1000  # 16-bit, 24kHz
                await self._event_queue.put(
                    AudioChunkEvent(
                        data=audio_data,
                        timestamp_ms=time.monotonic() * 1000,
                        duration_ms=duration_ms,
                        encoding="pcm",
                        sample_rate=24000,
                    )
                )

        elif event_type == "response.output_audio_transcript.delta":
            # Text transcript delta
            text_delta = event.get("delta", "")
            if text_delta:
                await self._event_queue.put(TextDeltaEvent(token=text_delta))

        elif event_type == "response.done":
            # Response complete
            response = event.get("response", {})
            response_id = response.get("id", "unknown")
            await self._event_queue.put(TurnCompleteEvent(turn_id=response_id))

        elif event_type == "error":
            error = event.get("error", {})
            logger.error(f"Realtime API error: {error}")

        elif event_type == "session.updated":
            logger.debug("Realtime session updated")

        else:
            logger.debug(f"Realtime event: {event_type}")

    async def send_user_text(self, text: str) -> None:
        """Send user message and trigger response."""
        if not self._is_connected or self._ws is None:
            raise RuntimeError("Realtime adapter not connected")

        # Add user message to conversation
        item = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            },
        }
        await self._ws.send(json.dumps(item))

        # Trigger response generation
        await self._ws.send(json.dumps({"type": "response.create"}))
        logger.debug(f"Sent user text and triggered response: {text[:50]}...")

    async def cancel_response(self) -> None:
        """Cancel current response (for interrupt handling)."""
        if self._is_connected and self._ws is not None:
            await self._ws.send(json.dumps({"type": "response.cancel"}))
            logger.info("Sent response.cancel to Realtime API")
            # Clear any pending events from queue
            while not self._event_queue.empty():
                try:
                    self._event_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

    async def stream_events(self) -> AsyncIterator[AudioChunkEvent | TextDeltaEvent | TurnCompleteEvent]:
        """Yield events from the response queue until TurnCompleteEvent."""
        while True:
            event = await self._event_queue.get()
            yield event
            if isinstance(event, TurnCompleteEvent):
                break

    async def close(self) -> None:
        """Close WebSocket connection."""
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None

        if self._ws is not None:
            await self._ws.close()
            self._ws = None

        self._is_connected = False
        logger.info("Realtime adapter closed")

    # --- AdapterBase required methods ---

    async def infer_stream(
        self, input: str | bytes | AudioChunk, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[str | AudioChunk | VideoFrame]:
        """Not used for Realtime adapter - use send_user_text + stream_events instead."""
        raise NotImplementedError("Use send_user_text() + stream_events() for Realtime API")
        yield ""  # pragma: no cover - makes this an async generator

    async def health(self) -> HealthStatus:
        """Check if WebSocket is connected."""
        latency_ms = None
        if self._is_connected and self._connect_time > 0:
            latency_ms = (time.monotonic() - self._connect_time) * 1000

        return HealthStatus(
            healthy=self._is_connected,
            latency_ms=latency_ms,
            detail="connected" if self._is_connected else "disconnected",
        )

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_emotion=True,
            supported_emotions=["neutral", "happy", "sad", "angry", "surprised"],
        )
