# TTH — Text-to-Human Video System

## Overview

TTH is a real-time text-to-human video system with emotion and character controllability. The system is designed with an API-first architecture that allows swapping between external APIs and self-hosted models by changing only configuration — no code changes required.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          CLIENT (browser / CLI)                          │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │  HTTP POST /v1/sessions
                                 │  WS   /v1/sessions/{id}/stream
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        API GATEWAY  (FastAPI)                            │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  ┌──────────────┐  │
│  │ Auth/RateLimit│ │ Schema Valid │  │ Session Mgr │  │ WS Hub       │  │
│  └─────────────┘  └──────────────┘  └─────────────┘  └──────────────┘  │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ UserTurnEvent
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR (async)                              │
│                                                                          │
│  UserText ──► [Realtime API (LLM+TTS combined)] ──► Text + Audio        │
│                                                         │                │
│                                                         ▼                │
│                                               [Avatar Stage]             │
│                                                         │                │
│                                                   VideoFrames            │
│                                                         │                │
│                                            [A/V Mux + Drift Ctrl]        │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ audio_chunk + video_frame events
                                 ▼
                            CLIENT STREAM
```

**Key Change**: The system now uses OpenAI's Realtime API which combines LLM and TTS into a single WebSocket connection, significantly reducing latency compared to the previous LLM → TTS pipeline.

## Project Structure

```
tth/
├── pyproject.toml           # Project dependencies and build config
├── Makefile                 # Development commands (dev, test, lint, etc.)
├── .env                     # Environment variables (API keys, profile)
├── .env.example             # Template for environment variables
│
├── config/
│   ├── base.yaml            # Default configuration (OpenAI Realtime + stub avatar)
│   └── profiles/
│       ├── api_only_mac.yaml    # v1: API-only profile (default)
│       └── offline_mock.yaml    # Testing: Mock adapters (no API calls)
│
├── src/tth/
│   ├── __init__.py
│   │
│   ├── core/                # Shared foundation (no external deps)
│   │   ├── types.py         # All Pydantic models: controls, events, media
│   │   ├── config.py        # YAML + env loading with Pydantic Settings
│   │   ├── registry.py      # Adapter registry (name → class)
│   │   └── logging.py       # Structlog configuration with trace IDs
│   │
│   ├── adapters/            # Provider implementations
│   │   ├── base.py          # AdapterBase ABC: load/warmup/infer_stream/health
│   │   ├── realtime/        # Combined LLM+TTS adapters
│   │   │   └── openai_realtime.py  # OpenAI Realtime API (WebSocket)
│   │   ├── llm/
│   │   │   ├── openai_api.py    # OpenAI Chat Completions (streaming)
│   │   │   └── mock_llm.py      # Deterministic mock for offline testing
│   │   ├── tts/
│   │   │   ├── openai_tts.py    # OpenAI TTS (streaming PCM)
│   │   │   └── mock_tts.py      # Pseudo-audio mock for offline testing
│   │   └── avatar/
│   │       └── stub.py          # Placeholder frames (content_type="raw_rgb")
│   │
│   ├── control/             # Control plane: emotion + character mapping
│   │   ├── mapper.py        # Unified → provider-specific parameter mapping
│   │   └── personas.py      # Named persona presets (default, professional, etc.)
│   │
│   ├── pipeline/            # Async turn engine
│   │   ├── orchestrator.py  # Stage sequencing, backpressure, cancellation
│   │   └── session.py       # Per-session state machine + drift controller
│   │
│   ├── alignment/           # A/V synchronization
│   │   └── drift.py         # Timestamp tracking, drift estimation
│   │
│   └── api/                 # FastAPI application
│       ├── main.py          # App factory, lifespan, adapter loading
│       ├── routes.py        # HTTP + WebSocket endpoints
│       └── schemas.py       # Request/response Pydantic models
│
├── tests/                   # pytest test suite
│   ├── test_types.py        # Core types validation
│   ├── test_mapper.py       # Control mapping logic
│   └── test_adapters.py     # Adapter behavior tests
│
├── scripts/                 # Development and testing scripts
│   ├── run_phased_tests.py  # Master test runner
│   ├── phase_01_unit.py     # Unit tests
│   ├── phase_02_offline_smoke.py
│   ├── phase_03_offline_multiturn.py
│   ├── phase_04_live_openai.py
│   ├── demo.py              # End-to-end demo script
│   ├── interactive_test.py  # Test pipeline with playable audio output
│   └── interactive_demo.py  # Interactive demo with playable output
│
└── docs/                    # Documentation
    ├── ARCHITECTURE.md      # This file
    ├── ADAPTERS.md          # Adapter documentation
    ├── REALTIME_API.md      # Realtime API integration guide
    └── MEMORY.md            # Operational notes
