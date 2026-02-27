# TTH Memory (Operational Notes)

## Stable Defaults
1. Config profile default: `api_only_mac`.
2. Session transport: WebSocket JSON events.
3. Media payloads are base64 in event JSON.
4. Pipeline: Realtime API (combined LLM+TTS) → Avatar.

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
The `offline_mock` profile is designed for offline testing but currently requires the Realtime API because the orchestrator is hardcoded to use `OpenAIRealtimeAdapter`. This means:
- Phase 2 passes because it only checks for audio/video output
- Phase 3 fails because it expects mock adapter behavior (e.g., "exciting" in text)
- The profile config has `llm:` and `tts:` components but these are ignored

**Future fix**: Create a mock realtime adapter or make the orchestrator configurable.

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
