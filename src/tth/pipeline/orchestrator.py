# src/tth/pipeline/orchestrator.py
from __future__ import annotations
import asyncio
import uuid
from typing import Any
from tth.adapters.base import AdapterBase
from tth.control.mapper import resolve as resolve_controls
from tth.core.types import (
    AudioChunk,
    AudioChunkEvent,
    TextDeltaEvent,
    TurnCompleteEvent,
    TurnControl,
    VideoFrameEvent,
)
from tth.pipeline.session import Session

_SENTENCE_ENDS = frozenset(".!?\n")
_MIN_SENTENCE_LEN = 10  # chars — avoid flushing on abbreviations like "Dr."


class Orchestrator:
    def __init__(
        self,
        llm: AdapterBase,
        tts: AdapterBase,
        avatar: AdapterBase,
    ) -> None:
        self.llm = llm
        self.tts = tts
        self.avatar = avatar

    async def run_turn(
        self,
        session: Session,
        text: str,
        control: TurnControl,
        output_q: asyncio.Queue,
    ) -> None:
        turn_id = str(uuid.uuid4())
        resolved = resolve_controls(control, session.persona_defaults)

        # Track user message in history for multi-turn context
        session.append_history("user", text)

        # Bounded queue: LLM can produce at most 2 sentences ahead of TTS
        sentence_q: asyncio.Queue[str | None] = asyncio.Queue(maxsize=2)
        frame_counter = 0
        full_response: list[str] = []

        # ── Producer: LLM → sentence buffer → sentence_q ─────────────────────
        async def llm_producer() -> None:
            session.transition("LLM_RUN")
            buf = ""
            async for token in self.llm.infer_stream(text, resolved, session.context):
                await output_q.put(TextDeltaEvent(token=token))
                buf += token
                full_response.append(token)
                # Flush on sentence boundary once buffer is long enough
                if token[-1] in _SENTENCE_ENDS and len(buf.strip()) >= _MIN_SENTENCE_LEN:
                    await sentence_q.put(buf.strip())
                    buf = ""
            if buf.strip():  # flush any trailing text
                await sentence_q.put(buf.strip())
            await sentence_q.put(None)  # sentinel: producer done

        # ── Consumer: sentence_q → TTS → Avatar ──────────────────────────────
        async def tts_avatar_consumer() -> None:
            nonlocal frame_counter
            session.transition("TTS_RUN")
            while True:
                sentence = await sentence_q.get()
                if sentence is None:
                    break  # done
                async for chunk in self.tts.infer_stream(sentence, resolved, session.context):
                    await output_q.put(
                        AudioChunkEvent(
                            data=chunk.data,
                            timestamp_ms=chunk.timestamp_ms,
                            duration_ms=chunk.duration_ms,
                            encoding=chunk.encoding,
                            sample_rate=chunk.sample_rate,
                        )
                    )
                    session.transition("AVATAR_RUN")
                    ctx = {**session.context, "frame_counter": frame_counter}
                    async for frame in self.avatar.infer_stream(chunk, resolved, ctx):
                        drift = session.drift_controller.update(
                            chunk.timestamp_ms, frame.timestamp_ms
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

        # Run LLM and TTS+Avatar in parallel — TTS starts as soon as first sentence ready
        await asyncio.gather(llm_producer(), tts_avatar_consumer())

        # Track assistant response in history
        if full_response:
            session.append_history("assistant", "".join(full_response))

        session.transition("TURN_COMPLETE")
        await output_q.put(TurnCompleteEvent(turn_id=turn_id))
