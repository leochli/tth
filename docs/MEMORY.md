# TTH Memory (Operational Notes)

## Stable Defaults
1. Config: base.yaml uses `openai_realtime` + `simli` avatar (with `stub_avatar` fallback).
2. Session transport: WebSocket JSON events.
3. Media payloads are base64 in event JSON.
4. Pipeline: Realtime API (combined LLM+TTS) → Simli Avatar.

## Key Commands
1. Run unit tests:
   - `make test` or `.venv/bin/python -m pytest tests/ -v`
2. Run offline phased tests:
   - `make phase` or `.venv/bin/python scripts/run_phased_tests.py`
3. Run with live OpenAI phase:
   - `make phase-live` or `.venv/bin/python scripts/run_phased_tests.py --live`
4. Run only live phase:
   - `.venv/bin/python scripts/phase_04_live_openai.py`

## Important Implementation Decisions
1. One active turn task per session:
   - New `user_text` cancels previous task.
2. `control_update` is stored as `pending_control` and merged into next turn.
3. Realtime API (combined LLM+TTS via WebSocket) replaces separate LLM→TTS pipeline.
4. Stub avatar intentionally emits `raw_rgb` payloads for no-external-video testing.
5. Realtime adapter is session-scoped: `connect()` once, reuse for multiple turns.

## Known Issues

### `offline_mock` Profile Compatibility
The `offline_mock` profile overrides the avatar to `stub_avatar` so tests run without Simli's API. The Realtime API adapter (`openai_realtime`) is still used, so `OPENAI_API_KEY` is required even in offline mode.

**Future fix**: Create a mock realtime adapter or make the orchestrator configurable for fully offline testing.

### Realtime API Limitations
The Realtime API does not support:
- `CharacterControl.speech_rate`
- `CharacterControl.pitch_shift`
- `CharacterControl.expressivity`
- `CharacterControl.motion_gain`

These parameters are logged as warnings when non-default values are used.

## Known Environment Constraints
1. In this sandbox, binding listen ports may be blocked.
2. In this sandbox, external DNS/network to provider APIs may be blocked.
3. In this sandbox, `uv run` may fail due `nice(5)` permission behavior.
4. Use `.venv/bin/python ...` directly when needed.

## Validation Baseline
1. `phase_01_unit.py`: must pass (70 tests).
2. `phase_02_offline_smoke.py`: must pass with coherent text/audio/video events.
3. `phase_03_offline_multiturn.py`: currently fails due to offline_mock profile issue.
4. `phase_04_live_openai.py`: pass when network+key available, skip otherwise.

## Security Notes
1. Do not hardcode API keys in source.
2. Keep secrets only in `.env` (local) or environment variables in deployment.
3. If a key is ever pasted in chat/plaintext, rotate/revoke it.

## Audio Streaming in Browsers

### MP3 is NOT suitable for low-latency streaming
- MP3 has frame headers (~417 bytes per frame at 128kbps)
- Arbitrary byte boundaries break frames
- Browsers cannot decode partial MP3 chunks reliably

### Use PCM for streaming audio
- Raw uncompressed audio - no frame boundaries
- OpenAI Realtime API outputs PCM (24kHz, 16-bit, mono)
- Trade-off: ~3x larger than MP3, but acceptable for voice

### Implementation pattern
1. Server: Use PCM format, pass encoding/sample_rate through pipeline
2. Client: Convert Int16 PCM to Float32, schedule with nextStartTime
3. Use scheduled playback to avoid gaps between chunks

## Cloud Avatar System

### Audio Resampling
- LivePortrait requires 16kHz audio input
- Realtime API outputs 24kHz PCM
- Use scipy.signal.resample for high-quality conversion
- Buffer audio chunks until minimum duration (200ms default) for better lip sync

### WebSocket Protocol
- Session-scoped connection (init → chunks → end)
- `interrupt` message clears cloud-side buffers
- Frame queue with backpressure (drop oldest when full)

### Latency Budget
- Target: <300ms for avatar generation
- Cold start: 10-30s (mitigate with keep_warm=1)
- Network RTT: ~50-100ms depending on region

### Adapter Interrupt Pattern
```python
async def interrupt(self) -> None:
    """Clear buffers on interrupt."""
    self._buffer.reset()
    # Clear pending frames queue
    while not self._pending_frames.empty():
        try:
            self._pending_frames.get_nowait()
        except asyncio.QueueEmpty:
            break
    # Notify cloud service
    if self._ws and self._ws.open:
        await self._ws.send(json.dumps({"type": "interrupt", ...}))
```

### Client-Side A/V Sync
1. Audio: Schedule PCM chunks with Web Audio API for gapless playback
2. Video: Queue frames, select by timestamp matching audio position
3. Drift: Track difference between audio time and frame timestamp
