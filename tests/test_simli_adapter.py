# tests/test_simli_adapter.py
"""Offline tests for SimliAvatarAdapter.

All tests mock SimliClient — no API key or network required.
"""
from __future__ import annotations

import asyncio
import io
import os
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from tth.adapters.avatar.simli import SimliAvatarAdapter, _av_frame_to_jpeg
from tth.core.types import (
    AudioChunk,
    CharacterControl,
    EmotionControl,
    TurnControl,
    VideoFrame,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_audio_chunk(duration_ms: float = 100.0) -> AudioChunk:
    """Create a PCM audio chunk at 24kHz matching the given duration."""
    n_bytes = int(24000 * 2 * duration_ms / 1000)
    return AudioChunk(
        data=bytes(n_bytes),
        timestamp_ms=0.0,
        duration_ms=duration_ms,
        encoding="pcm",
        sample_rate=24000,
    )


def _make_turn_control() -> TurnControl:
    return TurnControl(
        emotion=EmotionControl(),
        character=CharacterControl(),
    )


def _make_fake_jpeg(width: int = 64, height: int = 64) -> bytes:
    """Create a minimal valid JPEG in memory."""
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_fake_video_frame() -> VideoFrame:
    return VideoFrame(
        data=_make_fake_jpeg(),
        timestamp_ms=1000.0,
        frame_index=0,
        width=64,
        height=64,
        content_type="jpeg",
    )


def _make_mock_client() -> MagicMock:
    """Create a SimliClient mock with sensible defaults."""
    client = MagicMock()
    client.start = AsyncMock(return_value=client)
    client.stop = AsyncMock()
    client.send = AsyncMock()
    client.sendSilence = AsyncMock()
    client.clearBuffer = AsyncMock()

    # getVideoStreamIterator yields nothing by default
    async def _empty_stream(fmt: str) -> AsyncGenerator:
        return
        yield  # make it an async generator

    client.getVideoStreamIterator = MagicMock(side_effect=_empty_stream)
    return client


# ---------------------------------------------------------------------------
# _av_frame_to_jpeg unit test
# ---------------------------------------------------------------------------

def test_av_frame_to_jpeg_produces_valid_jpeg():
    """_av_frame_to_jpeg converts a PyAV-like frame to valid JPEG bytes."""

    # Build a minimal mock that mimics av.VideoFrame with to_image()
    img = Image.new("RGB", (32, 32), color=(255, 0, 0))
    mock_av_frame = MagicMock()
    mock_av_frame.to_image.return_value = img

    jpeg = _av_frame_to_jpeg(mock_av_frame)

    assert isinstance(jpeg, bytes)
    assert jpeg[:2] == b"\xff\xd8"  # JPEG magic bytes
    # Verify round-trip
    decoded = Image.open(io.BytesIO(jpeg))
    assert decoded.size == (32, 32)


# ---------------------------------------------------------------------------
# load() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_without_api_key_stays_inactive():
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY_MISSING_XYZ"})
    await adapter.load()
    assert not adapter._is_healthy
    assert adapter._client is None


@pytest.mark.asyncio
async def test_load_with_api_key_starts_client():
    mock_client = _make_mock_client()

    with patch("tth.adapters.avatar.simli.SimliClient", return_value=mock_client), \
         patch.dict(os.environ, {"SIMLI_API_KEY": "test-key-123"}):
        adapter = SimliAvatarAdapter({
            "api_key_env": "SIMLI_API_KEY",
            "face_id": "test-face",
            "min_chunk_ms": 50,
        })
        await adapter.load()

    assert adapter._is_healthy
    mock_client.start.assert_called_once()
    mock_client.sendSilence.assert_called_once()
    assert adapter._frame_consumer_task is not None

    await adapter.close()


@pytest.mark.asyncio
async def test_load_handles_client_start_failure():
    mock_client = _make_mock_client()
    mock_client.start.side_effect = RuntimeError("connection refused")

    with patch("tth.adapters.avatar.simli.SimliClient", return_value=mock_client), \
         patch.dict(os.environ, {"SIMLI_API_KEY": "test-key"}):
        adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY"})
        await adapter.load()

    assert not adapter._is_healthy


# ---------------------------------------------------------------------------
# infer_stream() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_infer_stream_buffers_audio_before_sending():
    """With min_chunk_ms=200, a 100ms chunk should not trigger a send."""
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY", "min_chunk_ms": 200})
    adapter._is_healthy = True
    adapter._client = _make_mock_client()

    chunk = _make_audio_chunk(duration_ms=100.0)
    frames = [f async for f in adapter.infer_stream(chunk, _make_turn_control(), {})]

    assert frames == []
    adapter._client.send.assert_not_called()


@pytest.mark.asyncio
async def test_infer_stream_sends_audio_when_buffer_full():
    """With min_chunk_ms=100, a 100ms chunk should send once."""
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY", "min_chunk_ms": 100})
    adapter._is_healthy = True
    adapter._client = _make_mock_client()

    chunk = _make_audio_chunk(duration_ms=100.0)
    _ = [f async for f in adapter.infer_stream(chunk, _make_turn_control(), {})]

    adapter._client.send.assert_called_once()
    sent_bytes = adapter._client.send.call_args[0][0]
    assert isinstance(sent_bytes, bytes)
    assert len(sent_bytes) > 0


@pytest.mark.asyncio
async def test_infer_stream_yields_queued_frames():
    """Frames already in the queue are yielded when audio is sent."""
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY", "min_chunk_ms": 100})
    adapter._is_healthy = True
    adapter._client = _make_mock_client()

    # Pre-load two frames into the queue (simulating _consume_frames output)
    for i in range(2):
        await adapter._pending_frames.put(_make_fake_video_frame())

    chunk = _make_audio_chunk(duration_ms=100.0)
    frames = [f async for f in adapter.infer_stream(chunk, _make_turn_control(), {})]

    assert len(frames) == 2
    assert all(f.content_type == "jpeg" for f in frames)


@pytest.mark.asyncio
async def test_infer_stream_falls_back_to_stub_when_unhealthy():
    """When not connected, infer_stream falls back to stub (not empty)."""
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY_MISSING_XYZ"})
    adapter._is_healthy = False
    adapter._client = None

    chunk = _make_audio_chunk(duration_ms=100.0)
    # Stub yields raw_rgb frames; just check we get something back
    frames = [f async for f in adapter.infer_stream(chunk, _make_turn_control(), {})]

    # Stub always yields at least one placeholder frame per call
    assert len(frames) >= 1


# ---------------------------------------------------------------------------
# interrupt() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interrupt_clears_buffer_and_queue():
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY", "min_chunk_ms": 200})
    adapter._is_healthy = True
    adapter._client = _make_mock_client()

    # Partially fill audio buffer (not enough to flush yet)
    adapter._buffer.add(_make_audio_chunk(duration_ms=100.0))
    assert adapter._buffer.buffered_ms > 0

    # Fill frame queue
    for _ in range(5):
        await adapter._pending_frames.put(_make_fake_video_frame())
    assert not adapter._pending_frames.empty()

    await adapter.interrupt()

    assert adapter._buffer.buffered_ms == 0
    assert adapter._pending_frames.empty()
    adapter._client.clearBuffer.assert_called_once()


# ---------------------------------------------------------------------------
# close() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_stops_client_and_consumer():
    mock_client = _make_mock_client()

    with patch("tth.adapters.avatar.simli.SimliClient", return_value=mock_client), \
         patch.dict(os.environ, {"SIMLI_API_KEY": "test-key"}):
        adapter = SimliAvatarAdapter({
            "api_key_env": "SIMLI_API_KEY",
            "min_chunk_ms": 50,
        })
        await adapter.load()
        assert adapter._is_healthy

        await adapter.close()

    assert not adapter._is_healthy
    assert adapter._client is None
    mock_client.stop.assert_called_once()


# ---------------------------------------------------------------------------
# health() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_reports_connected_when_healthy():
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY"})
    adapter._is_healthy = True

    status = await adapter.health()
    assert status.healthy


@pytest.mark.asyncio
async def test_health_reports_disconnected_when_unhealthy():
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY"})
    adapter._is_healthy = False

    status = await adapter.health()
    assert not status.healthy


# ---------------------------------------------------------------------------
# _consume_frames integration test (mocked av frame)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consume_frames_converts_av_frames_to_jpeg():
    """_consume_frames converts PyAV frames to JPEG and enqueues them."""
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY"})

    # Build a fake av.VideoFrame
    img = Image.new("RGB", (64, 64), color=(0, 128, 255))
    fake_av = MagicMock()
    fake_av.to_image.return_value = img
    fake_av.width = 64
    fake_av.height = 64

    # Mock client whose video iterator yields one frame then stops
    mock_client = _make_mock_client()

    async def _one_frame_stream(fmt: str):
        yield fake_av

    mock_client.getVideoStreamIterator = MagicMock(side_effect=_one_frame_stream)
    adapter._client = mock_client
    adapter._is_healthy = True

    # Run the consumer until it exhausts
    await adapter._consume_frames()

    assert adapter._pending_frames.qsize() == 1
    frame = adapter._pending_frames.get_nowait()
    assert frame.content_type == "jpeg"
    assert frame.data[:2] == b"\xff\xd8"  # valid JPEG
    assert frame.width == 64
    assert frame.height == 64
