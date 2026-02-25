# tests/test_adapters.py
"""Unit tests for adapters — mock httpx, verify event shapes."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from tth.core.types import (
    TurnControl,
    AudioChunk,
    EmotionControl,
    EmotionLabel,
    estimate_mp3_duration_ms,
)
from tth.adapters.avatar.stub import StubAvatarAdapter
from tth.core.registry import get, list_registered


# ── Registry ──────────────────────────────────────────────────────────────────


def test_registry_has_openai_chat():
    # Importing the adapter modules registers them
    import tth.adapters.llm.openai_api  # noqa

    assert "openai_chat" in list_registered()


def test_registry_has_openai_tts():
    import tth.adapters.tts.openai_tts  # noqa

    assert "openai_tts" in list_registered()


def test_registry_has_stub_avatar():
    import tth.adapters.avatar.stub  # noqa

    assert "stub_avatar" in list_registered()


def test_registry_get_unknown_raises():
    with pytest.raises(KeyError, match="No adapter"):
        get("nonexistent_adapter_xyz")


# ── StubAvatarAdapter ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stub_avatar_health():
    adapter = StubAvatarAdapter({})
    status = await adapter.health()
    assert status.healthy is True


@pytest.mark.asyncio
async def test_stub_avatar_produces_frames():
    adapter = StubAvatarAdapter({})
    chunk = AudioChunk(
        data=b"\x00" * 4096,
        timestamp_ms=0.0,
        duration_ms=1000.0,  # 1 second → 25 frames at 25 FPS
    )
    frames = []
    async for frame in adapter.infer_stream(chunk, TurnControl(), {}):
        frames.append(frame)

    assert len(frames) == 25  # 1000ms / 1000 * 25 FPS = 25 frames


@pytest.mark.asyncio
async def test_stub_avatar_frame_content_type():
    adapter = StubAvatarAdapter({})
    chunk = AudioChunk(
        data=b"\x00" * 1000,
        timestamp_ms=0.0,
        duration_ms=200.0,  # 200ms → 5 frames
    )
    async for frame in adapter.infer_stream(chunk, TurnControl(), {}):
        assert frame.content_type == "raw_rgb"
        assert frame.width == 256
        assert frame.height == 256


@pytest.mark.asyncio
async def test_stub_avatar_at_least_one_frame():
    """Even a tiny chunk should produce at least one frame."""
    adapter = StubAvatarAdapter({})
    chunk = AudioChunk(
        data=b"\x00",
        timestamp_ms=0.0,
        duration_ms=1.0,  # tiny duration
    )
    frames = []
    async for frame in adapter.infer_stream(chunk, TurnControl(), {}):
        frames.append(frame)
    assert len(frames) >= 1


@pytest.mark.asyncio
async def test_stub_avatar_frame_timestamps():
    adapter = StubAvatarAdapter({})
    chunk = AudioChunk(
        data=b"\x00" * 1000,
        timestamp_ms=1000.0,
        duration_ms=200.0,
    )
    frame_ts = []
    async for frame in adapter.infer_stream(chunk, TurnControl(), {}):
        frame_ts.append(frame.timestamp_ms)

    # Timestamps should be monotonically increasing
    assert all(frame_ts[i] <= frame_ts[i + 1] for i in range(len(frame_ts) - 1))
    # First frame should start at chunk timestamp
    assert frame_ts[0] == pytest.approx(1000.0)


@pytest.mark.asyncio
async def test_stub_avatar_frame_index():
    adapter = StubAvatarAdapter({})
    chunk = AudioChunk(
        data=b"\x00" * 1000,
        timestamp_ms=0.0,
        duration_ms=80.0,  # 2 frames
    )
    frames = []
    async for frame in adapter.infer_stream(chunk, TurnControl(), {"frame_counter": 10}):
        frames.append(frame)
    # frame_index should start from context["frame_counter"]
    assert frames[0].frame_index == 10


def test_stub_avatar_capabilities():
    adapter = StubAvatarAdapter({})
    caps = adapter.capabilities()
    assert caps.supports_streaming is True
    assert caps.supports_emotion is False
    assert caps.supports_identity is False


# ── estimate_mp3_duration_ms ──────────────────────────────────────────────────


def test_duration_estimation_4096_bytes():
    dur = estimate_mp3_duration_ms(b"\x00" * 4096, bitrate_kbps=128)
    assert abs(dur - 256.0) < 0.01


def test_duration_nonzero_for_any_data():
    for size in [1, 100, 1024, 8192]:
        dur = estimate_mp3_duration_ms(b"\x00" * size, bitrate_kbps=128)
        assert dur > 0, f"duration must be > 0 for size={size}"


# ── DriftController ───────────────────────────────────────────────────────────


def test_drift_controller():
    from tth.alignment.drift import DriftController

    dc = DriftController(window=5)
    assert dc.mean_drift_ms == 0.0

    dc.update(audio_ts_ms=0.0, video_ts_ms=10.0)
    assert dc.mean_drift_ms == pytest.approx(10.0)

    dc.update(audio_ts_ms=100.0, video_ts_ms=90.0)
    # mean of [10, -10]
    assert dc.mean_drift_ms == pytest.approx(0.0)


def test_drift_controller_within_budget():
    from tth.alignment.drift import DriftController

    dc = DriftController()
    dc.update(0.0, 50.0)  # 50ms drift — within 80ms budget
    assert dc.is_within_budget(80.0) is True


def test_drift_controller_exceeds_budget():
    from tth.alignment.drift import DriftController

    dc = DriftController()
    dc.update(0.0, 100.0)  # 100ms drift — exceeds 80ms budget
    assert dc.is_within_budget(80.0) is False


def test_drift_controller_reset():
    from tth.alignment.drift import DriftController

    dc = DriftController()
    dc.update(0.0, 50.0)
    dc.reset()
    assert dc.mean_drift_ms == 0.0


# ── Session ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_state_transitions():
    from tth.pipeline.session import Session
    from tth.core.types import TurnControl

    s = Session("test-id", TurnControl())
    assert s.state == "IDLE"

    s.transition("LLM_RUN")
    assert s.state == "LLM_RUN"

    s.transition("TTS_RUN")
    assert s.state == "TTS_RUN"


@pytest.mark.asyncio
async def test_session_cancel_no_task():
    from tth.pipeline.session import Session

    s = Session("test-id", TurnControl())
    # Should not raise even if no task is running
    await s.cancel_current_turn()
    assert s.state == "IDLE"


@pytest.mark.asyncio
async def test_session_manager_create_and_get():
    from tth.pipeline.session import SessionManager

    sm = SessionManager()
    session = sm.create(persona_id="default")
    assert session.id is not None
    retrieved = sm.get(session.id)
    assert retrieved is session


@pytest.mark.asyncio
async def test_session_manager_close():
    from tth.pipeline.session import SessionManager

    sm = SessionManager()
    session = sm.create()
    sm.close(session.id)
    assert sm.get(session.id) is None


@pytest.mark.asyncio
async def test_session_manager_get_or_404():
    from tth.pipeline.session import SessionManager

    sm = SessionManager()
    with pytest.raises(KeyError):
        sm.get_or_404("nonexistent-session-id")
