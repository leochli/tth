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

        # Send user text and stream response (connection already established)
        session.transition("LLM_RUN")
        await self.realtime.send_user_text(text)

        async for event in self.realtime.stream_events():
            await output_q.put(event)

            if isinstance(event, TextDeltaEvent):
                full_response.append(event.token)

            elif isinstance(event, AudioChunkEvent):
                session.transition("TTS_RUN")
                session.transition("AVATAR_RUN")

                # Convert AudioChunkEvent to AudioChunk for avatar
                audio_chunk = AudioChunk(
                    data=event.data,
                    timestamp_ms=event.timestamp_ms,
                    duration_ms=event.duration_ms,
                    encoding=event.encoding,
                    sample_rate=event.sample_rate,
                )

                ctx = {**session.context, "frame_counter": frame_counter}
                async for frame in self.avatar.infer_stream(audio_chunk, resolved, ctx):
                    drift = session.drift_controller.update(
                        event.timestamp_ms, frame.timestamp_ms
                    )
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

        # Track assistant response in history
        if full_response:
            session.append_history("assistant", "".join(full_response))

        session.transition("TURN_COMPLETE")
        # TurnCompleteEvent is yielded by stream_events(), so we don't send it again
