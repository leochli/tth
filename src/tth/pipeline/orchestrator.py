# src/tth/pipeline/orchestrator.py
from __future__ import annotations
import asyncio
import logging
from typing import Any
from tth.adapters.base import AdapterBase
from tth.adapters.realtime.openai_realtime import OpenAIRealtimeAdapter
from tth.control.mapper import resolve as resolve_controls
from tth.core.types import (
    AudioChunk,
    AudioChunkEvent,
    TextDeltaEvent,
    TurnControl,
    VideoFrameEvent,
)
from tth.pipeline.session import Session

logger = logging.getLogger(__name__)


class Orchestrator:
    """Simplified orchestrator using OpenAI Realtime API.

    IMPORTANT: realtime.connect() must be called ONCE at session start,
    not in run_turn(). The adapter maintains a persistent WebSocket.

    The Realtime API combines LLM + TTS in a single WebSocket connection,
    streaming audio directly without sentence buffering. This significantly
    reduces latency compared to the separate LLM → TTS pipeline.
    """

    def __init__(
        self,
        realtime: OpenAIRealtimeAdapter,
        avatar: AdapterBase,
    ) -> None:
        self.realtime = realtime
        self.avatar = avatar

    async def start_session(self, session: Session, output_q: asyncio.Queue[Any]) -> None:
        """Start the persistent avatar relay task for a WebSocket session.

        For push-model adapters (e.g. Simli), the relay runs continuously for
        the lifetime of the WebSocket connection — covering active turns AND
        the idle periods between turns (Simli's handleSilence=True keeps the
        avatar animating throughout). Call session.cancel_relay() on disconnect.

        For pull-model adapters (stub/mock), relay is managed per-turn inside
        run_turn() and this method is a no-op.
        """
        if not self.avatar.capabilities().has_streaming_frames:
            return

        frame_counter = 0
        stop_never = asyncio.Event()  # intentionally never set

        async def _persistent_relay() -> None:
            nonlocal frame_counter
            try:
                async for frame in self.avatar.relay_frames(stop_never):
                    drift = session.drift_controller.update(
                        session.last_audio_ts[0], frame.timestamp_ms
                    )
                    event = VideoFrameEvent(
                        data=frame.data,
                        timestamp_ms=frame.timestamp_ms,
                        frame_index=frame_counter,
                        width=frame.width,
                        height=frame.height,
                        content_type=frame.content_type,
                        drift_ms=drift,
                    )
                    # Non-blocking put: drop the frame rather than blocking audio delivery.
                    # Video frames are ephemeral (a dropped frame is acceptable); blocking
                    # here would starve AudioChunkEvents that run_turn puts into the same
                    # queue, causing the client to hear no audio when the queue is full.
                    try:
                        output_q.put_nowait(event)
                    except asyncio.QueueFull:
                        pass  # drop frame; send_loop will catch up
                    frame_counter += 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Avatar persistent relay died: {e}")

        session.relay_task = asyncio.create_task(_persistent_relay())

    async def run_turn(
        self,
        session: Session,
        text: str,
        control: TurnControl,
        output_q: asyncio.Queue[Any],
    ) -> None:
        resolved = resolve_controls(control, session.persona_defaults)

        # Track user message in history for multi-turn context
        session.append_history("user", text)

        # Log warning if CharacterControl params are non-default
        # (Realtime API doesn't support these)
        cc = resolved.character
        if (
            cc.speech_rate != 1.0
            or cc.pitch_shift != 0.0
            or cc.expressivity != 0.6
            or cc.motion_gain != 1.0
        ):
            logger.warning(
                "CharacterControl params not supported by Realtime API: "
                f"speech_rate={cc.speech_rate}, pitch_shift={cc.pitch_shift}, "
                f"expressivity={cc.expressivity}, motion_gain={cc.motion_gain}"
            )

        frame_counter = 0
        full_response: list[str] = []

        is_push = self.avatar.capabilities().has_streaming_frames
        avatar_q: asyncio.Queue[tuple[AudioChunk, float] | None] = asyncio.Queue(maxsize=32)

        if is_push:
            async def _feed_audio() -> None:
                while True:
                    item = await avatar_q.get()
                    if item is None:
                        break
                    audio_chunk, audio_ts = item
                    session.last_audio_ts[0] = audio_ts
                    ctx = {
                        **session.context,
                        "session_id": session.id,
                    }
                    async for _ in self.avatar.infer_stream(audio_chunk, resolved, ctx):
                        pass  # yields nothing for push model

            feed_task = asyncio.create_task(_feed_audio())

        else:
            # Pull model: existing sequential worker (stub/mock adapters)
            async def _avatar_worker() -> None:
                nonlocal frame_counter
                while True:
                    item = await avatar_q.get()
                    if item is None:
                        break
                    audio_chunk, audio_ts = item
                    ctx = {
                        **session.context,
                        "frame_counter": frame_counter,
                        "session_id": session.id,
                    }
                    async for frame in self.avatar.infer_stream(audio_chunk, resolved, ctx):
                        drift = session.drift_controller.update(audio_ts, frame.timestamp_ms)
                        await output_q.put(
                            VideoFrameEvent(
                                data=frame.data,
                                timestamp_ms=frame.timestamp_ms,
                                frame_index=frame.frame_index,
                                width=frame.width,
                                height=frame.height,
                                content_type=frame.content_type,
                                drift_ms=drift,
                            )
                        )
                        frame_counter += 1

            avatar_task = asyncio.create_task(_avatar_worker())

        # Send user text and stream response (connection already established)
        session.transition("LLM_RUN")
        await self.realtime.send_user_text(text)

        try:
            async for event in self.realtime.stream_events():
                await output_q.put(event)

                if isinstance(event, TextDeltaEvent):
                    full_response.append(event.token)

                elif isinstance(event, AudioChunkEvent):
                    session.transition("TTS_RUN")
                    session.transition("AVATAR_RUN")

                    audio_chunk = AudioChunk(
                        data=event.data,
                        timestamp_ms=event.timestamp_ms,
                        duration_ms=event.duration_ms,
                        encoding=event.encoding,
                        sample_rate=event.sample_rate,
                    )
                    await avatar_q.put((audio_chunk, event.timestamp_ms))

        except asyncio.CancelledError:
            if is_push:
                feed_task.cancel()
                try:
                    await feed_task
                except asyncio.CancelledError:
                    pass
            else:
                avatar_task.cancel()
                try:
                    await avatar_task
                except asyncio.CancelledError:
                    pass
            raise

        # Shutdown audio pipeline; relay continues independently for idle animation
        await avatar_q.put(None)
        if is_push:
            try:
                await feed_task  # ensure all audio sent to Simli
            except Exception as e:
                logger.error(f"Avatar feed error: {e}")
        else:
            try:
                await avatar_task
            except Exception as e:
                logger.error(f"Avatar pipeline error: {e}")

        # Track assistant response in history
        if full_response:
            session.append_history("assistant", "".join(full_response))

        session.transition("TURN_COMPLETE")
        # TurnCompleteEvent is yielded by stream_events(), so we don't send it again
