# Plan: Text-to-Human Video System (TTH) — Lean API-First

## Context

Build a real-time text-to-human video system with emotion and character controllability.
**Strategy**: Ship a working lean v1 on MacBook using only external APIs, with all abstractions correct so that swapping to self-hosted models requires only adding adapters + changing config — no architectural changes.

---

## System Design Diagrams

### Diagram 1: Top-Level Architecture (v1 API-Only → Future Self-Host)

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
│  UserText ──► [LLM Stage] ──► [Control Merge] ──► [TTS Stage]           │
│                                                         │                │
│                                                    AudioChunks           │
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

═══════════════════════════  PROVIDER LAYER  ════════════════════════════

  v1 API-Only (Mac)                      v2+ Self-Host (GPU Server)
  ─────────────────                      ──────────────────────────
  LLM:    OpenAI gpt-4o-mini API         LLM:    Qwen3 via vLLM
  TTS:    OpenAI tts-1 API               TTS:    CosyVoice3 (local)
  Avatar: stub_avatar (placeholder)      Avatar: MuseTalk 1.5 (local)

  ← swapped by changing one YAML line, no code changes →
```

---

### Diagram 2: Component Decomposition (Package Map)

```
src/tth/
│
├── core/              ← shared foundation (no deps on adapters or pipeline)
│   ├── config.py      ← YAML + env loading, typed with Pydantic Settings
│   ├── registry.py    ← adapter registry (name → class)
│   ├── types.py       ← EmotionControl, CharacterControl, all shared types
│   └── logging.py     ← structlog, trace IDs
│
├── adapters/          ← one file per provider, all implement AdapterBase
│   ├── base.py        ← AdapterBase ABC: load/warmup/infer_stream/health
│   ├── llm/           ← OpenAI, Anthropic, vLLM (stub)
│   ├── tts/           ← openai_tts (v1), elevenlabs (v2), cosyvoice_local (v2)
│   └── avatar/        ← stub_avatar (v1), heygen (v2), musetalk_local (v2)
│
├── control/           ← maps unified controls → provider-specific params
│   ├── mapper.py      ← EmotionControl + CharacterControl → provider fields
│   └── personas.py    ← named persona presets (defaults per persona_id)
│
├── pipeline/          ← async turn engine
│   ├── orchestrator.py ← stage sequencing, backpressure, cancel
│   └── session.py     ← per-session state machine
│
├── alignment/         ← A/V sync
│   └── drift.py       ← timestamps, drift estimation, correction hints
│
├── api/               ← FastAPI app
│   ├── main.py
│   ├── routes.py      ← POST /v1/sessions, WS /v1/sessions/{id}/stream, GET /v1/health, /v1/models
│   └── schemas.py     ← request/response Pydantic models
│
└── training/          ← v2: PyTorch Lightning fine-tuning (stubs in v1)
    ├── systems/
    ├── datamodules/
    └── datasets/
```

---

### Diagram 3: Real-Time Turn Sequence (API-only)

```
Client          Gateway         Orchestrator     LLM API      TTS API     Avatar API
  │                │                 │               │            │            │
  │─ WS connect ──►│                 │               │            │            │
  │◄── session_id ─│                 │               │            │            │
  │                │                 │               │            │            │
  │─ user_text ───►│                 │               │            │            │
  │  + controls    │──UserTurnEvent─►│               │            │            │
  │                │                 │──POST /chat──►│            │            │
  │                │                 │◄─ text delta ─│            │            │
  │◄─ text_delta ──│◄────────────────│               │            │            │
  │  (streamed)    │                 │               │            │            │
  │                │                 │  [control merge: emotion+character → TTS params]
  │                │                 │──── POST /v1/text-to-speech/stream ────►│
  │                │                 │                            │            │
  │                │                 │◄──── audio_chunk + ts ─────│            │
  │◄─ audio_chunk ─│◄────────────────│                            │            │
  │                │                 │  [control merge: emotion+character → avatar params]
  │                │                 │────────── POST /avatar/stream ─────────►│
  │                │                 │◄──────────── video_frame ───────────────│
  │◄─ video_frame ─│◄────────────────│                                         │
  │  (repeated     │                 │  [drift controller: check audio_ts vs video_ts]
  │   for each     │                 │◄── drift correction hints               │
  │   chunk)       │                 │                                         │
  │                │                 │                                         │
  │─ interrupt ───►│──InterruptEvent►│──── cancel() ──────────────────────────►│
  │◄─ turn_stopped─│◄────────────────│                                         │
```

---

### Diagram 4: Control Plane Detail

```
  ┌──────────────┐   ┌──────────────────┐   ┌──────────────────┐
  │  User Input  │   │  Persona Default  │   │  LLM Style Hints │
  │ EmotionCtrl  │   │ (from persona_id) │   │ (extracted from  │
  │ CharacterCtrl│   │                  │   │  response text)  │
  └──────┬───────┘   └────────┬─────────┘   └────────┬─────────┘
         │                    │                        │
         └────────────────────┴────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ Control Merger  │  (priority: user > persona > llm_hints)
                    │ mapper.py       │
                    └────────┬────────┘
                             │ NormalizedControl
                    ┌────────┴────────┐
                    │                 │
                    ▼                 ▼
           ┌──────────────┐  ┌──────────────────┐
           │ TTS Mapper   │  │  Avatar Mapper    │
           │              │  │                   │
           │ emotion →    │  │ emotion →         │
           │  EL voice    │  │  Tavus persona    │
           │  stability   │  │  style params     │
           │  style_exag  │  │                   │
           │              │  │ character →       │
           │ character →  │  │  motion_gain      │
           │  speed/pitch │  │  identity_ref     │
           └──────────────┘  └──────────────────┘
                    │                 │
                    ▼                 ▼
            to TTS adapter    to Avatar adapter
                    │                 │
                    ▼                 ▼
           ┌──────────────────────────────────────┐
           │   AppliedControlReport               │
           │   { applied: [...], downgraded: [...] }│
           │   (returned in turn_metrics event)   │
           └──────────────────────────────────────┘
