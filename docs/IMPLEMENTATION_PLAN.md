# TTH Implementation Plan (Lean v1, AI-Native, Extendable)

## 1) Goal
Build a real-time text-to-human video system that:
1. Accepts text input and streams synchronized audio + talking-head video output.
2. Supports controllable emotion and character traits at runtime.
3. Runs locally on a MacBook in API-only mode (no local model serving).
4. Keeps clean extension points for later self-hosted model serving.

## 2) Component Glossary (What each block means)
1. `Client`
   - Frontend or SDK consumer.
   - Sends user text and control updates.
   - Receives realtime audio/video/events.
2. `Gateway`
   - Public API entrypoint (`HTTP + WebSocket`).
   - Validates payloads, handles sessions, forwards events to orchestrator.
3. `Auth`
   - API key/token validation and basic rate limiting.
   - Keeps the service safe with minimal policy in v1.
4. `Orchestrator`
   - The core runtime engine.
   - Runs the generation pipeline (`LLM -> TTS -> Avatar`), handles interrupts, retries, and fallbacks.
5. `Control Plane`
   - Converts user controls (emotion/character) into provider-specific parameters.
   - Reports which controls were applied or downgraded.
6. `Adapters`
   - Provider wrappers behind a common interface.
   - Make each component switchable between `api` and `self_host` via config only.
7. `Providers`
   - Actual model endpoints or local workers (OpenAI, ElevenLabs, Tavus, local vLLM, etc.).

## 3) Lean v1 Architecture Decisions (Locked)
1. Use cascaded generation:
   - `text -> LLM response -> streaming TTS -> streaming avatar video`.
2. Start with one deployable backend service:
   - FastAPI app containing gateway, auth, orchestrator, adapter routing, and control mapping.
3. Keep session state in memory for v1:
   - Optional Redis integration behind an interface.
4. Default runtime for local development:
   - `API-only split mode` (`LLM=api`, `TTS=api`, `Avatar=api`).
5. Keep all provider dependencies behind adapters:
   - No provider-specific logic in route handlers or orchestrator core.
6. Keep local/self-host adapters present but optional:
   - They are loaded only in non-API profiles.

## 4) Revised v1 Repository Structure (Lean but Better)
```text
tth/
  README.md
  IMPLEMENTATION_PLAN.md
  SYSTEM_DESIGN_DIAGRAMS.md
  pyproject.toml
  .env.example
  Makefile

  app/
    main.py
    bootstrap.py

    api/
      deps.py
      routes/
        sessions.py
        stream.py
        generate.py
        health.py
        models.py
      middleware/
        auth.py
        rate_limit.py
        request_id.py
      ws/
        protocol.py
        event_codec.py

    domain/
      controls.py
      events.py
      media.py
      session.py
      capabilities.py

    orchestration/
      turn_engine.py
      sentence_buffer.py
      session_store.py
      cancellation.py
      fallback_policy.py
      timeout_budget.py

    control/
      resolver.py
      personas.py
      mappings/
        llm_prompt.py
        tts_openai.py
        tts_elevenlabs.py
        avatar_tavus.py
        avatar_heygen.py
        avatar_did.py

    providers/
      base.py
      registry.py
      llm/
        openai_realtime.py
        openai_responses.py
        local_vllm.py
        mock_llm.py
      tts/
        openai_tts.py
        elevenlabs_stream.py
        local_cosyvoice.py
        local_glmtts.py
        mock_tts.py
      avatar/
        stub_avatar.py
        tavus.py
        heygen.py
        did.py
        local_musetalk.py
        local_latentsync.py
        mock_avatar.py

    alignment/
      drift_controller.py
      timeline.py

    infra/
      config.py
      logging.py
      telemetry.py
      errors.py
      lifecycle.py

    observability/
      metrics.py
      tracing.py

  configs/
    base.yaml
    profiles/
      local_api_only_split.yaml
      local_api_only_managed.yaml
      dev_hybrid.yaml
      prod_self_host.yaml

  scripts/
    run_local_api_only.sh
    run_dev_hybrid.sh
    run_tests.sh

  tests/
    unit/
      test_contracts.py
      test_control_mapper.py
      test_adapter_registry.py
    integration/
      test_realtime_stream_api_only.py
      test_fallbacks.py
      test_interrupts.py
    e2e/
      test_text_to_av_session.py
```

### Why this structure is better
1. Clear boundaries:
   - `domain/*` has pure types only.
   - `api/*` owns transport/protocol concerns.
   - `providers/*` owns external API/model integrations.
2. Safer realtime protocol:
   - `api/ws/event_codec.py` is the single place for media encoding decisions (`json+base64` vs binary frames).
3. Better provider extensibility:
   - New provider files are added under `providers/{llm|tts|avatar}/` without touching orchestrator logic.
4. Easier testability:
   - `mock_*` providers make deterministic integration tests possible.
5. Lean runtime retained:
   - still one FastAPI process for v1.

## 5) Runtime Modes and Provider Selection
### 5.1 API-only split mode (default for MacBook)
```yaml
runtime:
  profile: local_api_only_split
  session_store: memory

components:
  llm:
    mode: api
    primary: openai_realtime
    fallback: [openai_responses]
  tts:
    mode: api
    primary: elevenlabs_stream
    fallback: [openai_tts]
  avatar:
    mode: api
    primary: tavus
    fallback: [heygen, did]
```

### 5.2 API-only managed mode (single avatar platform handles more logic)
```yaml
runtime:
  profile: local_api_only_managed
  session_store: memory

components:
  llm:
    mode: api
    primary: openai_realtime
  tts:
    mode: api
    primary: openai_tts
    disabled_when_avatar_handles_tts: true
  avatar:
    mode: api
    primary: tavus
    passthrough_text: true
```

