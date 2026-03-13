"""
Standalone verification script for the push-model A/V pipeline.

Tests:
  1. infer_stream is feed-only (no yields)
  2. relay_frames delivers frames independently
  3. Audio events flow through output_q alongside video frames
  4. Push-model orchestrator: audio not dropped or starved
  5. Stop event correctly drains relay_frames
  6. Unhealthy adapter: stub frames still reach relay
  7. Orchestrator pull model (stub adapter) still works
"""
from __future__ import annotations
import asyncio
import sys
import time

# ── path setup ────────────────────────────────────────────────────────────────
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from tth.adapters.avatar.simli import SimliAvatarAdapter
from tth.adapters.avatar.stub import StubAvatarAdapter
from tth.core.types import (
    AudioChunk, AudioChunkEvent, TextDeltaEvent, TurnCompleteEvent,
    TurnControl, VideoFrame, VideoFrameEvent,
)
from tth.pipeline.orchestrator import Orchestrator
from tth.pipeline.session import Session, SessionManager

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    status = PASS if cond else FAIL
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    _results.append((name, cond, detail))
    return cond


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_audio_chunk(duration_ms: float = 100.0, ts: float = 0.0) -> AudioChunk:
    n = int(24000 * 2 * duration_ms / 1000)
    return AudioChunk(data=bytes(n), timestamp_ms=ts, duration_ms=duration_ms,
                      encoding="pcm", sample_rate=24000)


def _make_video_frame(ts: float = 0.0, idx: int = 0) -> VideoFrame:
    return VideoFrame(data=b"\xff\xd8\xff" + bytes(100), timestamp_ms=ts,
                      frame_index=idx, width=64, height=64, content_type="jpeg")


# ── Test 1: infer_stream is feed-only ────────────────────────────────────────

async def test_infer_stream_feed_only():
    print("\n[1] infer_stream feed-only (no yielding)")
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY", "min_chunk_ms": 100})
    adapter._is_healthy = True

    from unittest.mock import AsyncMock, MagicMock
    client = MagicMock()
    client.send = AsyncMock()
    adapter._client = client

    chunk = _make_audio_chunk(100.0)
    frames = [f async for f in adapter.infer_stream(chunk, TurnControl(), {})]
    check("yields nothing", frames == [], f"got {len(frames)} frames")
    check("send() called once", client.send.call_count == 1)


# ── Test 2: relay_frames delivers frames injected AFTER relay starts ──────────

async def test_relay_frames_delivers():
    print("\n[2] relay_frames delivers frames injected after relay starts")
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY", "min_chunk_ms": 100})

    stop = asyncio.Event()
    frames: list[VideoFrame] = []

    async def _collect():
        async for f in adapter.relay_frames(stop):
            frames.append(f)
            if len(frames) == 3:
                stop.set()

    async def _inject():
        # Wait for relay to start (past the stale-discard phase)
        await asyncio.sleep(0.08)
        for i in range(3):
            await adapter._pending_frames.put(_make_video_frame(ts=float(i * 40), idx=i))
            await asyncio.sleep(0.01)

    await asyncio.gather(
        asyncio.wait_for(_collect(), timeout=3.0),
        _inject(),
    )
    check("received 3 frames", len(frames) == 3, f"got {len(frames)}")
    check("frames in order", [f.frame_index for f in frames] == [0, 1, 2])


# ── Test 3: relay_frames discards stale, then picks up new ───────────────────

async def test_relay_frames_discard_then_new():
    print("\n[3] relay_frames: discard stale at start, pick up fresh frames")
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY", "min_chunk_ms": 100})

    # Put 2 "stale" frames before relay starts
    for i in range(2):
        await adapter._pending_frames.put(_make_video_frame(ts=float(i), idx=i))

    stop = asyncio.Event()
    fresh_frames: list[VideoFrame] = []

    async def _collect():
        async for f in adapter.relay_frames(stop):
            fresh_frames.append(f)
            stop.set()

    async def _inject():
        await asyncio.sleep(0.05)  # let relay start and discard stale
        await adapter._pending_frames.put(_make_video_frame(ts=999.0, idx=99))

    await asyncio.gather(
        asyncio.wait_for(_collect(), timeout=2.0),
        _inject(),
    )
    check("stale frames discarded", all(f.frame_index == 99 for f in fresh_frames),
          f"indices={[f.frame_index for f in fresh_frames]}")


