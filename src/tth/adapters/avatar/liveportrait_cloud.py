# src/tth/adapters/avatar/liveportrait_cloud.py
"""LivePortrait cloud adapter for real-time avatar generation."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, AsyncIterator

from tth.adapters.avatar.cloud_base import CloudAvatarAdapterBase
from tth.core.registry import register
from tth.core.types import AudioChunk, TurnControl, VideoFrame

logger = logging.getLogger(__name__)


def map_emotion_to_avatar(
    emotion: Any, character: Any
) -> dict[str, Any]:
    """Map TTH controls to LivePortrait parameters.

    Args:
        emotion: EmotionControl with label, intensity, valence, arousal
        character: CharacterControl with persona_id, motion_gain, etc.

    Returns:
        Dict with LivePortrait-specific parameters
    """
    # Map emotion labels to expression weights
    emotion_weights = {
        "neutral": {"neutral": 1.0},
        "happy": {"happy": 1.0, "smile": 0.8},
        "sad": {"sad": 1.0},
        "angry": {"angry": 1.0},
        "surprised": {"surprised": 1.0},
        "fearful": {"fearful": 1.0},
        "disgusted": {"disgusted": 1.0},
    }

    label = emotion.label.value if hasattr(emotion.label, "value") else str(emotion.label)
    base_weights = emotion_weights.get(label, {"neutral": 1.0})

    # Apply intensity to weights
    expression_weight = {
        k: v * emotion.intensity for k, v in base_weights.items()
    }

    return {
        "expression_weight": expression_weight,
        "intensity": emotion.intensity,
        "head_motion_scale": character.motion_gain,
    }


@register("liveportrait_cloud")
class LivePortraitCloudAdapter(CloudAvatarAdapterBase):
    """Cloud-hosted LivePortrait via Modal or RunPod.

    Communication: WebSocket for streaming
    Input: AudioChunk (PCM audio, 24kHz → resampled to 16kHz)
    Output: VideoFrame (JPEG frames)

    Configuration:
        endpoint_url: WebSocket URL of the Modal deployment
        api_key_env: Environment variable for API key (default: MODAL_API_KEY)
        default_avatar: Default avatar ID to use
        resolution: [width, height] of output frames
        fps: Target frames per second
        min_chunk_ms: Minimum audio chunk size before sending
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.api_key_env = config.get("api_key_env", "MODAL_API_KEY")
        self._avatar_cache: dict[str, dict[str, Any]] = {}  # avatar_id -> metadata

    def _get_auth_headers(self) -> dict[str, str]:
        """Return headers for Modal authentication."""
        api_key = os.environ.get(self.api_key_env, "")
        if api_key:
            return {"Authorization": f"Bearer {api_key}"}
        return {}

    async def load(self) -> None:
        """Validate endpoint and preload avatar metadata."""
        if not self.endpoint_url:
            logger.warning(
                "No endpoint_url configured for LivePortrait cloud adapter. "
                "Set components.avatar.liveportrait_cloud.endpoint_url in config."
            )
            return

        logger.info(
            f"LivePortraitCloudAdapter loaded (endpoint={self.endpoint_url}, "
            f"default_avatar={self.default_avatar})"
        )

    async def infer_stream(
        self, input: AudioChunk, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[VideoFrame]:
        """Stream audio to cloud, yield video frames.

        Args:
            input: AudioChunk (PCM, 24kHz)
            control: TurnControl with emotion/character settings
            context: Pipeline context with session_id, frame_counter

        Yields:
            VideoFrame objects from the cloud service
        """
        # 1. Ensure connection
        if self._ws is None or not self._ws.open:
            try:
                await self._connect()
            except ConnectionError as e:
                logger.error(f"Failed to connect to cloud: {e}")
                # Fall back to stub adapter
                async for frame in self._fallback_to_stub(input, control, context):
                    yield frame
                return

        # 2. Initialize session on first chunk
        if self._session_id is None:
            self._session_id = context.get("session_id", str(uuid.uuid4()))
            avatar_id = control.character.persona_id or self.default_avatar
            try:
                await self._send_session_init(avatar_id)
            except Exception as e:
                logger.error(f"Failed to initialize session: {e}")
                async for frame in self._fallback_to_stub(input, control, context):
                    yield frame
                return

        # 3. Buffer and resample audio
        ready, resampled = self._buffer.add(input)
        if not ready or resampled is None:
            return  # Wait for more audio

        # 4. Send audio chunk to cloud
        emotion_params = map_emotion_to_avatar(control.emotion, control.character)
        try:
            await self._send_audio_chunk(resampled, input.timestamp_ms, emotion_params)
        except Exception as e:
            logger.error(f"Failed to send audio chunk: {e}")
            # Try to reconnect
            if await self._reconnect():
                # Retry once after reconnect
                try:
                    await self._send_audio_chunk(
                        resampled, input.timestamp_ms, emotion_params
                    )
                except Exception as e2:
                    logger.error(f"Retry failed: {e2}")
            return

        # 5. Yield any available frames (non-blocking)
        while not self._pending_frames.empty():
            try:
                yield self._pending_frames.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def flush(self, control: TurnControl, context: dict[str, Any]) -> AsyncIterator[VideoFrame]:
        """Flush remaining buffered audio and yield final frames.

        Call at end of turn to ensure all audio is processed.
        """
        remaining = self._buffer.flush_remaining()
        if remaining:
            emotion_params = map_emotion_to_avatar(control.emotion, control.character)
            try:
                await self._send_audio_chunk(remaining, 0.0, emotion_params)
            except Exception as e:
                logger.error(f"Failed to flush audio: {e}")

        # Yield any remaining frames
        while not self._pending_frames.empty():
            try:
                yield self._pending_frames.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def close(self) -> None:
        """Close connection and clear state."""
        # Flush any remaining audio
        remaining = self._buffer.flush_remaining()
        if remaining and self._ws and self._ws.open:
            logger.debug(f"Flushing {len(remaining)} bytes on close")

        await super().close()
        self._session_id = None
        self._current_avatar_id = None