```

---

### Diagram 5: Adapter Interface + Extension Model

```
                     AdapterBase (abstract)
                     ┌────────────────────────────┐
                     │ + load(config)             │
                     │ + warmup()                 │
                     │ + infer_stream(input,ctrl) │
                     │ + infer_batch(input,ctrl)  │
                     │ + health() → HealthStatus  │
                     │ + capabilities() → Caps    │
                     └────────────┬───────────────┘
              ┌──────────────┬────┴──────────────┐
              ▼              ▼                    ▼
        LLMAdapter      TTSAdapter          AvatarAdapter
              │              │                    │
      ┌───────┴──────┐  ┌────┴─────┐   ┌──────────┴──────────┐
      │ openai_api   │  │ eleven-  │   │ tavus_cvi (v1)      │
      │ (v1)         │  │ labs (v1)│   │ heygen (v1)         │
      │              │  │          │   │ musetalk_local (v2)  │
      │ vllm_local   │  │ openai_  │   │ latentsync (v2)     │
      │ (v2 stub)    │  │ tts (v1) │   │ livatar1 (v3 stub)  │
      │              │  │          │   └─────────────────────┘
      │ qwen3 (v2)   │  │ cosy-    │
      └──────────────┘  │ voice(v2)│
                        └──────────┘

  Registry:
  ┌─────────────────────────────────────────────────┐
  │  "openai_api"      → OpenAILLMAdapter           │
  │  "elevenlabs"      → ElevenLabsTTSAdapter        │
  │  "tavus_cvi"       → TavusCVIAvatarAdapter       │
  │  "cosyvoice_local" → CosyVoiceLocalTTSAdapter    │  ← add in v2
  │  "musetalk_local"  → MuseTalkLocalAvatarAdapter  │  ← add in v2
  └─────────────────────────────────────────────────┘
  Config change to switch:
    tts.primary: elevenlabs  →  tts.primary: cosyvoice_local
```

---

### Diagram 6: Session State Machine

```
   ┌─────────┐
   │  START  │
   └────┬────┘
        │ POST /v1/sessions
        ▼
   ┌─────────┐
   │  IDLE   │◄────────────────────────────┐
   └────┬────┘                             │
        │ user_text received               │
        ▼                                  │
   ┌────────────┐                          │
   │  LLM_RUN   │── provider_error ──► TURN_ERROR
   └─────┬──────┘                          │
         │ response planned                │ recoverable
         ▼                                 │
   ┌────────────┐                          │
   │ CTRL_MERGE │                          │
   └─────┬──────┘                          │
         │                                 │
         ▼                                 │
   ┌────────────┐                          │
   │  TTS_RUN   │── provider_error ──► TURN_ERROR ──────────┘
   └─────┬──────┘
         │ audio chunks flowing
         ▼
   ┌─────────────┐
   │ AVATAR_RUN  │── provider_error ──► TURN_ERROR
   └─────┬───────┘
         │ video frames flowing
         ▼
   ┌──────────────────┐
   │ STREAMING_OUTPUT │
   └─────┬──────┬─────┘
         │      │ interrupt
     end_turn   ▼
         │   INTERRUPTED ──► IDLE (after cancel_ack)
         ▼
   ┌───────────────┐
   │ TURN_COMPLETE │──► IDLE
   └───────────────┘
```

---

### Diagram 7: File Dependency Graph (implementation order)

```
  1. core/types.py          ← no deps, define all shared types first
  2. core/config.py         ← depends on types
  3. core/registry.py       ← depends on types
  4. core/logging.py        ← no deps
  5. adapters/base.py       ← depends on core/types
  6. control/mapper.py      ← depends on core/types
  7. control/personas.py    ← depends on core/types
  8. adapters/llm/openai_api.py   ← depends on adapters/base
  9. adapters/tts/elevenlabs.py   ← depends on adapters/base
 10. adapters/avatar/tavus_cvi.py ← depends on adapters/base
 11. alignment/drift.py     ← depends on core/types
 12. pipeline/session.py    ← depends on core/types, control/mapper
 13. pipeline/orchestrator.py ← depends on session + all adapters
 14. api/schemas.py         ← depends on core/types
 15. api/routes.py          ← depends on orchestrator + schemas
 16. api/main.py            ← depends on routes, loads config + registry
```

---

## Part 1: v1 Lean Implementation (API-Only, MacBook)

### Goal
Single `uvicorn` process on Mac, no GPU, no local models. All AI inference via remote APIs.
Working demo: send text → get real-time LLM response + streamed audio output.

### Cost-Effective Stack Decision

**Single provider key required: OpenAI only.**

| Component | Provider | Model | Cost | Reason |
|---|---|---|---|---|
| LLM | OpenAI | `gpt-4o-mini` | ~$0.15/1M input | Cheapest capable chat model; same key as TTS |
| TTS | OpenAI | `tts-1` | $0.015/1000 chars | Reuses OpenAI key; ~$0.003 per average response |
| Avatar | **Stubbed** | N/A | $0 | Placeholder frames tonight; plug in real API when needed |

**Why this stack:**
- One API key (`OPENAI_API_KEY`) is the only credential needed to run the demo
- A 200-character response costs < $0.001 in TTS, < $0.001 in LLM — negligible
- Avatar stub emits realistic event structure so the full pipeline is exercisable end-to-end
- When ready to add video: add HeyGen or Tavus adapter and change one config line

**Upgrade path (add when needed):**
- Better LLM quality: switch `llm.primary: anthropic_claude` (add `ANTHROPIC_API_KEY`)
- Better TTS: switch `tts.primary: elevenlabs` (add `ELEVENLABS_API_KEY`)
- Real avatar video: switch `avatar.primary: heygen` or `tavus_cvi` (add respective key)

### Tech Stack (v1)
- **Python 3.11+**, `uv` for package management
- **FastAPI** + **uvicorn** for serving
- **Pydantic v2** for all data models + settings
- **httpx** for async HTTP calls to providers
- **structlog** for logging
- **pytest** + **pytest-asyncio** for tests
- **LLM**: OpenAI `gpt-4o-mini`
- **TTS**: OpenAI `tts-1` (streaming)
- **Avatar**: Stub adapter (placeholder frames, correct event types)

### Step-by-Step Implementation

---

#### Step 0: Project Bootstrap

```
tth/
├── pyproject.toml
├── .env.example
├── Makefile
├── config/
│   ├── base.yaml
│   └── profiles/
│       └── api_only_mac.yaml
└── src/
    └── tth/
        └── __init__.py
```

**`pyproject.toml`** (key deps):
```toml
[project]
name = "tth"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "pydantic>=2.7",
  "pydantic-settings>=2.3",
  "httpx>=0.27",
  "websockets>=12",
  "structlog>=24",
  "pyyaml>=6",
  "python-dotenv>=1",
]
[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "pytest-httpx", "mypy", "ruff"]
train = ["torch", "pytorch-lightning", "omegaconf", "hydra-core"]  # added in v2
```

**`config/base.yaml`** (v1 defaults — OpenAI + stub avatar, no extra keys needed):
```yaml
app:
  host: "0.0.0.0"
  port: 8000
  log_level: "info"

components:
  llm:
    mode: api
    primary: openai_chat     # → adapters/llm/openai_api.py
    model: gpt-4o-mini       # cheapest capable model
    fallback: []
  tts:
    mode: api
    primary: openai_tts      # → adapters/tts/openai_tts.py  (reuses OPENAI_API_KEY)
    model: tts-1             # cheapest; upgrade to tts-1-hd for quality
    fallback: []
  avatar:
    mode: api
    primary: stub_avatar     # → adapters/avatar/stub.py  (no API key needed)
    fallback: []