```

## Core Components

### 1. Core Types (`src/tth/core/types.py`)

All shared data models using Pydantic v2:

- **Controls**: `EmotionControl`, `CharacterControl`, `TurnControl`
- **Media**: `AudioChunk`, `VideoFrame`
- **Events (outbound)**: `TextDeltaEvent`, `AudioChunkEvent`, `VideoFrameEvent`, `TurnCompleteEvent`, `ErrorEvent`
- **Events (inbound)**: `UserTextEvent`, `InterruptEvent`, `ControlUpdateEvent`
- **Status**: `HealthStatus`, `AdapterCapabilities`

Key design decisions:
- `bytes` fields in events use `@field_serializer` to encode as base64 in JSON
- `AudioChunk.duration_ms` is computed from byte count at known bitrate (never 0)
- `VideoFrame.content_type` signals encoding: `"raw_rgb"` for stub, `"jpeg"` for real adapters

### 2. Config System (`src/tth/core/config.py`)

Pydantic Settings with YAML + environment variable merging:

```yaml
# config/base.yaml
components:
  realtime:
    primary: openai_realtime
    model: gpt-4o-realtime-preview
  avatar:
    primary: stub_avatar
```

API keys are loaded from environment only (never in YAML):
- `OPENAI_API_KEY` (required for Realtime API)

### 3. Adapter Registry (`src/tth/core/registry.py`)

Simple decorator-based registry for swapping providers:

```python
@register("openai_realtime")
class OpenAIRealtimeAdapter(AdapterBase): ...

@register("elevenlabs")
class ElevenLabsTTSAdapter(AdapterBase): ...

# Usage:
adapter = registry.create(config["primary"], config)
```

### 4. Adapter Base (`src/tth/adapters/base.py`)

Abstract base class all adapters must implement:

```python
class AdapterBase(ABC):
    async def load(self) -> None: ...
    async def warmup(self) -> None: ...
    async def infer_stream(self, input, control, context) -> AsyncIterator: ...
    async def health(self) -> HealthStatus: ...
    def capabilities(self) -> AdapterCapabilities: ...
```

**Note**: Realtime adapters have a different lifecycle (session-scoped WebSocket) and don't use `infer_stream()` directly.

### 5. Control Mapper (`src/tth/control/mapper.py`)

Maps unified `TurnControl` to provider-specific parameters:

```python
# Realtime API: emotion → voice selection
def map_emotion_to_realtime_voice(emotion, character) -> str:
    return VOICE_MAP[emotion.label]

# LLM: emotion + character → system prompt injection
def build_llm_system_prompt(control, persona_name) -> str: ...
```

### 6. Orchestrator (`src/tth/pipeline/orchestrator.py`)

Simplified orchestrator using the Realtime API:

```
Realtime API                    Avatar Stage
    │                                │
    │  text_delta + audio_chunk      │
    ├──────────────────────────────► │
    │                                │
    │  Audio drives video generation │
    │  No sentence buffering needed  │
