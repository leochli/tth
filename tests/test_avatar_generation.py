# tests/test_avatar_generation.py
"""Offline tests for avatar generation.

Tests that avatar adapters actually generate video frames from audio input.
Run with: pytest tests/test_avatar_generation.py -v
"""
from __future__ import annotations

import time

import pytest

from tth.adapters.avatar.stub import StubAvatarAdapter
from tth.adapters.avatar.mock_cloud import MockCloudAvatarAdapter
from tth.adapters.avatar.did_streaming import DIDStreamingAvatar
from tth.core.types import AudioChunk, TurnControl, EmotionControl, CharacterControl, EmotionLabel


# Test fixtures
@pytest.fixture
def sample_audio() -> bytes:
    """Generate 100ms of 24kHz mono PCM audio (silence)."""
    # 100ms at 24kHz = 2400 samples * 2 bytes = 4800 bytes
    return b"\x00" * 2400


@pytest.fixture
def sample_audio_long() -> bytes:
    """Generate 500ms of 24kHz mono PCM audio (silence)."""
    # 500ms at 24kHz = 12000 samples * 2 bytes = 24000 bytes
    return b"\x00" * 12000


@pytest.fixture
def turn_control() -> TurnControl:
    """Create a default TurnControl for testing."""
    return TurnControl(
        emotion=EmotionControl(
            label=EmotionLabel.NEUTRAL,
            intensity=0.5,
            valence=0.0,
            arousal=0.0,
        ),
        character=CharacterControl(
            persona_id="default",
            speech_rate=1.0,
            pitch_shift=0.0,
            expressivity=0.6,
            motion_gain=1.0,
        ),
    )


@pytest.fixture
def context() -> dict:
    """Create a default context for testing."""
    return {
        "session_id": "test-session-001",
        "frame_counter": 0,
    }


class TestStubAvatar:
    """Test StubAvatarAdapter generates actual frames."""

    @pytest.mark.asyncio
    async def test_stub_generates_frames(self, sample_audio, turn_control, context):
        """Stub adapter should generate frames from audio."""
        adapter = StubAvatarAdapter({"fps": 25})
        await adapter.load()

        chunk = AudioChunk(
            data=sample_audio,
            timestamp_ms=0.0,
            duration_ms=100.0,
            encoding="pcm",
            sample_rate=24000,
        )

        frames = []
        async for frame in adapter.infer_stream(chunk, turn_control, context):
            frames.append(frame)

        assert len(frames) > 0, "Should generate at least one frame"

        # Verify frame properties
        for frame in frames:
            assert frame.data is not None, "Frame data should not be None"
            assert len(frame.data) > 0, "Frame data should not be empty"
            assert frame.width > 0, "Frame width should be positive"
            assert frame.height > 0, "Frame height should be positive"
            assert frame.content_type == "jpeg", "Frame should be JPEG"
            assert frame.timestamp_ms >= 0, "Frame timestamp should be non-negative"

    @pytest.mark.asyncio
    async def test_stub_frame_timing(self, sample_audio_long, turn_control, context):
        """Frame timestamps should align with audio duration."""
        adapter = StubAvatarAdapter({"fps": 25})
        await adapter.load()

        chunk = AudioChunk(
            data=sample_audio_long,
            timestamp_ms=1000.0,  # Start at 1 second
            duration_ms=500.0,
            encoding="pcm",
            sample_rate=24000,
        )

        frames = []
        async for frame in adapter.infer_stream(chunk, turn_control, context):
            frames.append(frame)

        # 500ms at 25fps = ~12-13 frames
        assert len(frames) >= 12, f"Should generate ~12 frames for 500ms audio, got {len(frames)}"

        # Check timestamps are sequential
        for i in range(len(frames) - 1):
            assert frames[i].timestamp_ms <= frames[i + 1].timestamp_ms

    @pytest.mark.asyncio
    async def test_stub_health(self):
        """Stub adapter health check."""
        adapter = StubAvatarAdapter({})
        await adapter.load()

        health = await adapter.health()
        assert health.healthy is True