### 5.3 Future hybrid/self-host mode (same interfaces)
1. Flip `mode` from `api` to `self_host` per component.
2. Keep orchestrator and API contracts unchanged.

## 6) Public API Contracts (Lean v1)
1. `POST /v1/sessions`
   - Input: persona/voice/avatar defaults.
   - Output: `session_id`, stream metadata.
2. `WS /v1/sessions/{session_id}/stream`
   - Inbound events: `user_text`, `control_update`, `interrupt`, `end_turn`.
   - Outbound events: `text_delta`, `audio_chunk`, `video_frame`, `turn_metrics`, `error`.
3. `POST /v1/generate`
   - Non-streaming batch generation.
4. `GET /v1/models`
   - Active providers, mode (`api`/`self_host`), capabilities.
5. `GET /v1/health`
   - Service health + provider adapter health.

### Shared control types
1. `EmotionControl`
   - `label`, `intensity`, `valence`, `arousal`.
2. `CharacterControl`
   - `persona_id`, `speech_rate`, `pitch_shift`, `expressivity`, `motion_gain`.
3. `RenderControl`
   - `fps`, `resolution`, `latency_mode`.

All events must include:
1. `schema_version`
2. `session_id`
3. `turn_id`
4. `timestamp_ms`

## 7) Adapter and Orchestrator Contracts
### 7.1 Adapter interface (all providers)
1. `load(config)`
2. `warmup()`
3. `infer_stream(input, control, context)`
4. `infer_batch(input, control)`
5. `health()`
6. `capabilities()`

### 7.2 Orchestrator responsibilities
1. Accept user turn.
2. Call LLM adapter and collect response text/hints.
3. Merge controls with persona defaults.
4. Call TTS adapter for chunked audio.
5. Call Avatar adapter for chunked frames.
6. Run drift controller and emit correction hints.
7. Stream results back to gateway.
8. Handle interrupts and cancellation immediately.
9. Trigger fallback provider chain on timeout/error.

## 8) Detailed One-Shot Implementation Steps (Lean v1)
1. Initialize project and dependencies (`FastAPI`, `Pydantic v2`, `httpx`, `websockets`, `structlog`, `pytest`).
2. Implement `infra/config.py` with YAML profile loading + env override.
3. Implement domain models in `app/domain/*` for controls, media, events, and capabilities.
4. Implement `api/ws/event_codec.py` for outbound/inbound realtime event encoding and schema checks.
5. Implement structured error model and unified error mapping in `infra/errors.py`.
6. Implement API key auth middleware and lightweight rate limiter in `api/middleware/*`.
7. Implement session store abstraction with in-memory backend.
8. Implement provider registry + dynamic provider loading by config in `providers/registry.py`.
9. Implement LLM providers:
   - OpenAI Realtime primary.
   - OpenAI Responses fallback.
10. Implement TTS providers:
   - ElevenLabs streaming primary.
   - OpenAI TTS fallback.
11. Implement Avatar providers:
    - Tavus primary.
    - HeyGen and D-ID fallbacks.
12. Implement control plane in `control/resolver.py` and `control/mappings/*`:
    - persona lookup,
    - control normalization,
    - provider capability-aware mapping and downgrade reporting.
13. Implement orchestration engine in `orchestration/turn_engine.py`:
    - LLM step -> control step -> TTS step -> avatar step.
14. Implement timeout budget manager and retry/fallback policy.
15. Implement interruption support:
    - cancellation tokens per turn,
    - immediate stop for downstream adapters.
16. Implement alignment drift controller with bounded correction policy.
17. Implement websocket stream route and multiplexer in `api/routes/stream.py`.
18. Implement HTTP routes (`sessions`, `generate`, `models`, `health`) under `api/routes/*`.
19. Implement service startup lifecycle:
    - adapter warmup,
    - health registry initialization.
20. Implement observability:
    - request/session logs,
    - stage latency metrics (`TTFA`, `TTFV`, drift).
21. Add mock providers (fake stream mode) for local dev without API keys.
22. Add scripts for local API-only run and test execution.
23. Add unit tests for domain models, control resolver, and provider registry.
24. Add integration tests for stream success, fallback, interrupt.
25. Add end-to-end test for full text->audio/video turn in fake mode.
26. Update README with exact run commands and profile examples.

## 9) Lean v1 Acceptance Criteria
1. Starts with one command in API-only mode on MacBook.
2. Runs with no local model serving and no GPU dependencies.
3. Streams text->audio/video through websocket.
4. Supports runtime emotion/character updates.
5. Handles interrupt within one turn without process restart.
6. Falls back to secondary provider when primary fails.
7. Exposes `GET /v1/health` and `GET /v1/models`.
8. Uses config-only switching between `api` and `self_host`.

## 10) v1.1+ Extension Path (keep v1 lean)
1. Split monolith into separate gateway/orchestrator/worker services.
2. Move session store from memory to Redis.
3. Enable self-host adapters (vLLM, CosyVoice, MuseTalk) in production profile.
4. Add trainer/eval services and model registry.
5. Add Kubernetes autoscaling and advanced SLO alerting.

## 11) Plan and Diagram File Locations
1. Plan file:
   - `/Users/leochli/Documents/tth/IMPLEMENTATION_PLAN.md`
2. Detailed diagrams:
   - `/Users/leochli/Documents/tth/SYSTEM_DESIGN_DIAGRAMS.md`