```

Key features:
- Single WebSocket connection for LLM+TTS (lower latency)
- Audio chunks drive avatar frame generation
- Real-time text deltas for immediate display

### 7. Session State Machine (`src/tth/pipeline/session.py`)

```
IDLE → LLM_RUN → TTS_RUN → AVATAR_RUN → STREAMING_OUTPUT → TURN_COMPLETE → IDLE
          │                       │                │
          └─────── error ─────────┴────────────────┴──► TURN_ERROR
```

Features:
- Turn cancellation via `asyncio.Task.cancel()`
- Pending control storage for `ControlUpdateEvent`
- Drift controller instance per session

### 8. Drift Controller (`src/tth/alignment/drift.py`)

Tracks audio vs video timestamp drift:

```python
class DriftController:
    def update(self, audio_ts_ms, video_ts_ms) -> float:
        drift = video_ts_ms - audio_ts_ms
        self._history.append(drift)
        return drift

    def mean_drift_ms(self) -> float: ...
    def is_within_budget(self, budget_ms=80.0) -> bool: ...
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/sessions` | POST | Create new session |
| `/v1/sessions/{id}/stream` | WS | Bidirectional real-time stream |
| `/v1/health` | GET | Per-component health status |
| `/v1/models` | GET | Active adapter capabilities |

### WebSocket Protocol

**Inbound events (client → server):**
```json
{"type": "user_text", "text": "Hello!", "control": {...}}
{"type": "interrupt"}
{"type": "control_update", "control": {...}}
```

**Outbound events (server → client):**
```json
{"type": "text_delta", "token": "Hello"}
{"type": "audio_chunk", "data": "<base64>", "timestamp_ms": 1000, "duration_ms": 256, "encoding": "pcm", "sample_rate": 24000}
{"type": "video_frame", "data": "<base64>", "frame_index": 0, "drift_ms": 5.0, ...}
{"type": "turn_complete", "turn_id": "uuid"}
{"type": "error", "code": "turn_error", "message": "..."}
```

## Testing

### Phase-based Testing

```bash
# Offline tests (no API calls)
make phase
# or: uv run python scripts/run_phased_tests.py

# Include live OpenAI validation
make phase-live
# or: uv run python scripts/run_phased_tests.py --live
```

### Unit Tests

```bash
make test
# or: uv run pytest tests/ -v
```

### Demo

```bash
# Terminal 1: Start server
make dev

# Terminal 2: Run demo
make demo
```

## Configuration Profiles

### v1 API-Only (Default)

```yaml
# config/base.yaml
components:
  realtime:
    primary: openai_realtime
    model: gpt-4o-realtime-preview
  avatar:
    primary: stub_avatar
```

### Switching Providers

To switch to a different avatar provider:
```yaml
# config/profiles/api_only_mac.yaml
components:
  avatar:
    primary: heygen          # requires HEYGEN_API_KEY + avatar_id
```
```bash
# .env
HEYGEN_API_KEY=...
```

No code changes required.

## Cost Estimates

| Component | Model | Cost |
|-----------|-------|------|
| Realtime (LLM+TTS) | gpt-4o-realtime-preview | ~$0.06/min audio output |
| Avatar | stub | $0 |

Typical demo session (~5 turns, ~30 seconds audio):
- Realtime API: ~$0.03
- **Total: ~$0.03 per conversation**

## Future Extensions (v2)

### Self-Hosted Adapters

```python
@register("cosyvoice_local")
class CosyVoiceLocalAdapter(AdapterBase):
    async def load(self):
        from cosyvoice import CosyVoice
        self.model = CosyVoice("pretrained/CosyVoice3-0.5B")
```

### Training Infrastructure

```
packages/training/
├── systems/          # LightningModules
├── datamodules/      # Data loading
└── datasets/         # Dataset definitions
```

## Development

```bash
# Install dependencies
make install

# Run linter
make lint

# Format code
make fmt

# Run all offline tests
make phase
```