class TestMockCloudAvatar:
    """Test MockCloudAvatarAdapter generates actual frames."""

    @pytest.mark.asyncio
    async def test_mock_cloud_generates_frames(self, sample_audio, turn_control, context):
        """Mock cloud adapter should generate frames from audio."""
        adapter = MockCloudAvatarAdapter({
            "simulated_latency_ms": 50,
            "resolution": [512, 512],
            "fps": 25,
        })
        await adapter.load()

        chunk = AudioChunk(
            data=sample_audio,
            timestamp_ms=0.0,
            duration_ms=100.0,
            encoding="pcm",
            sample_rate=24000,
        )

        frames = []
        async for frame in adapter.infer_stream(chunk, turn_control, context):
            frames.append(frame)

        assert len(frames) > 0, "Should generate at least one frame"

        # Verify frame is valid JPEG
        first_frame = frames[0]
        assert first_frame.data is not None
        assert len(first_frame.data) > 0
        # Check it's a valid JPEG (starts with FFD8)
        assert first_frame.data[:2] == b"\xff\xd8", "Should be valid JPEG"

    @pytest.mark.asyncio
    async def test_mock_cloud_simulates_latency(self, sample_audio, turn_control, context):
        """Mock cloud should simulate latency."""
        latency_ms = 100
        adapter = MockCloudAvatarAdapter({
            "simulated_latency_ms": latency_ms,
            "resolution": [512, 512],
            "fps": 25,
        })
        await adapter.load()

        chunk = AudioChunk(
            data=sample_audio,
            timestamp_ms=0.0,
            duration_ms=100.0,
            encoding="pcm",
            sample_rate=24000,
        )

        start = time.monotonic()
        frames = []
        async for frame in adapter.infer_stream(chunk, turn_control, context):
            frames.append(frame)
        elapsed_ms = (time.monotonic() - start) * 1000

        # Should have at least simulated latency
        assert elapsed_ms >= latency_ms * 0.8, \
            f"Should simulate at least {latency_ms}ms latency, took {elapsed_ms:.0f}ms"

    @pytest.mark.asyncio
    async def test_mock_cloud_health(self):
        """Mock cloud adapter health check."""
        adapter = MockCloudAvatarAdapter({"simulated_latency_ms": 150})
        await adapter.load()

        health = await adapter.health()
        assert health.healthy is True
        assert health.latency_ms == 150


class TestDIDStreamingAvatar:
    """Test D-ID Streaming adapter (without API key)."""

    @pytest.mark.asyncio
    async def test_did_streaming_no_api_key(self):
        """D-ID adapter should handle missing API key gracefully."""
        import os
        from unittest.mock import patch
        adapter = DIDStreamingAvatar({
            "resolution": [512, 512],
            "fps": 25,
        })
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DID_API_KEY", None)
            await adapter.load()
            health = await adapter.health()

        assert health.healthy is False
        assert "DID_API_KEY" in health.detail

    @pytest.mark.asyncio
    async def test_did_streaming_placeholder(self, sample_audio, turn_control, context):
        """D-ID adapter should yield placeholder frames when not configured."""
        adapter = DIDStreamingAvatar({
            "resolution": [512, 512],
            "fps": 25,
        })
        await adapter.load()

        chunk = AudioChunk(
            data=sample_audio,
            timestamp_ms=0.0,
            duration_ms=100.0,
            encoding="pcm",
            sample_rate=24000,
        )

        frames = []
        async for frame in adapter.infer_stream(chunk, turn_control, context):
            frames.append(frame)

        # Should yield placeholder frame
        assert len(frames) >= 1, "Should yield at least one placeholder frame"

        frame = frames[0]
        assert frame.data is not None
        assert len(frame.data) > 0
        assert frame.content_type == "jpeg"

        await adapter.close()


class TestAvatarFrameValidation:
    """Test that generated frames meet VideoFrame contract."""

    @pytest.mark.asyncio
    async def test_frame_is_valid_jpeg(self, sample_audio, turn_control, context):
        """Generated frames should be valid JPEG images."""
        adapter = MockCloudAvatarAdapter({"resolution": [256, 256]})
        await adapter.load()

        chunk = AudioChunk(
            data=sample_audio,
            timestamp_ms=0.0,
            duration_ms=100.0,
            encoding="pcm",
            sample_rate=24000,
        )

        async for frame in adapter.infer_stream(chunk, turn_control, context):
            # JPEG magic bytes
            assert frame.data[:2] == b"\xff\xd8", "Should start with JPEG SOI marker"
            assert frame.data[-2:] == b"\xff\xd9", "Should end with JPEG EOI marker"

    @pytest.mark.asyncio
    async def test_frame_dimensions(self, sample_audio, turn_control, context):
        """Frame dimensions should match configuration."""
        resolution = [320, 240]
        adapter = MockCloudAvatarAdapter({"resolution": resolution})
        await adapter.load()

        chunk = AudioChunk(
            data=sample_audio,
            timestamp_ms=0.0,
            duration_ms=100.0,
            encoding="pcm",
            sample_rate=24000,
        )

        async for frame in adapter.infer_stream(chunk, turn_control, context):
            assert frame.width == resolution[0]
            assert frame.height == resolution[1]

    @pytest.mark.asyncio
    async def test_multiple_audio_chunks(self, turn_control, context):
        """Test processing multiple audio chunks sequentially."""
        adapter = MockCloudAvatarAdapter({"simulated_latency_ms": 10})
        await adapter.load()

        total_frames = 0
        for i in range(3):
            # Each chunk is 50ms
            audio_data = b"\x00" * 1200  # 50ms at 24kHz
            chunk = AudioChunk(
                data=audio_data,
                timestamp_ms=i * 50.0,
                duration_ms=50.0,
                encoding="pcm",
                sample_rate=24000,
            )

            async for frame in adapter.infer_stream(chunk, turn_control, context):
                total_frames += 1
                assert frame.timestamp_ms == i * 50.0

        assert total_frames >= 3, "Should generate frames for each chunk"