# ── Test 4: stop event drains then exits ─────────────────────────────────────

async def test_relay_frames_stop_and_drain():
    print("\n[4] relay_frames: stop.set() → drain window → exit")
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY", "min_chunk_ms": 100})
    stop = asyncio.Event()
    collected: list[VideoFrame] = []

    async def _run():
        async for f in adapter.relay_frames(stop):
            collected.append(f)

    relay = asyncio.create_task(_run())

    # Add frame after relay has been polling a bit
    await asyncio.sleep(0.1)
    await adapter._pending_frames.put(_make_video_frame(ts=1.0, idx=1))
    await asyncio.sleep(0.05)
    stop.set()  # signal stop

    try:
        await asyncio.wait_for(relay, timeout=3.0)
    except asyncio.TimeoutError:
        relay.cancel()
        check("relay exits after stop", False, "timed out waiting for relay to drain")
        return

    check("relay exited cleanly", not relay.cancelled())
    check("got frame before stop", len(collected) >= 1, f"collected {len(collected)}")


# ── Test 5: Unhealthy adapter - stub frames reach relay ─────────────────────

async def test_unhealthy_stub_frames_reach_relay():
    print("\n[5] Unhealthy Simli: stub frames queued, relay delivers them")
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY_MISSING", "min_chunk_ms": 100})
    adapter._is_healthy = False
    adapter._client = None

    stop = asyncio.Event()
    delivered: list[VideoFrame] = []

    async def _relay():
        async for f in adapter.relay_frames(stop):
            delivered.append(f)
            if len(delivered) >= 1:
                stop.set()

    relay = asyncio.create_task(_relay())
    await asyncio.sleep(0.05)  # let relay start

    # infer_stream should push stub frames into _pending_frames
    chunk = _make_audio_chunk(100.0)
    async for _ in adapter.infer_stream(chunk, TurnControl(), {}):
        pass  # feed-only

    try:
        await asyncio.wait_for(relay, timeout=2.0)
    except asyncio.TimeoutError:
        relay.cancel()
        check("stub frames reach relay", False, "timed out waiting for stub frames")
        return

    check("stub frames delivered via relay", len(delivered) >= 1,
          f"delivered {len(delivered)}")


# ── Test 6: Full orchestrator push-model pipeline ────────────────────────────

async def test_orchestrator_push_model_audio_flows():
    print("\n[6] Orchestrator push model: audio events flow, not dropped")

    from unittest.mock import AsyncMock, MagicMock, patch

    # Mock realtime adapter that yields text + audio + turn_complete
    mock_realtime = MagicMock()
    mock_realtime.send_user_text = AsyncMock()
    mock_realtime.capabilities = MagicMock(return_value=MagicMock(has_streaming_frames=False))

    n_audio_chunks = 5

    async def _fake_stream():
        yield TextDeltaEvent(token="Hello")
        for i in range(n_audio_chunks):
            yield AudioChunkEvent(
                data=bytes(48000),  # ~1s of PCM
                timestamp_ms=float(i * 200),
                duration_ms=200.0,
                encoding="pcm",
                sample_rate=24000,
            )
            await asyncio.sleep(0.01)
        yield TurnCompleteEvent(turn_id="test-turn-1")

    mock_realtime.stream_events = MagicMock(return_value=_fake_stream())

    # Push-model avatar: frames come from relay, not infer_stream
    class MockPushAvatar:
        def capabilities(self):
            from tth.core.types import AdapterCapabilities
            return AdapterCapabilities(has_streaming_frames=True)

        async def infer_stream(self, input, control, context):
            """Feed-only: no yields."""
            return
            yield

        async def relay_frames(self, stop: asyncio.Event):
            """Yield 10 frames then exit (simulates continuous stream ending)."""
            for i in range(10):
                await asyncio.sleep(0.02)
                yield _make_video_frame(ts=float(i * 20), idx=i)

        async def interrupt(self):
            pass

    sm = SessionManager()
    session = sm.create()

    orch = Orchestrator(realtime=mock_realtime, avatar=MockPushAvatar())
    output_q: asyncio.Queue = asyncio.Queue(maxsize=128)

    # start_session launches the persistent relay before run_turn
    await orch.start_session(session, output_q)
    await orch.run_turn(session, "Hello", TurnControl(), output_q)
    # Give the relay a moment to deliver its remaining frames then cancel it
    if session.relay_task and not session.relay_task.done():
        await asyncio.wait_for(session.relay_task, timeout=1.0)
    await session.cancel_relay()

    # Drain output_q
    events = []
    while not output_q.empty():
        events.append(output_q.get_nowait())

    audio_events = [e for e in events if isinstance(e, AudioChunkEvent)]
    video_events = [e for e in events if isinstance(e, VideoFrameEvent)]
    text_events = [e for e in events if isinstance(e, TextDeltaEvent)]
    turn_events = [e for e in events if isinstance(e, TurnCompleteEvent)]

    check("all audio events received", len(audio_events) == n_audio_chunks,
          f"got {len(audio_events)}/{n_audio_chunks}")
    check("video frames received", len(video_events) > 0,
          f"got {len(video_events)}")
    check("text delta received", len(text_events) == 1)
    check("turn complete received", len(turn_events) == 1)

    # Audio events should not be after turn_complete (i.e., not dropped/delayed)
    if turn_events and audio_events:
        turn_idx = events.index(turn_events[0])
        last_audio_idx = max(events.index(e) for e in audio_events)
        check("audio before turn_complete", last_audio_idx < turn_idx,
              f"last_audio={last_audio_idx}, turn={turn_idx}")