personas:
  default:
    name: "Assistant"
    emotion: { label: neutral, intensity: 0.5 }
    character: { speech_rate: 1.0, expressivity: 0.6 }
```

**`config/profiles/api_only_mac.yaml`** (inherits base, no overrides needed for v1 — base IS the api_only profile):
```yaml
# v1 API-only profile: all values inherited from base.yaml
# Uncomment lines below to upgrade individual components without changing base:
# components:
#   tts:
#     primary: elevenlabs      # requires ELEVENLABS_API_KEY
#   avatar:
#     primary: heygen          # requires HEYGEN_API_KEY + avatar_id
```

**`.env.example`**:
```
# Required for v1 demo (only this one key needed)
OPENAI_API_KEY=sk-...

# Optional — add later when upgrading components
# ANTHROPIC_API_KEY=...        # for Claude LLM adapter
# ELEVENLABS_API_KEY=...       # for ElevenLabs TTS adapter
# TAVUS_API_KEY=...            # for Tavus avatar adapter
# HEYGEN_API_KEY=...           # for HeyGen avatar adapter

TTH_PROFILE=api_only_mac
```

---

#### Step 1: Core Types (`src/tth/core/types.py`)

Define the shared language of the entire system. **Nothing else is imported before this.**

```python
# src/tth/core/types.py
from __future__ import annotations
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


# ── Controls ──────────────────────────────────────────────────────────────────

class EmotionLabel(str, Enum):
    NEUTRAL   = "neutral"
    HAPPY     = "happy"
    SAD       = "sad"
    ANGRY     = "angry"
    SURPRISED = "surprised"
    FEARFUL   = "fearful"
    DISGUSTED = "disgusted"


class EmotionControl(BaseModel):
    label:     EmotionLabel = EmotionLabel.NEUTRAL
    intensity: float = Field(0.5, ge=0.0, le=1.0)
    valence:   float = Field(0.0, ge=-1.0, le=1.0)  # -1=negative  +1=positive
    arousal:   float = Field(0.0, ge=-1.0, le=1.0)  # -1=calm      +1=excited


class CharacterControl(BaseModel):
    persona_id:  str   = "default"
    speech_rate: float = Field(1.0, ge=0.25, le=4.0)
    pitch_shift: float = Field(0.0, ge=-1.0, le=1.0)
    expressivity: float = Field(0.6, ge=0.0, le=1.0)
    motion_gain:  float = Field(1.0, ge=0.0, le=2.0)


class TurnControl(BaseModel):
    emotion:   EmotionControl   = Field(default_factory=EmotionControl)
    character: CharacterControl = Field(default_factory=CharacterControl)


# ── Media ─────────────────────────────────────────────────────────────────────

class AudioChunk(BaseModel):
    """Internal pipeline type — not sent over WS directly."""
    data:         bytes   # raw MP3 bytes (not base64 — internal only)
    timestamp_ms: float
    duration_ms:  float   # computed from byte count + bitrate (never 0.0)
    sample_rate:  int = 24000
    encoding:     str = "mp3"


def estimate_mp3_duration_ms(data: bytes, bitrate_kbps: int = 128) -> float:
    """Duration of raw MP3 bytes at a known constant bitrate."""
    return (len(data) * 8) / (bitrate_kbps * 1000) * 1000


class VideoFrame(BaseModel):
    """Internal pipeline type — not sent over WS directly."""
    data:         bytes   # raw bytes (not base64 — internal only)
    timestamp_ms: float
    frame_index:  int
    width:        int
    height:       int
    content_type: Literal["jpeg", "h264_nal", "raw_rgb"] = "jpeg"
    # "raw_rgb":  stub adapter only — width*height*3 bytes, not a valid JPEG
    # "jpeg":     all production adapters — decodable by standard image libs
    # "h264_nal": future video streaming adapters


# ── Status ────────────────────────────────────────────────────────────────────

class HealthStatus(BaseModel):
    healthy:    bool
    latency_ms: float | None = None
    detail:     str = ""


class AdapterCapabilities(BaseModel):
    supports_streaming: bool       = True
    supports_emotion:   bool       = False
    supports_identity:  bool       = False
    max_text_length:    int        = 5000
    supported_emotions: list[str]  = []


# ── Events (outbound to client) ───────────────────────────────────────────────

class TextDeltaEvent(BaseModel):
    type:  Literal["text_delta"] = "text_delta"
    token: str

class AudioChunkEvent(BaseModel):
    """WS outbound event. `data` is base64-encoded MP3 bytes in JSON transport.
    Pydantic v2 serializes `bytes` fields as base64 automatically via model_dump_json().
    Clients must base64-decode `data` before playback."""
    type:  Literal["audio_chunk"] = "audio_chunk"
    data:  bytes          # base64 in JSON; raw bytes in memory
    timestamp_ms: float
    duration_ms:  float

class VideoFrameEvent(BaseModel):
    """WS outbound event. `data` is base64-encoded in JSON transport.
    content_type tells the client how to interpret the decoded bytes:
    'raw_rgb' → width*height*3 raw bytes; 'jpeg' → standard JPEG."""
    type:         Literal["video_frame"] = "video_frame"
    data:         bytes   # base64 in JSON; raw bytes in memory
    timestamp_ms: float
    frame_index:  int
    width:        int
    height:       int
    content_type: str     # "jpeg" | "raw_rgb" | "h264_nal"
    drift_ms:     float

class TurnCompleteEvent(BaseModel):
    type:     Literal["turn_complete"] = "turn_complete"
    turn_id:  str

class ErrorEvent(BaseModel):
    type:    Literal["error"] = "error"
    code:    str
    message: str


# ── Events (inbound from client) ─────────────────────────────────────────────

class UserTextEvent(BaseModel):
    type:    Literal["user_text"] = "user_text"
    text:    str
    control: TurnControl = Field(default_factory=TurnControl)

class InterruptEvent(BaseModel):
    type: Literal["interrupt"] = "interrupt"

class ControlUpdateEvent(BaseModel):
    type:    Literal["control_update"] = "control_update"
    control: TurnControl


InboundEvent = UserTextEvent | InterruptEvent | ControlUpdateEvent
```

---

#### Step 2: Config System (`src/tth/core/config.py`)

```python
# src/tth/core/config.py
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base; override wins on conflicts."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class ComponentConfig(BaseModel):
    mode:     str       = "api"   # "api" | "self_host"
    primary:  str       = ""
    fallback: list[str] = Field(default_factory=list)
    # adapter-specific extra fields passed through as-is
    model_config = {"extra": "allow"}


