# src/tth/adapters/avatar/did_streaming.py
"""D-ID Realtime API adapter for streaming avatar generation.

D-ID's Realtime API provides WebRTC-based streaming for real-time
audio-driven avatar generation via the Agents SDK.

API Documentation: https://docs.d-id.com/reference/agents-streams

IMPORTANT: D-ID's real-time streaming uses WebRTC, not REST polling.
This adapter creates an Agent and manages streams for real-time video.

## Hybrid Architecture

Server manages:
- Creating D-ID agent and stream sessions
- Sending text to D-ID chat API
- Providing WebRTC connection info to browser client

Browser handles:
- WebRTC connection to D-ID
"""
from __future__ import annotations

import base64
import json
import logging
import os
import urllib.parse
from dataclasses import dataclass
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


@dataclass
class DIDConnectionInfo:
    """WebRTC connection info for browser client."""
    agent_id: str
    stream_id: str
    session_id: str  # For chat
    webrtc_session_id: str = ""  # Stream session_id (for SDP/ICE handshake)
    ice_servers: list[dict] | None = None
    offer: dict | None = None  # SDP offer from D-ID


@register("did_streaming")
class DIDStreamingAvatar(AdapterBase):
    """D-ID Realtime API adapter for streaming avatar generation.

    Uses D-ID's Agents SDK to create real-time audio-driven avatars.
    This requires:
    1. Creating an Agent with a presenter image
    2. Creating a stream for that agent (WebRTC-based)
    3. Sending text via the chat API

    Configuration:
        api_key_env: Environment variable for D-ID API key (default: DID_API_KEY)
        presenter_id: D-ID presenter ID (optional, uses default if not set)
        resolution: [width, height] (default: [512, 512])
        fps: Target frames per second (default: 25)

    Note: Real-time streaming with D-ID requires WebRTC. This adapter
    provides connection info for browser-side WebRTC clients and falls
    back to placeholder frames for server-side processing.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.api_key_env = config.get("api_key_env", "DID_API_KEY")
        self.presenter_id = config.get("presenter_id")
        self.resolution = config.get("resolution", [512, 512])
        self.fps = config.get("fps", 25)

        self._client: httpx.AsyncClient | None = None
        self._agent_id: str | None = None
        self._session_id: str | None = None
        self._stream_url: str | None = None
        self._chat_id: str | None = None
        self._is_healthy = False
        self._frame_index = 0

        # Active connections by session_id
        self._connections: dict[str, DIDConnectionInfo] = {}

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

        # D-ID API uses Basic Auth with format: base64(api_key:)
        # The API key is the username, password is empty
        self._client = httpx.AsyncClient(
            base_url=_DID_API_URL,
            headers={
                "Authorization": f"Basic {base64.b64encode(f'{api_key}:'.encode()).decode()}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )
        self._is_healthy = True
        logger.info("D-ID Streaming adapter loaded")

    # ── Public API for WebRTC Connection ─────────────────────────────────────

    async def create_connection(self, session_id: str) -> DIDConnectionInfo | None:
        """Create a D-ID streaming connection for a session.

        This creates an agent (if needed) and a stream, returning
        connection info for the browser to establish WebRTC.

        Args:
            session_id: Our internal session ID

        Returns:
            DIDConnectionInfo with details for browser WebRTC connection
        """
        if not self._is_healthy or not self._client:
            logger.warning("D-ID adapter not healthy")
            return None

        try:
            # Ensure we have an agent
            agent_id = await self._ensure_agent()
            if not agent_id:
                return None

            # Create stream for this session (includes offer and ICE servers)
            stream_result = await self._create_stream(agent_id)
            if not stream_result:
                return None
            stream_id, offer, ice_servers, webrtc_session_id = stream_result

            # Create chat session
            chat_id = await self._create_chat(agent_id, stream_id)

            # Store connection info
            conn_info = DIDConnectionInfo(
                agent_id=agent_id,
                stream_id=stream_id,
                session_id=chat_id or "",
                webrtc_session_id=webrtc_session_id,
                offer=offer,
                ice_servers=ice_servers,
            )
            self._connections[session_id] = conn_info

            logger.info(f"Created D-ID connection for session {session_id}")
            return conn_info

        except Exception as e:
            logger.error(f"Failed to create D-ID connection: {e}")
            return None

    async def send_text(self, session_id: str, text: str) -> bool:
        """Send text to D-ID chat for the agent to speak.

        Args:
            session_id: Our internal session ID
            text: Text for the agent to speak

        Returns True on success.
        """
        conn = self._connections.get(session_id)
        if not conn or not self._client:
            return False

        if not conn.session_id:
            logger.warning("No chat session available")
            return False

        try:
            from datetime import datetime, timezone
            timestamp = datetime.now(timezone.utc).isoformat()
            response = await self._client.post(
                f"/agents/{conn.agent_id}/chat/{conn.session_id}",
                json={
                    "chatMode": "Functional",
                    "streamId": conn.stream_id,
                    "sessionId": conn.webrtc_session_id,
                    "messages": [
                        {"role": "user", "content": text, "created_at": timestamp}
                    ],
                }
            )
            if response.status_code not in (200, 201):
                logger.warning(f"Failed to send message: {response.status_code} - {response.text[:200]}")
                return False
            return True
        except Exception as e:
            logger.error(f"Failed to send text: {e}")
            return False

    async def close_connection(self, session_id: str) -> None:
        """Close a D-ID streaming connection."""
        conn = self._connections.pop(session_id, None)
        if not conn or not self._client:
            return

        try:
            encoded_stream_id = urllib.parse.quote(conn.stream_id, safe='')
            await self._client.delete(
                f"/agents/{conn.agent_id}/streams/{encoded_stream_id}"
            )
            logger.info(f"Closed D-ID connection for session {session_id}")
        except Exception as e:
            logger.warning(f"Failed to close D-ID connection: {e}")

    async def submit_ice_candidate(
        self, session_id: str, candidate: dict
    ) -> bool:
        """Submit ICE candidate from browser to D-ID.

        Args:
            session_id: Our internal session ID
            candidate: ICE candidate from browser

        Returns True on success.
        """
        conn = self._connections.get(session_id)
        if not conn or not self._client:
            logger.warning(f"No connection found for session {session_id}")
            return False

        try:
            # URL-encode stream_id (contains $ character)
            encoded_stream_id = urllib.parse.quote(conn.stream_id, safe='')
            url = f"/agents/{conn.agent_id}/streams/{encoded_stream_id}/ice"
            logger.info(f"Submitting ICE candidate to D-ID: {candidate.get('candidate', '')[:50]}...")
            response = await self._client.post(url, json={
                "session_id": conn.webrtc_session_id,
                **candidate,
            })
            logger.info(f"D-ID ICE response: {response.status_code}")
            return response.status_code in (200, 201)
        except Exception as e:
            logger.error(f"Failed to submit ICE candidate: {e}")
            return False

    async def submit_sdp_answer(
        self, session_id: str, answer: dict
    ) -> bool:
        """Submit SDP answer from browser to D-ID.

        Args:
            session_id: Our internal session ID
            answer: SDP answer from browser

        Returns True on success.
        """
        conn = self._connections.get(session_id)
        if not conn or not self._client:
            logger.warning(f"No connection found for session {session_id}")
            return False

        try:
            # URL-encode stream_id (contains $ character)
            encoded_stream_id = urllib.parse.quote(conn.stream_id, safe='')
            url = f"/agents/{conn.agent_id}/streams/{encoded_stream_id}/sdp"
            logger.info("Submitting SDP answer to D-ID")
            response = await self._client.post(url, json={
                "session_id": conn.webrtc_session_id,
                "answer": answer,
            })
            logger.info(f"D-ID SDP response: {response.status_code}")
            return response.status_code in (200, 201)
        except Exception as e:
            logger.error(f"Failed to submit SDP answer: {e}")
            return False

    # ── Internal Methods ─────────────────────────────────────────────────────

    async def _ensure_agent(self) -> str | None:
        """Ensure an Agent exists, creating one if needed.
        Returns the agent ID or None on failure.
        """
        if self._agent_id:
            return self._agent_id

        if not self._is_healthy or not self._client:
            return None

        # Create an agent with a clip presenter
        # Default to Adam presenter if not specified
        default_presenter_id = self.presenter_id or "v2_public_Adam@0GLJgELXjc"
        payload = {
            "presenter": {
                "type": "clip",
                "presenter_id": default_presenter_id,
                "voice": {
                    "type": "microsoft",
                    "voice_id": "en-US-JennyNeural"
                }
            }
        }

        try:
            logger.info(f"Creating D-ID agent with payload: {json.dumps(payload, indent=2)}")
            response = await self._client.post("/agents", json=payload)
            logger.info(f"D-ID API response: status={response.status_code}, body={response.text[:500]}")
            if response.status_code == 401:
                logger.error("Invalid D-ID API key")
                return None
            if response.status_code not in (200, 201):
                logger.error(f"Failed to create agent: {response.status_code} - {response.text}")
                return None
            result = response.json()
            self._agent_id = result.get("id")
            logger.info(f"Created D-ID agent: {self._agent_id}")
            return self._agent_id
        except Exception as e:
            logger.error(f"D-ID API error creating agent: {e}")
            return None

    async def _create_stream(
        self, agent_id: str
    ) -> tuple[str, dict | None, list | None, str] | None:
        """Create a D-ID stream for the agent.

        Returns (stream_id, offer, ice_servers, webrtc_session_id) or None on failure.
        The stream creation response includes the SDP offer, ICE servers, and session_id
        which must be included in all subsequent SDP/ICE requests.
        """
        if not self._client:
            return None

        try:
            response = await self._client.post(
                f"/agents/{agent_id}/streams",
                json={"fluent": True}
            )
            if response.status_code == 401:
                logger.error("Invalid D-ID API key")
                return None
            if response.status_code not in (200, 201):
                logger.error(f"Failed to create stream: {response.status_code} - {response.text}")
                return None
            result = response.json()
            stream_id = result.get("id")
            offer = result.get("offer")
            ice_servers = result.get("ice_servers")
            webrtc_session_id = result.get("session_id", "")
            logger.info(f"Created D-ID stream: {stream_id}, webrtc_session_id: {webrtc_session_id}")
            return (stream_id, offer, ice_servers, webrtc_session_id)
        except Exception as e:
            logger.error(f"D-ID API error creating stream: {e}")
            return None

    async def _create_chat(self, agent_id: str, stream_id: str) -> str | None:
        """Create a chat session for the agent.

        Note: chat is created at /agents/{id}/chat (not under /streams/).
        The stream association is passed per-message via streamId/sessionId.
        """
        if not self._client:
            return None

        try:
            response = await self._client.post(
                f"/agents/{agent_id}/chat",
                json={"persist": False},
            )
            if response.status_code not in (200, 201):
                logger.warning(f"Failed to create chat: {response.status_code} - {response.text[:200]}")
                return None
            result = response.json()
            chat_id = result.get("id")
            logger.info(f"Created D-ID chat: {chat_id}")
            return chat_id
        except Exception as e:
            logger.error(f"Failed to create chat: {e}")
            return None

    # ── AdapterBase Interface ────────────────────────────────────────────────

    async def infer_stream(
        self, input: AudioChunk, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[VideoFrame]:
        """Generate avatar frames from audio input.

        Note: D-ID's real-time streaming uses WebRTC, which delivers video
        directly to the browser client. Server-side frame retrieval is not
        supported. This adapter yields placeholder frames for server-side
        processing. Use create_connection() for browser WebRTC integration.

        Args:
            input: AudioChunk (PCM, 24kHz from Realtime API)
            control: TurnControl with emotion/character settings
            context: Pipeline context with session_id, frame_counter

        Yields:
            VideoFrame placeholder objects (actual video delivered via WebRTC)
        """
        # D-ID streaming uses WebRTC - video goes directly to browser client
        # Server cannot retrieve video frames from the stream
        # Always yield placeholder frames for server-side processing
        async for frame in self._generate_placeholder(input, context):
            yield frame

    async def _generate_placeholder(
        self, input: AudioChunk, context: dict[str, Any]
    ) -> AsyncIterator[VideoFrame]:
        """Generate placeholder frames when D-ID is unavailable."""
        import io
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            # Fallback: yield minimal JPEG
            yield VideoFrame(
                data=b"",
                timestamp_ms=input.timestamp_ms,
                frame_index=self._frame_index,
                width=self.resolution[0],
                height=self.resolution[1],
                content_type="jpeg",
            )
            self._frame_index += 1
            return
        # Generate a simple placeholder image
        img = Image.new("RGB", tuple(self.resolution), color=(60, 60, 80))
        draw = ImageDraw.Draw(img)
        text = "D-ID Streaming"
        draw.text(
            (self.resolution[0] // 2, self.resolution[1] // 2),
            text,
            fill=(200, 200, 200),
            anchor="mm"
        )
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        yield VideoFrame(
            data=buffer.getvalue(),
            timestamp_ms=input.timestamp_ms,
            frame_index=self._frame_index,
            width=self.resolution[0],
            height=self.resolution[1],
            content_type="jpeg",
        )
        self._frame_index += 1

    async def interrupt(self) -> None:
        """Handle interrupt - reset frame index."""
        logger.info("D-ID adapter interrupted")
        self._frame_index = 0

    async def health(self) -> HealthStatus:
        """Check D-ID API health.

        Note: Even when healthy, this adapter yields placeholder frames
        because D-ID's WebRTC streaming delivers video directly to the
        browser, not to the server.
        """
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
            detail="D-ID API configured (WebRTC mode - video to browser only)",
        )

    def capabilities(self) -> AdapterCapabilities:
        """Return adapter capabilities.

        Note: supports_streaming is False because server-side frame
        retrieval is not supported. D-ID uses WebRTC for real-time
        video delivery directly to browser clients.
        """
        return AdapterCapabilities(
            supports_streaming=False,  # Server-side streaming not supported
            supports_emotion=True,
            supports_identity=True,
        )

    async def close(self) -> None:
        """Clean up resources."""
        # Close all active connections
        for session_id in list(self._connections.keys()):
            await self.close_connection(session_id)

        if self._client:
            await self._client.aclose()
            self._client = None
