# TTH Codebase Design

## 1) Purpose
TTH is a lean, AI-native realtime text-to-human pipeline with:
1. Text input.
2. Streamed text/audio/video output.
3. Emotion + character controls.
4. Config-driven provider swapping (`api` vs `self_host`) without orchestration changes.

## 2) Runtime Modes
1. `api_only_mac` (default):
   - `openai_realtime` (combined LLM+TTS) + `stub_avatar`.
   - Single WebSocket connection for reduced latency.
2. `offline_mock`:
   - `mock_llm` + `mock_tts` + `stub_avatar`.
   - No network required; deterministic for CI/local debugging.
   - Note: This profile uses the legacy LLM→TTS pipeline, not Realtime API.
3. Future profiles:
   - Self-hosted adapters by config only.

## 3) End-to-End Flow
1. `POST /v1/sessions` creates per-session state.
2. `WS /v1/sessions/{id}/stream` receives:
   - `user_text`, `control_update`, `interrupt`.
3. Orchestrator pipeline (Realtime API mode):
   - Realtime API WebSocket streams text_delta + audio_chunk events.
   - Audio chunks drive avatar frame generation.
4. Drift controller computes frame/audio timestamp drift.
5. Outbound events:
   - `text_delta`, `audio_chunk`, `video_frame`, `turn_complete`, `error`.

## 4) Folder Structure and Responsibilities
```text
src/tth/
  api/
    main.py                # app bootstrap, adapter wiring, lifespan
    routes.py              # HTTP/WS endpoints, turn task management
    schemas.py             # endpoint response/request models

  pipeline/
    orchestrator.py        # realtime turn engine (Realtime→Avatar)
    session.py             # session registry/state/cancellation

  adapters/
    base.py                # adapter interface contract
    realtime/
      openai_realtime.py   # OpenAI Realtime API (combined LLM+TTS via WebSocket)
    llm/
      openai_api.py        # live OpenAI LLM stream (legacy, for offline_mock)
      mock_llm.py          # deterministic offline LLM stream
    tts/
      openai_tts.py        # live OpenAI TTS stream (legacy, for offline_mock)
      mock_tts.py          # deterministic offline pseudo-audio stream
    avatar/
      stub.py              # placeholder frame stream with sync-friendly timestamps

  control/
    mapper.py              # control merge + provider mappings + prompt style hints
    personas.py            # persona defaults

  alignment/
    drift.py               # drift metrics/tracking

  core/
    config.py              # YAML+env settings loader
    types.py               # canonical data/event/control types
    registry.py            # adapter registration/lookup
    logging.py             # structlog setup
```

## 5) Core Interfaces
1. Adapter contract (`AdapterBase`):
   - `load`, `warmup`, `infer_stream`, `infer_batch`, `health`, `capabilities`.
   - Note: Realtime adapters use a session-scoped WebSocket and have different methods:
     - `connect()`, `send_user_text()`, `stream_events()`, `cancel_response()`, `close()`
2. Session contract:
   - one active turn task per session.
   - `cancel_current_turn()` for interrupts/new turns.
3. Control contract:
   - `resolve(user_control, persona_defaults)`.
   - `merge_controls(pending_control, turn_control)` for `control_update`.

## 6) Event Transport Contract
1. Media bytes in outbound events are base64-serialized via `field_serializer`.
2. `audio_chunk` fields:
   - `data`, `timestamp_ms`, `duration_ms`, `encoding`, `sample_rate`.
   - `encoding` is "pcm" for Realtime API output (24kHz, 16-bit, mono).
3. `video_frame` fields:
   - `data`, `timestamp_ms`, `frame_index`, `width`, `height`, `content_type`, `drift_ms`.
4. Stub avatar uses `content_type="raw_rgb"` intentionally.

## 7) Testing Strategy (Standalone Phases)
1. `scripts/phase_01_unit.py`:
   - Runs `pytest` for core contracts and behaviors.
2. `scripts/phase_02_offline_smoke.py`:
   - In-process app, single-turn smoke, checks output quality and event validity.
3. `scripts/phase_03_offline_multiturn.py`:
   - Multi-turn session, validates `control_update` application and continuity.
4. `scripts/phase_04_live_openai.py`:
   - Live validation with real OpenAI Realtime API calls.
   - Skips when key missing or DNS/network unavailable.
5. `scripts/run_phased_tests.py`:
   - Runs phases sequentially (`--live` to include phase 4).

## 8) Run Commands
1. Offline phased tests:
   - `.venv/bin/python scripts/run_phased_tests.py`
2. Include live phase:
   - `.venv/bin/python scripts/run_phased_tests.py --live`
3. Make targets:
   - `make phase`
   - `make phase-live`

## 9) Output Quality Checks
Offline phase scripts assert:
1. Non-empty coherent text.
2. Non-zero audio chunks and payload bytes.
3. Non-zero video frame count.
4. Drift kept within practical stub-mode budget.
5. Multi-turn behavior works; `control_update` affects next turn.

## 10) Extension Guide
To add a provider:
1. Implement adapter under modality folder (or `adapters/realtime/` for combined LLM+TTS).
2. Decorate with `@register("provider_name")`.
3. Add mapping logic in `control/mapper.py` if needed.
4. Switch `config/base.yaml` or profile `components.<modality>.primary`.
5. Re-run phased tests.

### Adding a Realtime Adapter (Combined LLM+TTS)
Realtime adapters have a different lifecycle than streaming adapters:
```python
@register("my_realtime")
class MyRealtimeAdapter(AdapterBase):
    async def connect(self, system_instructions: str, voice: str) -> None:
        """Establish connection ONCE at session start."""
        ...

    async def send_user_text(self, text: str) -> None:
        """Send user message and trigger response."""
        ...

    async def stream_events(self) -> AsyncIterator[TextDeltaEvent | AudioChunkEvent | TurnCompleteEvent]:
        """Yield events until TurnCompleteEvent."""
        ...

    async def cancel_response(self) -> None:
        """Cancel current response (for interrupt handling)."""
        ...

    async def close(self) -> None:
        """Close connection at session end."""
        ...
```

### Adding a Streaming Adapter (Avatar, or standalone LLM/TTS)
```python
@register("my_avatar")
class MyAvatarAdapter(AdapterBase):
    async def infer_stream(self, input, control, context):
        # Yield VideoFrame
        yield frame

    async def health(self):
        return HealthStatus(healthy=True)
```