class AppConfig(BaseModel):
    host:      str = "0.0.0.0"
    port:      int = 8000
    log_level: str = "info"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TTH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Loaded from YAML
    app:        AppConfig = Field(default_factory=AppConfig)
    components: dict[str, Any] = Field(default_factory=dict)
    personas:   dict[str, Any] = Field(default_factory=dict)

    # API keys — from env only, never committed to YAML
    openai_api_key:     str = ""
    anthropic_api_key:  str = ""
    elevenlabs_api_key: str = ""
    tavus_api_key:      str = ""
    heygen_api_key:     str = ""

    profile: str = "api_only_mac"

    @model_validator(mode="before")
    @classmethod
    def load_yaml(cls, values: dict) -> dict:
        profile = os.getenv("TTH_PROFILE", values.get("profile", "api_only_mac"))
        base_path = Path("config/base.yaml")
        cfg: dict = yaml.safe_load(base_path.read_text()) if base_path.exists() else {}
        profile_path = Path(f"config/profiles/{profile}.yaml")
        if profile_path.exists():
            cfg = deep_merge(cfg, yaml.safe_load(profile_path.read_text()))
        # YAML values have lowest priority — env vars override them
        return {**cfg, **values}


# Module-level singleton; imported everywhere
settings = Settings()
```

---

#### Step 3: Adapter Base + Registry (`src/tth/adapters/base.py`, `src/tth/core/registry.py`)

```python
# src/tth/adapters/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator
from tth.core.types import (
    TurnControl, HealthStatus, AdapterCapabilities,
    AudioChunk, VideoFrame,
)


class AdapterBase(ABC):
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    async def load(self) -> None:
        """Load model weights or establish connection. Called once at startup."""

    async def warmup(self) -> None:
        """Send a throwaway inference request to prime caches. Optional."""

    @abstractmethod
    async def infer_stream(
        self,
        input: str | bytes | AudioChunk,
        control: TurnControl,
        context: dict[str, Any],
    ) -> AsyncIterator[str | AudioChunk | VideoFrame]:
        """Stream output tokens/chunks/frames. Must be an async generator."""
        ...

    async def infer_batch(
        self,
        input: str | bytes | AudioChunk,
        control: TurnControl,
    ) -> list[Any]:
        return [chunk async for chunk in self.infer_stream(input, control, {})]

    @abstractmethod
    async def health(self) -> HealthStatus: ...

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities()
```

```python
# src/tth/core/registry.py
from __future__ import annotations
from typing import Any, Type
# NOTE: import AdapterBase lazily to avoid circular imports at module load time

_registry: dict[str, type] = {}


def register(name: str):
    """Decorator: @register("openai_chat") on an AdapterBase subclass."""
    def decorator(cls: type) -> type:
        _registry[name] = cls
        return cls
    return decorator


def get(name: str) -> type:
    if name not in _registry:
        raise KeyError(
            f"No adapter registered for '{name}'. "
            f"Available: {sorted(_registry)}"
        )
    return _registry[name]


def create(name: str, config: dict[str, Any]) -> Any:
    """Instantiate a registered adapter with given config dict."""
    return get(name)(config)
```

---

#### Step 4: LLM Adapter — OpenAI (`src/tth/adapters/llm/openai_api.py`)

```python
# src/tth/adapters/llm/openai_api.py
from __future__ import annotations
import json
from typing import Any, AsyncIterator
import httpx
from tth.adapters.base import AdapterBase
from tth.control.mapper import build_llm_system_prompt
from tth.core.config import settings
from tth.core.registry import register
from tth.core.types import HealthStatus, TurnControl


@register("openai_chat")
class OpenAIChatAdapter(AdapterBase):
    """Streams tokens from OpenAI Chat Completions (SSE)."""

    _BASE = "https://api.openai.com/v1"

    async def infer_stream(
        self, input: str, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[str]:
        system_prompt = build_llm_system_prompt(
            control,
            persona_name=context.get("persona_name", "Assistant"),
        )
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
        payload = {
            "model": self.config.get("model", "gpt-4o-mini"),
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                *context.get("history", []),
                {"role": "user", "content": input},
            ],
        }
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream(
                "POST", f"{self._BASE}/chat/completions",
                headers=headers, json=payload,
            ) as resp:
                resp.raise_for_status()
                async for raw_line in resp.aiter_lines():
                    line = raw_line.strip()
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        delta = json.loads(line[6:])
                        token = (
                            delta["choices"][0]["delta"].get("content") or ""
                        )
                        if token:
                            yield token

    async def health(self) -> HealthStatus:
        import time
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"{self._BASE}/models",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            )
        return HealthStatus(
            healthy=r.status_code == 200,
            latency_ms=(time.monotonic() - t0) * 1000,
        )
```

---

#### Step 5: TTS Adapter — OpenAI TTS (`src/tth/adapters/tts/openai_tts.py`)

```python
# src/tth/adapters/tts/openai_tts.py
from __future__ import annotations
import time
from typing import Any, AsyncIterator
import httpx
from tth.adapters.base import AdapterBase
from tth.control.mapper import map_emotion_to_openai_tts
from tth.core.config import settings
from tth.core.registry import register
from tth.core.types import (
    AdapterCapabilities, AudioChunk, HealthStatus,
    TurnControl, estimate_mp3_duration_ms,
)

_OPENAI_BITRATE_KBPS = 128   # tts-1 outputs 128 kbps MP3

@register("openai_tts")
class OpenAITTSAdapter(AdapterBase):
    """
    Streams MP3 chunks from OpenAI TTS.
    Reuses OPENAI_API_KEY — no extra credentials needed.
    duration_ms is computed from chunk byte count at the known bitrate.
    """

    _BASE = "https://api.openai.com/v1"

    async def infer_stream(
        self, input: str, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[AudioChunk]:
        tts_params = map_emotion_to_openai_tts(control.emotion, control.character)
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
        payload = {
            "model":           self.config.get("model", "tts-1"),
            "input":           input,
            "voice":           tts_params["voice"],
            "speed":           tts_params["speed"],
            "response_format": "mp3",
        }
        wall_ms = time.monotonic() * 1000

        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST", f"{self._BASE}/audio/speech",
                headers=headers, json=payload,
            ) as resp:
                resp.raise_for_status()
                async for raw in resp.aiter_bytes(chunk_size=4096):
                    if not raw:
                        continue
                    duration = estimate_mp3_duration_ms(raw, _OPENAI_BITRATE_KBPS)
                    yield AudioChunk(
                        data=raw,
                        timestamp_ms=wall_ms,
                        duration_ms=duration,
                        sample_rate=24000,
                        encoding="mp3",
                    )
                    wall_ms += duration   # advance wall clock by this chunk's duration

    async def health(self) -> HealthStatus:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"{self._BASE}/models",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            )
        return HealthStatus(
            healthy=r.status_code == 200,
            latency_ms=(time.monotonic() - t0) * 1000,
        )

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_emotion=True,   # via voice selection + speed
            supported_emotions=["neutral", "happy", "sad", "angry", "surprised", "fearful"],
        )
