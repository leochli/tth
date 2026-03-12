# src/tth/adapters/avatar/buffer.py
"""Audio chunk buffering for cloud avatar transmission."""
from __future__ import annotations

import logging

from tth.adapters.avatar.audio_utils import AudioResampler
from tth.core.types import AudioChunk

logger = logging.getLogger(__name__)


class AudioChunkBuffer:
    """Buffers and resamples audio chunks for cloud transmission.

    Accumulates audio chunks until minimum duration is reached, then resamples
    from 24kHz (Realtime API output) to 16kHz (LivePortrait input).

    Configurable chunk size - initial testing suggests 200-500ms for better lip sync.
    """

    # Default settings
    MIN_CHUNK_MS = 200  # Configurable - test empirically with LivePortrait
    SOURCE_RATE = 24000  # Realtime API output (PCM)
    TARGET_RATE = 16000  # LivePortrait input

    def __init__(self, min_chunk_ms: int = MIN_CHUNK_MS):
        self.min_chunk_ms = min_chunk_ms
        self.accumulator = bytearray()
        self.resampler = AudioResampler(self.SOURCE_RATE, self.TARGET_RATE)
        self.accumulated_ms = 0.0

    def add(self, chunk: AudioChunk) -> tuple[bool, bytes | None]:
        """Add chunk, return (ready_to_send, resampled_data).

        Args:
            chunk: AudioChunk from the pipeline (PCM, 24kHz)

        Returns:
            Tuple of (ready_to_send, resampled_data):
            - ready_to_send: True if enough audio accumulated
            - resampled_data: Resampled 16kHz PCM bytes, or None if not ready
        """
        # 1. Validate encoding is PCM (Realtime API outputs PCM, not MP3)
        if chunk.encoding != "pcm":
            raise ValueError(
                f"Expected PCM encoding, got {chunk.encoding}. "
                "AudioChunkBuffer requires PCM input from Realtime API."
            )

        # 2. Accumulate raw PCM data
        self.accumulator.extend(chunk.data)
        self.accumulated_ms += chunk.duration_ms

        # 3. Check if we have enough audio
        if self.accumulated_ms >= self.min_chunk_ms:
            return True, self._flush_resampled()
        return False, None

    def _flush_resampled(self) -> bytes:
        """Resample accumulated audio and reset buffer.

        Returns:
            Resampled 16kHz PCM bytes
        """
        raw = bytes(self.accumulator)
        resampled = self.resampler.resample(raw)
        logger.debug(
            f"Resampled {len(raw)} bytes ({self.accumulated_ms:.0f}ms) "
            f"→ {len(resampled)} bytes"
        )
        self.accumulator.clear()
        self.accumulated_ms = 0.0
        return resampled

    def flush_remaining(self) -> bytes | None:
        """Get any remaining buffered audio.

        Call at end of turn to ensure all audio is processed.

        Returns:
            Resampled 16kHz PCM bytes, or None if buffer was empty
        """
        if len(self.accumulator) > 0:
            logger.debug(f"Flushing remaining {self.accumulated_ms:.0f}ms of audio")
            return self._flush_resampled()
        return None

    def reset(self) -> None:
        """Clear buffer (for interrupt handling)."""
        self.accumulator.clear()
        self.accumulated_ms = 0.0
        logger.debug("Audio buffer reset")

    @property
    def buffered_ms(self) -> float:
        """Current buffered audio duration in milliseconds."""
        return self.accumulated_ms
