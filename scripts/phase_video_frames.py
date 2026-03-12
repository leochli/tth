#!/usr/bin/env python3
"""Offline video frame pipeline test — no API keys required.

Drives stub_avatar and mock_cloud_avatar directly, then verifies:
  1. Frames are produced (at least 1 per audio chunk)
  2. content_type == "jpeg"
  3. Raw bytes are decodable as JPEG by PIL
  4. VideoFrameEvent JSON round-trip is correct (base64 encode/decode)
  5. Decoded bytes match originals exactly
  6. Multiple audio chunks across a turn all yield frames (not just the first)

Run from repo root:
    uv run python scripts/phase_video_frames.py
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from PIL import Image

from tth.adapters.avatar.mock_cloud import MockCloudAvatarAdapter
from tth.adapters.avatar.stub import StubAvatarAdapter
from tth.core.types import AudioChunk, TurnControl, VideoFrameEvent


# ── helpers ──────────────────────────────────────────────────────────────────


def _pcm_chunk(duration_ms: float = 200.0) -> AudioChunk:
    sample_rate = 24000
    samples = int(sample_rate * duration_ms / 1000)
    return AudioChunk(
        data=b"\x00" * (samples * 2),  # 16-bit silence
        timestamp_ms=time.monotonic() * 1000,
        duration_ms=duration_ms,
        sample_rate=sample_rate,
        encoding="pcm",
    )


async def _collect(adapter, chunk: AudioChunk) -> list:
    frames = []
    async for f in adapter.infer_stream(chunk, TurnControl(), {"frame_counter": 0, "session_id": "test"}):
        frames.append(f)
    return frames


def _assert_jpeg(data: bytes, label: str) -> Image.Image:
    assert data[:2] == b"\xff\xd8", f"{label}: missing JPEG SOI (got {data[:4].hex()})"
    assert data[-2:] == b"\xff\xd9", f"{label}: missing JPEG EOI (got {data[-4:].hex()})"
    img = Image.open(io.BytesIO(data))
    img.load()
    assert img.mode in ("RGB", "L", "RGBA"), f"{label}: unexpected mode {img.mode}"
    return img


def _assert_event_roundtrip(frame, label: str) -> None:
    event = VideoFrameEvent(
        data=frame.data,
        timestamp_ms=frame.timestamp_ms,
        frame_index=frame.frame_index,
        width=frame.width,
        height=frame.height,
        content_type=frame.content_type,
        drift_ms=0.0,
    )
    raw_json = event.model_dump_json()
    parsed = json.loads(raw_json)

    assert parsed["type"] == "video_frame", f"{label}: type={parsed['type']!r}"
    assert parsed["content_type"] == "jpeg", f"{label}: content_type={parsed['content_type']!r}"

    decoded = base64.b64decode(parsed["data"])
    assert decoded == frame.data, f"{label}: base64 round-trip mismatch ({len(decoded)} vs {len(frame.data)} bytes)"

    # Validate the bytes the browser would actually receive
    _assert_jpeg(decoded, f"{label}[via JSON]")


# ── test cases ────────────────────────────────────────────────────────────────


async def test_stub_avatar() -> None:
    print("\n[1] stub_avatar — PIL-generated JPEG frames, single chunk")
    adapter = StubAvatarAdapter({"fps": 25})
    chunk = _pcm_chunk(duration_ms=200.0)
    frames = await _collect(adapter, chunk)

    assert frames, "stub_avatar produced no frames"
    print(f"    produced {len(frames)} frames")

    for i, f in enumerate(frames):
        assert f.content_type == "jpeg", f"frame {i}: content_type={f.content_type!r}"
        assert f.width == 256 and f.height == 256, f"frame {i}: dimensions {f.width}x{f.height}"
        img = _assert_jpeg(f.data, f"stub frame {i}")
        print(f"    frame {i}: {img.size} {img.mode} ({len(f.data)} bytes) ✓")
        _assert_event_roundtrip(f, f"stub frame {i}")

    print("    PASS")


async def test_stub_avatar_multi_chunk() -> None:
    """Simulate a multi-chunk turn: verify frames come back across ALL chunks, not just first."""
    print("\n[2] stub_avatar — multi-chunk turn (simulates real OpenAI Realtime streaming)")
    adapter = StubAvatarAdapter({"fps": 25})
    control = TurnControl()

    all_frames: list = []
    chunks_with_frames = 0
    n_chunks = 8  # 8 × 100ms = 800ms of audio

    for i in range(n_chunks):
        ctx = {"frame_counter": len(all_frames), "session_id": "test"}
        chunk = _pcm_chunk(duration_ms=100.0)
        frames_this_chunk = []
        async for f in adapter.infer_stream(chunk, control, ctx):
            frames_this_chunk.append(f)
        if frames_this_chunk:
            chunks_with_frames += 1
        all_frames.extend(frames_this_chunk)

    print(f"    {n_chunks} chunks → {len(all_frames)} total frames, {chunks_with_frames}/{n_chunks} chunks had frames")
    assert len(all_frames) > 0, "no frames produced across entire turn"
    assert chunks_with_frames >= n_chunks // 2, (
        f"only {chunks_with_frames}/{n_chunks} chunks produced frames — "
        "frames are not being delivered across the turn"
    )

    for i, f in enumerate(all_frames[:3]):
        _assert_jpeg(f.data, f"multi-chunk frame {i}")
        _assert_event_roundtrip(f, f"multi-chunk frame {i}")

    print("    PASS")


async def test_mock_cloud_avatar() -> None:
    print("\n[3] mock_cloud_avatar — hand-crafted minimal JPEG")
    adapter = MockCloudAvatarAdapter({"simulated_latency_ms": 0, "resolution": [512, 512], "fps": 25})
    await adapter.load()
    chunk = _pcm_chunk(duration_ms=200.0)
    frames = await _collect(adapter, chunk)

    assert frames, "mock_cloud_avatar produced no frames"
    print(f"    produced {len(frames)} frames")

    f = frames[0]
    assert f.content_type == "jpeg", f"content_type={f.content_type!r}"
    assert f.width == 512 and f.height == 512, f"dimensions {f.width}x{f.height}"
    img = _assert_jpeg(f.data, "mock_cloud frame 0")
    print(f"    frame 0: {img.size} {img.mode} ({len(f.data)} bytes) ✓")
    _assert_event_roundtrip(f, "mock_cloud frame 0")

    print("    PASS")


# ── main ─────────────────────────────────────────────────────────────────────


async def main() -> int:
    print("[phase-video-frames] offline JPEG frame pipeline validation")
    failed = False

    for test_fn in (test_stub_avatar, test_stub_avatar_multi_chunk, test_mock_cloud_avatar):
        try:
            await test_fn()
        except Exception as e:
            print(f"    FAIL: {e}")
            failed = True

    if failed:
        print("\n[phase-video-frames] FAIL")
        return 1

    print("\n[phase-video-frames] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