```

---

#### Step 6: Avatar Adapter — Stub (`src/tth/adapters/avatar/stub.py`)

The stub emits `VideoFrame` events with `content_type="raw_rgb"` (raw `width×height×3` bytes).
This is clearly labelled — not JPEG — so no decoder chokes on it. Real adapters set `content_type="jpeg"`.
`duration_ms` from the audio chunk is used to compute exact frame count so A/V sync math is valid.

```python
# src/tth/adapters/avatar/stub.py
from __future__ import annotations
import asyncio
from typing import Any, AsyncIterator
from tth.adapters.base import AdapterBase
from tth.core.registry import register
from tth.core.types import (
    AdapterCapabilities, AudioChunk, HealthStatus, TurnControl, VideoFrame,
)

_W, _H = 256, 256
# 256×256 solid black raw RGB frame (not JPEG — content_type="raw_rgb")
_BLACK_FRAME = bytes(_W * _H * 3)


@register("stub_avatar")
class StubAvatarAdapter(AdapterBase):
    """
    Emits placeholder VideoFrame events timed to match audio duration.
    Exercises the full pipeline + drift controller without a real avatar API.
    Replace by changing avatar.primary in config — no code changes needed.
    content_type="raw_rgb" signals clients that this is raw bytes, not JPEG.
    """

    FPS: int = 25

    async def infer_stream(
        self, input: AudioChunk, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[VideoFrame]:
        # Use actual duration_ms (always > 0 with corrected TTS adapter)
        frames = max(1, round(input.duration_ms / 1000 * self.FPS))
        frame_duration_ms = 1000 / self.FPS
        base_idx = context.get("frame_counter", 0)

        for i in range(frames):
            yield VideoFrame(
                data=_BLACK_FRAME,
                timestamp_ms=input.timestamp_ms + i * frame_duration_ms,
                frame_index=base_idx + i,
                width=_W,
                height=_H,
                content_type="raw_rgb",
            )
            await asyncio.sleep(frame_duration_ms / 1000)

    async def health(self) -> HealthStatus:
        return HealthStatus(healthy=True, detail="stub adapter — always healthy")

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_emotion=False,
            supports_identity=False,
        )
```

When ready to add real video:
```yaml
# config/profiles/api_only_mac.yaml
components:
  avatar:
    primary: heygen        # requires HEYGEN_API_KEY + avatar_id in .env
    avatar_id: "abc123"
```

---

#### Step 7: Control Mapper (`src/tth/control/mapper.py`)

The single place that translates `TurnControl` → provider-specific fields.
**Adding a new provider (e.g., ElevenLabs v2) = add one function here. No pipeline code changes.**

```python
# src/tth/control/mapper.py
from __future__ import annotations
from tth.core.types import (
    CharacterControl, EmotionControl, EmotionLabel, TurnControl,
)


# ── OpenAI TTS mappings ───────────────────────────────────────────────────────

_OPENAI_VOICE_MAP: dict[EmotionLabel, str] = {
    EmotionLabel.NEUTRAL:   "nova",
    EmotionLabel.HAPPY:     "shimmer",
    EmotionLabel.SAD:       "onyx",
    EmotionLabel.ANGRY:     "echo",
    EmotionLabel.SURPRISED: "fable",
    EmotionLabel.FEARFUL:   "alloy",
    EmotionLabel.DISGUSTED: "echo",
}

def map_emotion_to_openai_tts(
    emotion: EmotionControl, character: CharacterControl
) -> dict:
    """
    OpenAI TTS has no direct emotion parameter, so we proxy it via:
    - voice selection (different voices carry different tonal qualities)
    - speed adjustment driven by arousal level (excited=faster, calm=slower)
    """
    speed_mod = 1.0 + (emotion.arousal * 0.15)    # ±15% speed from arousal
    speed = round(
        max(0.25, min(4.0, character.speech_rate * speed_mod)), 2
    )
    return {
        "voice": _OPENAI_VOICE_MAP.get(emotion.label, "alloy"),
        "speed": speed,
    }


# ── LLM system prompt injection ───────────────────────────────────────────────

def build_llm_system_prompt(
    control: TurnControl, persona_name: str = "Assistant"
) -> str:
    """
    Injects emotion + character into the LLM system prompt so the model
    generates text with the target emotional register before TTS is applied.
    """
    e, c = control.emotion, control.character
    parts = [f"You are {persona_name}."]

    if e.label != EmotionLabel.NEUTRAL or e.intensity > 0.3:
        parts.append(
            f"Respond with a {e.label.value} tone "
            f"(intensity {e.intensity:.1f}/1.0)."
        )
    if c.speech_rate < 0.85:
        parts.append("Speak slowly and deliberately.")
    elif c.speech_rate > 1.2:
        parts.append("Speak at a brisk, energetic pace.")
    if c.expressivity > 0.7:
        parts.append("Be expressive and emotionally engaged.")

    parts.append("Keep responses conversational and appropriately brief.")
    return " ".join(parts)


# ── Control merge ─────────────────────────────────────────────────────────────

def resolve(user_control: TurnControl, persona_defaults: TurnControl) -> TurnControl:
    """
    Merge user-supplied controls with persona defaults.
    User values win; fall back to persona defaults for unset fields.
    A field is considered "unset" if it equals the type default.
    """
    user_emotion_is_default = (
        user_control.emotion == EmotionControl()
    )
    user_character_is_default = (
        user_control.character.persona_id == "default"
    )
    return TurnControl(
        emotion=(
            persona_defaults.emotion
            if user_emotion_is_default
            else user_control.emotion
        ),
        character=(
            persona_defaults.character
            if user_character_is_default
            else user_control.character
        ),
    )


def _merge_controls(base: TurnControl, override: TurnControl) -> TurnControl:
    """
    Merge a stored pending_control (base) with a new UserTextEvent's control (override).
    Override fields win over base; base fills in defaults.
    Called in routes.py to apply ControlUpdateEvent on the next turn.
    """
    base_emotion_is_default    = (base.emotion    == EmotionControl())
    base_character_is_default  = (base.character  == CharacterControl())
    over_emotion_is_default    = (override.emotion    == EmotionControl())
    over_character_is_default  = (override.character  == CharacterControl())
    return TurnControl(
        emotion=(
            override.emotion if not over_emotion_is_default
            else base.emotion if not base_emotion_is_default
            else EmotionControl()
        ),
        character=(
            override.character if not over_character_is_default
            else base.character if not base_character_is_default
            else CharacterControl()
        ),
    )