# ── Test 7: Orchestrator pull model (stub adapter) unchanged ─────────────────

async def test_orchestrator_pull_model_unchanged():
    print("\n[7] Orchestrator pull model (stub): works same as before")

    from unittest.mock import AsyncMock, MagicMock

    mock_realtime = MagicMock()
    mock_realtime.send_user_text = AsyncMock()
    mock_realtime.capabilities = MagicMock(return_value=MagicMock(has_streaming_frames=False))

    n_audio_chunks = 3

    async def _fake_stream():
        for i in range(n_audio_chunks):
            yield AudioChunkEvent(
                data=bytes(9600),  # 200ms of PCM
                timestamp_ms=float(i * 200),
                duration_ms=200.0,
                encoding="pcm",
                sample_rate=24000,
            )
        yield TurnCompleteEvent(turn_id="pull-test-1")

    mock_realtime.stream_events = MagicMock(return_value=_fake_stream())

    # Pull-model avatar (stub)
    stub_avatar = StubAvatarAdapter({})

    sm = SessionManager()
    session = sm.create()

    orch = Orchestrator(realtime=mock_realtime, avatar=stub_avatar)
    output_q: asyncio.Queue = asyncio.Queue(maxsize=128)

    await orch.run_turn(session, "Hello", TurnControl(), output_q)

    events = []
    while not output_q.empty():
        events.append(output_q.get_nowait())

    audio = [e for e in events if isinstance(e, AudioChunkEvent)]
    video = [e for e in events if isinstance(e, VideoFrameEvent)]

    check("audio events present", len(audio) == n_audio_chunks,
          f"got {len(audio)}/{n_audio_chunks}")
    check("video frames present", len(video) > 0, f"got {len(video)}")


# ── Test 8: Audio not starved when relay floods output_q ─────────────────────

async def test_relay_drain_window_full_second():
    """
    After stop.set(), relay_frames MUST give Simli the full 1-second drain window
    even if stop was set mid-poll (50ms timeout in flight).

    Regression for: stop.set() during a 50ms poll causes relay to exit after
    ≤50ms instead of 1 second, dropping frames that arrive 50-300ms later
    (Simli's pipeline latency after last audio chunk).
    """
    print("\n[DRAIN] stop.set() mid-poll must still honour full 1-second drain window")
    import asyncio as _asyncio
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY", "min_chunk_ms": 100})
    stop = _asyncio.Event()
    collected: list[VideoFrame] = []

    async def _run():
        async for f in adapter.relay_frames(stop):
            collected.append(f)

    relay = _asyncio.create_task(_run())

    # Let relay start and enter its 50ms poll
    await asyncio.sleep(0.04)

    # Set stop DURING a 50ms poll (the relay is mid-wait_for)
    stop.set()

    # Wait 200ms — if drain window works, late frames injected NOW should be delivered
    await asyncio.sleep(0.05)  # give relay a moment to enter drain mode
    late_frame = _make_video_frame(ts=9001.0, idx=999)
    await adapter._pending_frames.put(late_frame)

    # Give relay time to drain and exit
    try:
        await asyncio.wait_for(relay, timeout=3.0)
    except asyncio.TimeoutError:
        relay.cancel()
        check("relay exits after drain", False, "timed out")
        return

    # The late frame (arriving >50ms after stop.set) MUST be delivered
    late_delivered = any(f.frame_index == 999 for f in collected)
    check("late frame delivered (drain window ≥1s)", late_delivered,
          f"collected indices={[f.frame_index for f in collected]}")
    check("relay exited cleanly", not relay.cancelled())


