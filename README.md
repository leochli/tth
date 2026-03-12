# TTH — Text-to-Human Video System

Real-time text-to-human video synthesis with emotion and character controllability. Built with an API-first architecture that lets you swap between external APIs and self-hosted models via configuration — no code changes required.

## Features

- **Real-time streaming** — WebSocket-based bidirectional communication
- **Simli real-time avatars** — Lip-synced video from OpenAI Realtime audio at <300ms latency
- **Emotion control** — Fine-grained emotion parameters (label, intensity, valence, arousal)
- **Character control** — Speech rate, pitch, expressivity, motion gain
- **Pluggable adapters** — Swap LLM, TTS, and avatar providers via config
- **Interactive demo** — Browser demo at `/static/demo.html`

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- `OPENAI_API_KEY` (required for LLM + TTS via Realtime API)

### Setup

```bash
git clone https://github.com/leochli/tth.git
cd tth

make install

# Set your API keys
export OPENAI_API_KEY=sk-...
export SIMLI_API_KEY=...      # For Simli real-time avatars
```

### Try the Demo

```bash
make dev
```

Open **http://localhost:8000/demo.html** in your browser.

1. Click **Connect** → establishes a WebSocket session
2. Type a message and click **Send**
3. Streaming text, audio, and lip-synced avatar video play in real time

With `SIMLI_API_KEY` set, the server forwards audio to Simli and streams JPEG frames back to the browser via VideoFrame events.

### CLI Demo

```bash
make dev     # Terminal 1: start server
make demo    # Terminal 2: CLI client
```

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                  CLIENT (browser / CLI)                       │
└──────────────────────────────┬───────────────────────────────┘
                               │  WS /v1/sessions/…
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                   API GATEWAY (FastAPI)                       │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR (async)                       │
│                                                              │
│  UserText ──► [Realtime API] ──► text + audio chunks         │
│                                       │                      │
│                                       ▼                      │
│                            [Simli Avatar Adapter]            │
│                         (resample 24kHz → 16kHz,            │
│                          send binary PCM over WS)            │
└──────────────────────────────────────────────────────────────┘
                                        │ VideoFrame events
                                        ▼
                               Browser canvas element
```

**Simli flow**: OpenAI Realtime API produces audio → server resamples from 24kHz to 16kHz and forwards binary PCM to Simli's WebSocket → Simli returns binary JPEG frames → server sends `video_frame` events to the browser over the existing WebSocket connection.

## Project Structure

```
tth/
├── src/tth/
│   ├── core/           # Types, config, registry
│   ├── adapters/
│   │   ├── llm/        # OpenAI Chat, Anthropic, mock
│   │   ├── tts/        # OpenAI TTS, ElevenLabs, mock
│   │   └── avatar/
│   │       ├── stub.py              # Placeholder RGB frames
│   │       ├── mock_cloud.py        # Simulated cloud adapter (CI/dev)
│   │       ├── simli.py             # Simli real-time avatar (primary)
│   │       ├── did_streaming.py     # D-ID WebRTC streaming (legacy)
│   │       ├── did_cloud.py         # D-ID Talks API (text-to-video, legacy)
│   │       ├── liveportrait_cloud.py
│   │       └── cloud_base.py        # Base class for cloud adapters
│   ├── control/        # Emotion/character mapping
│   ├── pipeline/       # Orchestrator + session management
│   ├── alignment/      # A/V drift control
│   └── api/
│       ├── main.py     # FastAPI app
│       ├── routes.py   # REST + WebSocket + D-ID routes
│       └── static/     # Browser demo (demo.html, did_webrtc.js, …)
├── client/             # Standalone browser client files
├── config/             # YAML configuration profiles
├── tests/              # pytest suite
└── docs/               # Architecture documentation
```

## API Endpoints

### Core

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/sessions` | POST | Create session |
| `/v1/sessions/{id}/stream` | WS | Bidirectional real-time stream |
| `/v1/health` | GET | Per-component health status |
| `/v1/models` | GET | Active adapter capabilities |

### WebSocket Protocol

**Client → Server:**
```json
{"type": "user_text", "text": "Hello!", "control": {...}}
{"type": "interrupt"}
{"type": "control_update", "control": {...}}
```

**Server → Client:**
```json
{"type": "text_delta", "token": "Hello"}
{"type": "audio_chunk", "data": "<base64>", "timestamp_ms": 1000, "duration_ms": 256}
{"type": "video_frame", "data": "<base64>", "frame_index": 0, "drift_ms": 5.0}
{"type": "turn_complete", "turn_id": "uuid"}
```

## Configuration

### Avatar Adapters

```yaml
# config/base.yaml
components:
  avatar:
    primary: simli               # Simli real-time avatars (requires SIMLI_API_KEY)
    fallback: [stub_avatar]
```

Available avatar adapters:

| Adapter | Description | API Key |
|---------|-------------|---------|
| `stub_avatar` | Placeholder frames, no external calls | — |
| `mock_cloud_avatar` | Simulated latency, JPEG frames (dev/CI) | — |
| `simli` | Simli real-time lip-sync, <300ms latency | `SIMLI_API_KEY` |
| `liveportrait_cloud` | LivePortrait via Modal/RunPod WebSocket | `MODAL_API_KEY` |
| `did_streaming` | D-ID Agents SDK, WebRTC to browser (legacy) | `DID_API_KEY` |
| `did_cloud` | D-ID Talks API, text-to-video (legacy) | `DID_API_KEY` |

### Environment Variables

```bash
# Required
OPENAI_API_KEY=sk-...

# Avatar providers (pick one)
SIMLI_API_KEY=...          # Simli real-time avatars (primary)
MODAL_API_KEY=...          # LivePortrait on Modal
DID_API_KEY=...            # D-ID (legacy)

# Optional alternative providers
ANTHROPIC_API_KEY=...
ELEVENLABS_API_KEY=...
```

### Switching Providers

Change avatar with no code edits:

```yaml
# config/base.yaml
components:
  avatar:
    primary: mock_cloud_avatar   # dev/CI — no API key needed
    # primary: simli             # production — requires SIMLI_API_KEY
```

```bash
TTH_PROFILE=offline_mock make dev   # fully offline mode
```

## Development

```bash
make install    # Install dependencies
make dev        # Start development server (http://localhost:8000)
make test       # Run unit tests
make lint       # Run linter (ruff + mypy)
make fmt        # Format code
make phase      # Offline integration tests (mock_cloud_avatar)
make phase-live # Live API integration tests
make demo       # CLI demo client
```

## Cost Estimates

| Component | Provider | Cost |
|-----------|----------|------|
| LLM + TTS | OpenAI Realtime API | ~$0.06/min audio |
| Avatar | Simli | ~$0.05/min |
| Avatar | stub / mock | $0 |

## License

MIT