# ── Future provider mappings (add here when upgrading) ────────────────────────
# def map_emotion_to_elevenlabs(emotion, character) -> dict: ...
# def map_emotion_to_heygen(emotion, character) -> dict: ...
```

---

#### Step 8: Orchestrator (`src/tth/pipeline/orchestrator.py`)

**Key design — low TTFA via pipelined sentence streaming:**
- LLM token stream and TTS run concurrently via a bounded `asyncio.Queue`
- TTS starts on the **first complete sentence** (not after full LLM response)
- Sentences are processed in order (consumer is sequential) so audio never interleaves
- TTFA ≈ LLM first-sentence latency (~500ms) + TTS first-chunk latency (~200ms) = ~700ms total

```python
# src/tth/pipeline/orchestrator.py
from __future__ import annotations
import asyncio
import uuid
from typing import Any
from tth.adapters.base import AdapterBase
from tth.control.mapper import resolve as resolve_controls
from tth.core.types import (
    AudioChunk, AudioChunkEvent, TextDeltaEvent, TurnCompleteEvent,
    TurnControl, VideoFrameEvent,
)
from tth.pipeline.session import Session

_SENTENCE_ENDS = frozenset(".!?\n")
_MIN_SENTENCE_LEN = 10   # chars — avoid flushing on abbreviations like "Dr."


class Orchestrator:
    def __init__(
        self,
        llm: AdapterBase,
        tts: AdapterBase,
        avatar: AdapterBase,
    ) -> None:
        self.llm    = llm
        self.tts    = tts
        self.avatar = avatar

    async def run_turn(
        self,
        session: Session,
        text: str,
        control: TurnControl,
        output_q: asyncio.Queue,
    ) -> None:
        turn_id = str(uuid.uuid4())
        resolved = resolve_controls(control, session.persona_defaults)

        # Bounded queue: LLM can produce at most 2 sentences ahead of TTS
        sentence_q: asyncio.Queue[str | None] = asyncio.Queue(maxsize=2)
        frame_counter = 0

        # ── Producer: LLM → sentence buffer → sentence_q ─────────────────────
        async def llm_producer() -> None:
            session.transition("LLM_RUN")
            buf = ""
            async for token in self.llm.infer_stream(text, control, session.context):
                await output_q.put(TextDeltaEvent(token=token))
                buf += token
                # Flush on sentence boundary once buffer is long enough
                if token[-1] in _SENTENCE_ENDS and len(buf.strip()) >= _MIN_SENTENCE_LEN:
                    await sentence_q.put(buf.strip())
                    buf = ""
            if buf.strip():                          # flush any trailing text
                await sentence_q.put(buf.strip())
            await sentence_q.put(None)               # sentinel: producer done

        # ── Consumer: sentence_q → TTS → Avatar ──────────────────────────────
        async def tts_avatar_consumer() -> None:
            nonlocal frame_counter
            session.transition("TTS_RUN")
            while True:
                sentence = await sentence_q.get()
                if sentence is None:
                    break                            # done
                async for chunk in self.tts.infer_stream(
                    sentence, resolved, session.context
                ):
                    await output_q.put(AudioChunkEvent(
                        data=chunk.data,
                        timestamp_ms=chunk.timestamp_ms,
                        duration_ms=chunk.duration_ms,
                    ))
                    session.transition("AVATAR_RUN")
                    ctx = {**session.context, "frame_counter": frame_counter}
                    async for frame in self.avatar.infer_stream(chunk, resolved, ctx):
                        drift = session.drift_controller.update(
                            chunk.timestamp_ms, frame.timestamp_ms
                        )
                        await output_q.put(VideoFrameEvent(
                            data=frame.data,
                            timestamp_ms=frame.timestamp_ms,
                            frame_index=frame.frame_index,
                            width=frame.width,
                            height=frame.height,
                            content_type=frame.content_type,
                            drift_ms=drift,
                        ))
                        frame_counter += 1

        # Run LLM and TTS+Avatar in parallel — TTS starts as soon as first sentence ready
        await asyncio.gather(llm_producer(), tts_avatar_consumer())

        session.transition("TURN_COMPLETE")
        await output_q.put(TurnCompleteEvent(turn_id=turn_id))
```

---

#### Step 9: API Layer (`src/tth/api/routes.py` + `main.py`)

Canonical endpoint set — single consistent naming used everywhere:
- `POST /v1/sessions` — create session
- `WS   /v1/sessions/{session_id}/stream` — bidirectional real-time stream
- `GET  /v1/health` — per-component health
- `GET  /v1/models` — active adapters + capabilities

WS design: the session stays open across **multiple turns**. `send_loop` never breaks on `TurnCompleteEvent`. Turn concurrency is serialized by `session.current_turn_task` — an incoming `UserTextEvent` cancels the running task (if any) before starting a new one. No lock is used; cancellation is via `asyncio.Task.cancel()`. `pending_control` (set by `ControlUpdateEvent`) is merged into the next `UserTextEvent`'s control and then cleared.

```python
# src/tth/api/routes.py
from __future__ import annotations
import asyncio
import json
from typing import Annotated
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from tth.api.schemas import (
    CreateSessionRequest, CreateSessionResponse,
    HealthResponse, ModelsResponse,
)
from tth.core.types import (
    InterruptEvent, UserTextEvent, ControlUpdateEvent, ErrorEvent,
)
from tth.pipeline.session import SessionManager

router = APIRouter()


# ── Session lifecycle ─────────────────────────────────────────────────────────

@router.post("/v1/sessions", response_model=CreateSessionResponse)
async def create_session(
    req: CreateSessionRequest,
    session_manager: Annotated[SessionManager, Depends(get_session_manager)],
):
    session = session_manager.create(
        persona_id=req.persona_id,
        emotion=req.emotion,
        character=req.character,
    )
    return CreateSessionResponse(session_id=session.id)


# ── Real-time WebSocket ───────────────────────────────────────────────────────

@router.websocket("/v1/sessions/{session_id}/stream")
async def session_stream(ws: WebSocket, session_id: str):
    session = get_session_manager().get_or_404(session_id)
    output_q: asyncio.Queue = asyncio.Queue(maxsize=64)
    await ws.accept()

    # ── Outbound: relay events to client; keep alive across turns ────────────
    async def send_loop() -> None:
        while True:
            event = await output_q.get()
            try:
                await ws.send_text(event.model_dump_json())
            except WebSocketDisconnect:
                return   # client gone; recv_loop will also exit

    # ── Inbound: handle client messages ──────────────────────────────────────
    async def recv_loop() -> None:
        try:
            async for raw in ws.iter_text():
                evt = _parse_inbound(raw)
                if evt is None:
                    continue

                if isinstance(evt, UserTextEvent):
                    # Cancel any running turn, then start the new one.
                    await session.cancel_current_turn()

                    # Merge pending_control (from prior ControlUpdateEvent) with
                    # this turn's control, then clear pending so it isn't double-applied.
                    effective_control = (
                        _merge_controls(session.pending_control, evt.control)
                        if session.pending_control is not None
                        else evt.control
                    )
                    session.pending_control = None

                    # Capture loop-local copies to avoid closure-over-loop-var bugs
                    _text    = evt.text
                    _control = effective_control

                    async def _run(text=_text, control=_control) -> None:
                        try:
                            await get_orchestrator().run_turn(
                                session, text, control, output_q
                            )
                        except asyncio.CancelledError:
                            pass   # clean interrupt; no error event needed
                        except Exception as exc:
                            await output_q.put(ErrorEvent(
                                code="turn_error", message=str(exc)
                            ))
                    session.current_turn_task = asyncio.create_task(_run())

                elif isinstance(evt, InterruptEvent):
                    await session.cancel_current_turn()

                elif isinstance(evt, ControlUpdateEvent):
                    # Stored; will be merged into the control of the next UserTextEvent
                    session.pending_control = evt.control

        except WebSocketDisconnect:
            pass

    send_task = asyncio.create_task(send_loop())
    recv_task = asyncio.create_task(recv_loop())

    try:
        await recv_task                   # exits on disconnect
    finally:
        send_task.cancel()
        await session.cancel_current_turn()
        get_session_manager().close(session_id)