async def test_audio_not_starved_by_relay():
    print("\n[8] Audio events not starved when relay floods output_q with video frames")

    from unittest.mock import AsyncMock, MagicMock

    mock_realtime = MagicMock()
    mock_realtime.send_user_text = AsyncMock()

    n_audio = 10

    async def _fake_stream():
        for i in range(n_audio):
            yield AudioChunkEvent(
                data=bytes(4800),
                timestamp_ms=float(i * 100),
                duration_ms=100.0,
                encoding="pcm",
                sample_rate=24000,
            )
            await asyncio.sleep(0.005)  # 5ms between audio chunks
        yield TurnCompleteEvent(turn_id="starve-test")

    mock_realtime.stream_events = MagicMock(return_value=_fake_stream())

    # Push adapter that produces frames VERY fast (faster than audio)
    class HighRatePushAvatar:
        def capabilities(self):
            from tth.core.types import AdapterCapabilities
            return AdapterCapabilities(has_streaming_frames=True)

        async def infer_stream(self, input, control, context):
            return
            yield

        async def relay_frames(self, stop: asyncio.Event):
            count = 0
            while not stop.is_set():
                await asyncio.sleep(0.005)  # 200fps — floods queue
                yield _make_video_frame(ts=float(count * 5), idx=count)
                count += 1
            # drain one more
            yield _make_video_frame(ts=float(count * 5), idx=count)

        async def interrupt(self): pass

    sm = SessionManager()
    session = sm.create()

    orch = Orchestrator(realtime=mock_realtime, avatar=HighRatePushAvatar())
    # Small queue to test backpressure
    output_q: asyncio.Queue = asyncio.Queue(maxsize=16)

    # Drain queue in background (simulating send_loop)
    drained: list = []
    async def _drain():
        while True:
            try:
                item = output_q.get_nowait()
                drained.append(item)
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.002)

    drain_task = asyncio.create_task(_drain())
    try:
        await asyncio.wait_for(
            orch.run_turn(session, "Hi", TurnControl(), output_q),
            timeout=10.0,
        )
    finally:
        drain_task.cancel()
        # Also drain remaining items
        while not output_q.empty():
            drained.append(output_q.get_nowait())

    audio_events = [e for e in drained if isinstance(e, AudioChunkEvent)]
    check("all audio events received (no starvation)", len(audio_events) == n_audio,
          f"got {len(audio_events)}/{n_audio}")
    check("turn_complete received", any(isinstance(e, TurnCompleteEvent) for e in drained))


# ── Test 9: drain window honours full 1-second after stop set mid-poll ───────

async def test_relay_drain_window_full_second():
    """After stop.set(), relay_frames MUST give Simli the full 1-second drain
    window even when stop is set while a 50ms poll is in flight.

    Bug scenario:
      1. relay enters wait_for(..., timeout=0.05)  ← 50ms poll
      2. stop.set() fires
      3. wait_for times out after ≤50ms
      4. BUG: relay checks `if stop.is_set()` → True → breaks immediately
      5. Late Simli frame (arrives 50-800ms after stop) is never delivered

    Fix: only break if `timeout >= _DRAIN_S` so the 50ms-timeout branch
    re-enters the loop with the 1-second drain timeout.
    """
    print("\n[9] relay_frames: drain window ≥1s even when stop set mid-poll")
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY", "min_chunk_ms": 100})
    stop = asyncio.Event()
    collected: list[VideoFrame] = []

    async def _run():
        async for f in adapter.relay_frames(stop):
            collected.append(f)

    relay = asyncio.create_task(_run())
    await asyncio.sleep(0.04)   # let relay enter a 50ms poll
    stop.set()                   # set stop WHILE the 50ms poll is in flight
    await asyncio.sleep(0.05)   # let the 50ms poll timeout fire (enters drain mode)

    # Inject a late frame — simulating Simli's ~300ms pipeline latency
    late_frame = _make_video_frame(ts=9001.0, idx=999)
    await adapter._pending_frames.put(late_frame)

    try:
        await asyncio.wait_for(relay, timeout=3.0)
    except asyncio.TimeoutError:
        relay.cancel()
        check("relay drain window ≥1s (exits cleanly)", False, "timed out — relay never exited")
        return

    late_delivered = any(f.frame_index == 999 for f in collected)
    check("late frame delivered in drain window", late_delivered,
          f"collected indices={[f.frame_index for f in collected]}")
    check("relay exited cleanly after drain", not relay.cancelled())


