#!/usr/bin/env python3
"""
Phase 4: Avatar Stub + Full Pipeline Test
Tests the stub avatar adapter and the complete orchestrator pipeline.
"""
from __future__ import annotations
import asyncio
import sys


async def test_avatar_stub():
    print("=" * 60)
    print("PHASE 4: Avatar Stub Test")
    print("=" * 60)

    from tth.adapters.avatar.stub import StubAvatarAdapter
    from tth.core.types import TurnControl, AudioChunk

    adapter = StubAvatarAdapter({})

    # Test health
    print("[1/3] Health check...")
    health = await adapter.health()
    print(f"      healthy={health.healthy}, detail={health.detail}")
    assert health.healthy

    # Test capabilities
    print("[2/3] Capabilities...")
    caps = adapter.capabilities()
    print(f"      streaming={caps.supports_streaming}, emotion={caps.supports_emotion}")

    # Test frame generation
    print("[3/3] Frame generation...")
    chunk = AudioChunk(
        data=b"\x00" * 4096,
        timestamp_ms=0.0,
        duration_ms=1000.0,  # 1 second → 25 frames at 25 FPS
    )

    frames = []
    async for frame in adapter.infer_stream(chunk, TurnControl(), {}):
        frames.append(frame)
        if len(frames) <= 3:
            print(f"      frame {frame.frame_index}: {frame.width}x{frame.height} "
                  f"{frame.content_type} @ {frame.timestamp_ms:.1f}ms")

    print(f"\n      Total frames: {len(frames)}")
    assert len(frames) == 25, f"Expected 25 frames, got {len(frames)}"
    assert all(f.content_type == "raw_rgb" for f in frames), "All frames should be raw_rgb"

    print("\n" + "=" * 60)
    print("PHASE 4 PASSED: Avatar stub working")
    print("=" * 60)
    return True


async def test_drift_controller():
    print("\n" + "=" * 60)
    print("PHASE 4b: Drift Controller Test")
    print("=" * 60)

    from tth.alignment.drift import DriftController

    dc = DriftController(window=5)

    # Simulate some drift
    print("[1/2] Recording drift samples...")
    drifts = [10, -5, 15, -20, 8]  # ms
    for i, d in enumerate(drifts):
        audio_ts = i * 100.0
        video_ts = audio_ts + d
        dc.update(audio_ts, video_ts)
        print(f"      sample {i+1}: audio={audio_ts}ms, video={video_ts}ms, drift={d}ms")

    print(f"\n      Mean drift: {dc.mean_drift_ms:.1f}ms")
    print(f"      Max drift: {dc.max_drift_ms:.1f}ms")
    print(f"      Within 80ms budget: {dc.is_within_budget(80.0)}")

    print("[2/2] Reset and verify...")
    dc.reset()
    assert dc.mean_drift_ms == 0.0, "Mean should be 0 after reset"
    print("      ✓ Reset works")

    print("\n" + "=" * 60)
    print("PHASE 4b PASSED: Drift controller working")
    print("=" * 60)
    return True


async def test_full_pipeline():
    print("\n" + "=" * 60)
    print("PHASE 4c: Full Pipeline Integration Test")
    print("=" * 60)

    from tth.core.config import settings
    from tth.adapters.llm.openai_api import OpenAIChatAdapter
    from tth.adapters.tts.openai_tts import OpenAITTSAdapter
    from tth.adapters.avatar.stub import StubAvatarAdapter
    from tth.pipeline.session import Session
    from tth.pipeline.orchestrator import Orchestrator
    from tth.core.types import TurnControl
    from tth.control.personas import get_persona_defaults

    # Create adapters
    print("[1/3] Creating adapters...")
    llm = OpenAIChatAdapter({"model": "gpt-4o-mini"})
    tts = OpenAITTSAdapter({"model": "tts-1"})
    avatar = StubAvatarAdapter({})

    # Create orchestrator
    print("[2/3] Creating orchestrator and session...")
    orch = Orchestrator(llm=llm, tts=tts, avatar=avatar)
    session = Session(
        session_id="test-session",
        persona_defaults=get_persona_defaults("casual"),
        persona_name="Casual",
    )

    # Run a turn
    print("[3/3] Running full turn...")
    output_q = asyncio.Queue()

    async def collect_events():
        events = []
        while True:
            evt = await output_q.get()
            events.append(evt)
            evt_type = getattr(evt, 'type', type(evt).__name__)
            if evt_type == "turn_complete":
                return events
            # Print progress
            if evt_type == "text_delta":
                print(f"      [text] {evt.token}", end="", flush=True)
            elif evt_type == "audio_chunk":
                print(f"\n      [audio] {len(evt.data)} bytes, dur={evt.duration_ms:.0f}ms")
            elif evt_type == "video_frame":
                print(f"      [video] frame {evt.frame_index}, drift={evt.drift_ms:.1f}ms")

    # Run turn and collect events concurrently
    turn_task = asyncio.create_task(
        orch.run_turn(
            session,
            "Say hello in one short sentence.",
            TurnControl(),
            output_q,
        )
    )
    events = await collect_events()
    await turn_task

    # Analyze results
    text_events = [e for e in events if getattr(e, 'type', None) == "text_delta"]
    audio_events = [e for e in events if getattr(e, 'type', None) == "audio_chunk"]
    video_events = [e for e in events if getattr(e, 'type', None) == "video_frame"]

    print(f"\n\n      Summary:")
    print(f"      - Text tokens: {len(text_events)}")
    print(f"      - Audio chunks: {len(audio_events)}")
    print(f"      - Video frames: {len(video_events)}")
    print(f"      - Session state: {session.state}")
    print(f"      - Mean drift: {session.drift_controller.mean_drift_ms:.1f}ms")

    assert len(text_events) > 0, "No text events!"
    assert len(audio_events) > 0, "No audio events!"
    assert len(video_events) > 0, "No video events!"
    assert session.state == "TURN_COMPLETE", f"Expected TURN_COMPLETE, got {session.state}"

    print("\n" + "=" * 60)
    print("PHASE 4c PASSED: Full pipeline integration working")
    print("=" * 60)
    return True


async def main():
    try:
        if not await test_avatar_stub():
            sys.exit(1)
        if not await test_drift_controller():
            sys.exit(1)
        if not await test_full_pipeline():
            sys.exit(1)
        print("\n✅ ALL PHASE 4 TESTS PASSED\n")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ ASSERTION FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