# ── Utility endpoints ─────────────────────────────────────────────────────────

@router.get("/v1/health", response_model=HealthResponse)
async def health():
    orch = get_orchestrator()
    return HealthResponse(
        llm=await orch.llm.health(),
        tts=await orch.tts.health(),
        avatar=await orch.avatar.health(),
    )

@router.get("/v1/models", response_model=ModelsResponse)
async def models():
    orch = get_orchestrator()
    return ModelsResponse(
        llm=orch.llm.capabilities(),
        tts=orch.tts.capabilities(),
        avatar=orch.avatar.capabilities(),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_inbound(raw: str):
    try:
        data = json.loads(raw)
        t = data.get("type")
        if t == "user_text":    return UserTextEvent(**data)
        if t == "interrupt":    return InterruptEvent(**data)
        if t == "control_update": return ControlUpdateEvent(**data)
    except Exception:
        pass
    return None
```

```python
# src/tth/pipeline/session.py  (additions for turn concurrency)
import asyncio
from tth.core.types import TurnControl

class Session:
    def __init__(self, session_id: str, persona_defaults: TurnControl):
        self.id = session_id
        self.persona_defaults = persona_defaults
        self.context: dict = {"history": [], "persona_name": "Assistant"}
        self.pending_control: TurnControl | None = None
        self.current_turn_task: asyncio.Task | None = None
        self.drift_controller = DriftController()
        self._state: str = "IDLE"

    async def cancel_current_turn(self) -> None:
        if self.current_turn_task and not self.current_turn_task.done():
            self.current_turn_task.cancel()
            try:
                await self.current_turn_task
            except asyncio.CancelledError:
                pass
        self.current_turn_task = None
        self._state = "IDLE"

    def transition(self, state: str) -> None:
        self._state = state
```

---

#### Step 10: Local Dev Run

```bash
# 1. Set up project
uv init tth && cd tth
uv add fastapi uvicorn pydantic pydantic-settings httpx structlog pyyaml python-dotenv

# 2. Copy .env.example → .env, add your OpenAI key
echo "OPENAI_API_KEY=sk-..." > .env

# 3. Start server
make dev
# → uvicorn src.tth.api.main:app --reload --port 8000

# 4. Quick smoke test
python scripts/demo.py
# Output:
#   [session created: abc123]
#   [text_delta] Hello! I'd be happy to help...
#   [audio_chunk] 4096 bytes @ 1234.5ms
#   [video_frame] 256x256 stub @ 1234.5ms  (placeholder until real avatar added)
#   [turn_complete] drift_ms=12.3
```

**Cost for one demo session** (~5 turns, ~150 chars each):
- LLM (gpt-4o-mini): ~$0.001
- TTS (tts-1): ~$0.01
- Avatar: $0.00 (stubbed)
- **Total: ~$0.01 per full conversation**

---

## Part 2: Extension Points (v2 Self-Host)

Upgrading from API-only to self-hosted requires **zero architectural changes**:

| What changes | How |
|---|---|
| Add `cosyvoice_local.py` | Implement `TTSAdapterBase`, `@register("cosyvoice3_local")` |
| Add `musetalk_local.py` | Implement `AvatarAdapterBase`, `@register("musetalk_local")` |
| Switch config | `tts.primary: cosyvoice3_local`, `avatar.primary: musetalk_local` |
| Add training | Install `train` extras, use `packages/training/` with PyTorch Lightning |

Self-hosted adapter sketch:
```python
@register("cosyvoice3_local")
class CosyVoiceLocalAdapter(AdapterBase):
    async def load(self):
        from cosyvoice import CosyVoice  # loaded lazily, only when self_host mode
        self.model = CosyVoice("pretrained/CosyVoice3-0.5B", ...)

    async def infer_stream(self, text, control, context):
        emotion_token = map_emotion_to_cosyvoice_instruct(control.emotion)
        for chunk in self.model.inference_instruct2(text, emotion_token, ...):
            yield AudioChunk(data=chunk, ...)
```

---

## Part 3: Emotion Control — v1 vs v2

| Feature | v1 (API-Only — OpenAI + stub) | v2 (Self-Host — GPU) |
|---|---|---|
| TTS emotion | OpenAI voice selection + speed (6 voices proxy emotions) | CosyVoice3 instruct tokens → full spectrum |
| TTS fine-grained | Limited: no continuous valence/arousal in OpenAI TTS | EmoSteer-TTS: continuous valence/arousal |
| Avatar emotion | None (stub returns placeholder frames) | AUHead post-filter: per-AU intensity |
| Avatar expression | None (stub) | EmoTalker facial embedding |
| Character voice | OpenAI `speed` param + voice selection per persona | CosyVoice speaker embedding fine-tune |
| Character identity | None (stub) | MuseTalk reference video + GGTalker adapt |

---

## Part 4: Training Infrastructure (v2)

Added as `packages/training/` — only installed when needed (`pip install tth[train]`).

### Structure
```
packages/training/
├── systems/
│   ├── tts_finetune_system.py      # LightningModule for voice fine-tuning
│   └── avatar_identity_system.py   # LightningModule for identity adaptation
├── datamodules/
│   ├── tts_datamodule.py           # loads audio manifests
│   └── talking_head_datamodule.py  # loads video + landmark manifests
├── datasets/
│   ├── tts_dataset.py              # item: (text, mel, speaker_id, emotion_label)
│   └── talking_head_dataset.py     # item: (audio_chunk, video_frame, landmarks)
└── callbacks/
    ├── sample_logger.py            # logs audio/video samples to W&B
    └── checkpoint.py
```

### Fine-Tune Voice (CosyVoice3)
- **Data needed**: 100+ sentences, 1+ min audio, with optional emotion labels
- **Time**: 1–5 GPU hours on A10
- **Output**: checkpoint in `checkpoints/tts/{persona_id}/`
- **Config**: `config/training/tts_finetune.yaml` → `apps/trainer/main.py`

### Adapt Identity (MuseTalk / GGTalker-style)
- **Data needed**: 32+ portrait images of target person
- **Time**: 10–50 GPU hours
- **Output**: identity embedding in `checkpoints/avatar/{persona_id}/`

### Train Entry Point
```bash
# Using Hydra (added in v2)
python -m tth.apps.trainer training=tts_finetune persona_id=alice data_dir=data/alice
```

---

## Part 5: Phased Execution Plan

### Phase 0 — Bootstrap (Day 1)
- [ ] Create `pyproject.toml`, install deps with `uv`
- [ ] Set up `config/base.yaml` + `config/profiles/api_only_mac.yaml`
- [ ] Implement `core/types.py` with all control + event types
- [ ] Implement `core/config.py` (Pydantic Settings + YAML loader)
- [ ] Implement `core/registry.py`
- [ ] Write unit tests for types (serialization, validation edge cases)

### Phase 1 — Adapters (Days 2–4)
- [ ] Implement `adapters/base.py` (ABC)
- [ ] Implement `adapters/llm/openai_api.py` (streaming SSE chat)
- [ ] Implement `adapters/tts/openai_tts.py` (streaming MP3, `duration_ms` via bitrate math)
- [ ] Implement `adapters/avatar/stub.py` (placeholder frames, `content_type="raw_rgb"`)
- [ ] Implement `control/mapper.py` (`map_emotion_to_openai_tts`, `build_llm_system_prompt`, `resolve`)
- [ ] Implement `control/personas.py` (default persona presets: neutral, professional, casual, excited)
- [ ] Write unit tests per adapter (mock `httpx`, verify event shape and `duration_ms > 0`)

### Phase 2 — Pipeline (Days 5–7)
- [ ] Implement `pipeline/session.py` (state machine, drift tracker)
- [ ] Implement `pipeline/orchestrator.py` (full async turn engine)
- [ ] Implement `alignment/drift.py` (timestamp tracking, correction)
- [ ] Write integration test: mock adapters → full turn → correct event sequence

### Phase 3 — API + E2E (Days 8–10)
- [ ] Implement `api/schemas.py` (all Pydantic request/response models)
- [ ] Implement `api/routes.py` (WS + HTTP endpoints)
- [ ] Implement `api/main.py` (startup: load adapters from registry by config)
- [ ] Write `scripts/test_session.py` (smoke test: connect WS, send text, assert events)
- [ ] Run actual end-to-end test with real API keys

### Phase 4 — Controls (Days 11–14)
- [ ] Complete all emotion mappings in `control/mapper.py` for each provider
- [ ] Complete all character mappings (speech_rate, expressivity, persona_id)
- [ ] Add persona presets in `config/personas.yaml` (neutral, professional, casual, excited)
- [ ] Test emotion sweep: send same text with 5 different emotions, verify perceptual difference
- [ ] Test character sweep: slow/fast speech_rate, high/low expressivity

### Phase 5 — Hardening (Days 15–18)
- [ ] Add fallback chain: primary fails → try next provider from `fallback` list
- [ ] Add circuit breaker per adapter (3-state: Closed/Open/HalfOpen)
- [ ] Add timeout budgets per stage (LLM: 5s, TTS: 2s first chunk, Avatar: 3s)
- [ ] Add `GET /v1/health` per-component health check
- [ ] Add `GET /v1/models` to return active adapters + capabilities
- [ ] Add structured logging (structlog) + trace ID per session/turn

### Phase 6 — Self-Host Adapters (v2, separate milestone)
- [ ] Implement `adapters/tts/cosyvoice_local.py`
- [ ] Implement `adapters/tts/emosteer.py` (EmoSteer-TTS wrapper)
- [ ] Implement `adapters/avatar/musetalk_local.py`
- [ ] Implement `adapters/avatar/latentsync_local.py`
- [ ] Implement `adapters/avatar/auhead.py` (facial emotion post-filter)
- [ ] Add `config/profiles/self_host_gpu.yaml`
- [ ] Verify: switch profile, same tests pass

### Phase 7 — Training (v2)
- [ ] Install `tth[train]` deps (pytorch-lightning, hydra-core)
- [ ] Implement dataset manifests + datamodules
- [ ] Implement TTS fine-tune LightningModule
- [ ] Implement identity adaptation LightningModule
- [ ] Add `apps/trainer/main.py` Hydra entry point
- [ ] Run voice fine-tune on sample data, measure identity consistency delta

---

## Part 6: File-to-File Interface Contracts

### `core/types.py` exports used everywhere
- `EmotionControl`, `CharacterControl`, `TurnControl`
- `AudioChunk`, `VideoFrame`
- `HealthStatus`, `AdapterCapabilities`
- All event types: `UserTextEvent`, `TextDeltaEvent`, `AudioChunkEvent`, `VideoFrameEvent`, `TurnCompleteEvent`, `InterruptEvent`

### `adapters/base.py` → every adapter
Every adapter must:
- Accept `config: dict` in `__init__`
- Implement `infer_stream() → AsyncIterator`
- Implement `health() → HealthStatus`
- Decorate with `@register("name")`

### `control/mapper.py` → orchestrator, adapters
- `resolve(user_control, persona_defaults) → TurnControl` — merges controls
- `map_emotion_to_openai_tts(emotion, character) → {"voice": str, "speed": float}`
- `build_llm_system_prompt(control, persona_name) → str`
- Future: `map_emotion_to_elevenlabs(...)`, `map_emotion_to_heygen(...)` added here

### Config keys → adapter names (v1 defaults)
- `components.llm.primary: "openai_chat"` → `registry.get("openai_chat")` → `OpenAIChatAdapter`
- `components.tts.primary: "openai_tts"` → `registry.get("openai_tts")` → `OpenAITTSAdapter`
- `components.avatar.primary: "stub_avatar"` → `registry.get("stub_avatar")` → `StubAvatarAdapter`

---

## Part 7: Acceptance Criteria

| Check | How to verify |
|---|---|
| Single command start | `make dev` → server up at :8000 with only `OPENAI_API_KEY` in `.env` |
| No local models loaded | No file downloads; `ps aux` shows no GPU processes |
| Multi-turn conversation | Send 3 turns on same WS; all receive text+audio+video events, session stays open |
| No turn race | Send 2 `user_text` events rapidly; only one turn runs at a time (second cancels first) |
| `duration_ms > 0` on all audio chunks | Check in demo script; never `0.0` |
| `content_type` set on all video frames | `"raw_rgb"` for stub, `"jpeg"` for real adapters |
| Emotion switch | 5 emotion labels → different `voice` field and `speed` in TTS calls |
| Persona switch | 2 persona configs → different system prompt injected into LLM |
| Config portability | Change `tts.primary: openai_tts` → `elevenlabs` in YAML; no code change |
| Low TTFA | First audio chunk arrives before full LLM response finishes (pipelined sentences) |
| A/V drift | ≤ 80ms mean (logged per turn in `turn_complete` event) |
| `/v1/health` endpoint | Returns health for llm, tts, avatar adapters |
| `/v1/models` endpoint | Returns capabilities for active adapters |
