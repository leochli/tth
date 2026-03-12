# src/tth/adapters/avatar/did_cloud.py
"""D-ID API adapter for avatar generation.

D-ID provides text-to-video avatar generation. For real-time streaming,
we use their talks API with text input and retrieve the generated video.

API Docs: https://docs.d-id.com/reference/create-a-talk
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import time
from typing import Any, AsyncIterator

import httpx

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

_DID_API_URL = "https://api.d-id.com"


@register("did_cloud")
class DIDCloudAvatar(AdapterBase):
    """D-ID API adapter for avatar generation.

    Note: D-ID's standard API is text-to-video, not audio-to-video.
    For real-time audio-driven avatars, consider using D-ID's streaming API
    or LivePortrait on Modal.

    Configuration:
        api_key_env: Environment variable for D-ID API key (default: DID_API_KEY)
        source_url: URL to presenter image (jpg/png)
        presenter_id: D-ID presenter ID (optional)
        driver_id: D-ID driver/expression ID (optional)
        resolution: [width, height] (default: [512, 512])
        fps: Target frames per second (default: 25)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.api_key_env = config.get("api_key_env", "DID_API_KEY")
        # Use a JPG source URL, not MP4
        self.source_url = config.get(
            "source_url",
            "https://d-id-public-bucket.s3.eu-west-1.amazonaws.com/or-roman.jpg"
        )
        self.presenter_id = config.get("presenter_id")
        self.driver_id = config.get("driver_id")
        self.resolution = config.get("resolution", [512, 512])
        self.fps = config.get("fps", 25)

        # HTTP client
        self._client: httpx.AsyncClient | None = None

        # Pending text buffer for batch processing
        self._text_buffer: list[str] = []
        self._last_talk_id: str | None = None
        self._is_healthy = False

    def _get_api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")

    async def load(self) -> None:
        """Initialize HTTP client."""
        api_key = self._get_api_key()
        if not api_key:
            logger.warning(
                f"Missing {self.api_key_env} environment variable. "
                "Get your API key from https://d-id.com"
            )
            return

        # D-ID API key format: base64(email):api_key
        # Split into username (base64 email) and password (api key)
        if ":" in api_key:
            username, password = api_key.split(":", 1)
        else:
            username, password = api_key, ""

        self._client = httpx.AsyncClient(
            base_url=_DID_API_URL,
            auth=httpx.BasicAuth(username, password),
            headers={
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )
        self._is_healthy = True
        logger.info("D-ID adapter loaded")

    async def infer_stream(
        self, input: AudioChunk, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[VideoFrame]:
        """Generate avatar frames.

        Note: D-ID's standard API doesn't support real-time audio input.
        This adapter yields placeholder frames. For real-time avatars,
        use the stub adapter or deploy LivePortrait on Modal.
        """
        if not self._is_healthy or not self._client:
            logger.warning("D-ID adapter not configured, skipping")
            return

        # D-ID doesn't support real-time audio streaming
        # Yield a placeholder frame to indicate the adapter is working
        logger.warning(
            "D-ID adapter: Real-time audio-to-video not supported by standard API. "
            "Use stub_avatar for testing or deploy LivePortrait for production."
        )

        # Yield a single placeholder frame
        placeholder = self._generate_placeholder_frame(input.timestamp_ms)
        yield placeholder

    def _generate_placeholder_frame(self, timestamp_ms: float) -> VideoFrame:
        """Generate a placeholder frame indicating D-ID is configured but waiting."""
        import colorsys
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", tuple(self.resolution), color=(60, 60, 80))
        draw = ImageDraw.Draw(img)

        # Draw text
        text = "D-ID Ready"
        draw.text(
            (self.resolution[0] // 2, self.resolution[1] // 2),
            text,
            fill=(200, 200, 200),
            anchor="mm"
        )

        # Convert to JPEG
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)

        return VideoFrame(
            data=buffer.getvalue(),
            timestamp_ms=timestamp_ms,
            frame_index=0,
            width=self.resolution[0],
            height=self.resolution[1],
            content_type="jpeg",
        )

    async def create_talk_from_text(self, text: str) -> str | None:
        """Create a D-ID talk from text and return the video URL.

        This is useful for non-real-time avatar generation.
        """
        if not self._is_healthy or not self._client:
            return None

        payload = {
            "source_url": self.source_url,
            "script": {
                "type": "text",
                "input": text,
                "provider": {
                    "type": "microsoft",
                    "voice_id": "en-US-JennyNeural"
                }
            },
            "config": {
                "fluent": True,
                "pad_audio": 0.5,
            }
        }

        if self.presenter_id:
            payload["presenter_id"] = self.presenter_id

        try:
            response = await self._client.post("/talks", json=payload)

            if response.status_code == 401:
                logger.error("Invalid D-ID API key")
                return None

            if response.status_code != 201:
                logger.error(f"Failed to create talk: {response.status_code} - {response.text}")
                return None

            result = response.json()
            talk_id = result.get("id")
            self._last_talk_id = talk_id
            logger.info(f"Created D-ID talk: {talk_id}")

            # Poll for completion
            for _ in range(60):  # 30 second timeout
                await asyncio.sleep(0.5)

                status_response = await self._client.get(f"/talks/{talk_id}")
                if status_response.status_code != 200:
                    continue

                status_data = status_response.json()
                status = status_data.get("status")

                if status == "done":
                    return status_data.get("result_url")
                elif status == "error":
                    logger.error(f"D-ID talk failed: {status_data.get('error', {}).get('message')}")
                    return None

            logger.warning("D-ID talk timed out")
            return None

        except Exception as e:
            logger.error(f"D-ID API error: {e}")
            return None

    async def interrupt(self) -> None:
        """Handle interrupt."""
        self._text_buffer.clear()

    async def health(self) -> HealthStatus:
        """Check D-ID API health."""
        api_key = self._get_api_key()
        if not api_key:
            return HealthStatus(
                healthy=False,
                detail=f"Missing {self.api_key_env} environment variable",
            )

        if not self._is_healthy:
            return HealthStatus(
                healthy=False,
                detail="Not initialized",
            )

        return HealthStatus(
            healthy=True,
            detail="D-ID API configured (text-to-video mode)",
        )

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=False,  # D-ID standard API doesn't support real-time streaming
            supports_emotion=True,
            supports_identity=True,
        )

    async def close(self) -> None:
        """Clean up resources."""
        if self._client:
            await self._client.aclose()
            self._client = None