# ── Test 10: relay exits within ~1.2s even when idle frames flood continuously ─

async def test_relay_drain_no_infinite_loop():
    """Simli with handleSilence=True generates idle frames at ~25fps forever.
    relay_frames MUST exit after _DRAIN_S (1s) even when frames arrive every 40ms.
    Without time-based drain, per-frame logic resets the window → infinite loop.
    """
    print("\n[10] relay_frames: exits within 1.2s when idle frames flood after stop")
    adapter = SimliAvatarAdapter({"api_key_env": "SIMLI_API_KEY", "min_chunk_ms": 100})
    stop = asyncio.Event()
    collected: list[VideoFrame] = []

    async def _run():
        async for f in adapter.relay_frames(stop):
            collected.append(f)

    relay = asyncio.create_task(_run())

    # Signal stop immediately; then flood with idle frames at 25fps for 3 seconds
    stop.set()

    async def _flood():
        for i in range(75):  # 3 seconds worth at 25fps
            await asyncio.sleep(0.04)
            try:
                adapter._pending_frames.put_nowait(_make_video_frame(ts=float(i), idx=i))
            except asyncio.QueueFull:
                pass

    flood_task = asyncio.create_task(_flood())

    start = asyncio.get_running_loop().time()
    try:
        await asyncio.wait_for(relay, timeout=2.5)
    except asyncio.TimeoutError:
        relay.cancel()
        flood_task.cancel()
        check("relay exits within 1.2s with continuous idle frames", False,
              "timed out — infinite loop with handleSilence=True frames")
        return

    elapsed = asyncio.get_running_loop().time() - start
    flood_task.cancel()
    check(
        "relay exits within 1.2s with continuous idle frames",
        elapsed < 1.25,
        f"took {elapsed:.2f}s (expected < 1.25s)",
    )
    check("relay collected some idle frames", len(collected) > 0, f"got {len(collected)}")


# ── Test 11: capabilities() returns has_streaming_frames ────────────────────

async def test_capabilities():
    print("\n[8] AdapterCapabilities.has_streaming_frames")
    from tth.core.types import AdapterCapabilities
    from tth.adapters.avatar.stub import StubAvatarAdapter

    stub = StubAvatarAdapter({})
    check("stub has_streaming_frames=False", not stub.capabilities().has_streaming_frames)

    simli = SimliAvatarAdapter({})
    check("simli has_streaming_frames=True", simli.capabilities().has_streaming_frames)

    cap = AdapterCapabilities()
    check("default has_streaming_frames=False", not cap.has_streaming_frames)


# ── main ─────────────────────────────────────────────────────────────────────

async def main():
    tests = [
        test_infer_stream_feed_only,
        test_relay_frames_delivers,
        test_relay_frames_discard_then_new,
        test_relay_frames_stop_and_drain,
        test_relay_drain_window_full_second,
        test_relay_drain_no_infinite_loop,
        test_unhealthy_stub_frames_reach_relay,
        test_orchestrator_push_model_audio_flows,
        test_orchestrator_pull_model_unchanged,
        test_audio_not_starved_by_relay,
        test_capabilities,
    ]

    for t in tests:
        try:
            await t()
        except Exception as e:
            print(f"  [{FAIL}] EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            _results.append((t.__name__, False, str(e)))

    total = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = total - passed

    print(f"\n{'=' * 60}")
    if failed == 0:
        print(f"\033[32m ALL {total} CHECKS PASS\033[0m")
    else:
        print(f"\033[31m {failed}/{total} CHECKS FAILED\033[0m")
        for name, ok, detail in _results:
            if not ok:
                print(f"  ✗ {name}: {detail}")
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
