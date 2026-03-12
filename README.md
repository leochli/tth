# TTH — Text-to-Human Video System

Real-time text-to-human video synthesis with emotion and character controllability. Built with an API-first architecture that lets you swap between external APIs and self-hosted models via configuration — no code changes required.

## Features

- **Real-time streaming** — WebSocket-based bidirectional communication
- **D-ID WebRTC avatars** — Live talking-head video via D-ID's Agents SDK, delivered directly to the browser via WebRTC
- **Emotion control** — Fine-grained emotion parameters (label, intensity, valence, arousal)
- **Character control** — Speech rate, pitch, expressivity, motion gain
- **Pluggable adapters** — Swap LLM, TTS, and avatar providers via config
- **Interactive demo** — Browser demo at `/static/demo.html` with WebSocket + WebRTC modes

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
export DID_API_KEY=...        # Optional: for D-ID WebRTC avatars
```

### Try the Demo

```bash
make dev
```

Open **http://localhost:8000/static/demo.html** in your browser.

**Standard mode (WebSocket):**
1. Click **Connect** → establishes a WebSocket session
2. Type a message and click **Send**
3. Streaming text and audio play in real time

**D-ID WebRTC mode:**
1. Set `DID_API_KEY` and restart the server
2. Click **Connect D-ID** → server creates a D-ID agent + stream, browser connects via WebRTC
3. Type a message and click **Send** → avatar speaks with lip-synced video and audio

### CLI Demo

```bash
make dev     # Terminal 1: start server
make demo    # Terminal 2: CLI client
```

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                  CLIENT (browser / CLI)                       │
└──────────────────────┬───────────────────────┬───────────────┘
                       │  WS /v1/sessions/…    │  HTTP /v1/did/…
                       ▼                       ▼
┌──────────────────────────────────────────────────────────────┐
│                   API GATEWAY (FastAPI)                       │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR (async)                       │
│                                                              │
│  UserText ──► [Realtime API] ──► text + audio chunks         │
│                                       │                      │
│                                       ▼                      │
│                                  [Avatar]                    │
│                            (stub / D-ID / cloud)            │
└──────────────────────────────────────────────────────────────┘
                                        │ WebRTC (D-ID mode)
                                        ▼
                               Browser video element
```

**D-ID hybrid flow**: the server creates the D-ID agent and stream, negotiates WebRTC (SDP + ICE relay), then sends text via the chat API. Video and audio travel directly from D-ID to the browser over WebRTC — the server never touches the media.

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
│   │       ├── did_streaming.py     # D-ID WebRTC streaming
│   │       ├── did_cloud.py         # D-ID Talks API (text-to-video)
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

### D-ID WebRTC

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/did/sessions/{id}/connect` | POST | Create D-ID agent + stream, return SDP offer |
| `/v1/did/sessions/{id}/sdp` | POST | Relay browser SDP answer to D-ID |
| `/v1/did/sessions/{id}/ice` | POST | Relay ICE candidates to D-ID |
| `/v1/did/sessions/{id}/chat` | POST | Send text for avatar to speak |
| `/v1/did/sessions/{id}` | DELETE | Close WebRTC session |

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
    primary: did_streaming       # D-ID WebRTC (requires DID_API_KEY)
    fallback: [stub_avatar]
```

Available avatar adapters:

| Adapter | Description | API Key |
|---------|-------------|---------|
| `stub_avatar` | Placeholder frames, no external calls | — |
| `mock_cloud_avatar` | Simulated latency, JPEG frames (dev/CI) | — |
| `did_streaming` | D-ID Agents SDK, WebRTC to browser | `DID_API_KEY` |
| `did_cloud` | D-ID Talks API, text-to-video (not real-time) | `DID_API_KEY` |
| `liveportrait_cloud` | LivePortrait via Modal/RunPod WebSocket | `MODAL_API_KEY` |

### Environment Variables

```bash
# Required
OPENAI_API_KEY=sk-...

# Avatar providers (pick one)
DID_API_KEY=...            # D-ID WebRTC streaming
MODAL_API_KEY=...          # LivePortrait on Modal

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
| Avatar | D-ID streaming | Per D-ID plan |
| Avatar | stub / mock | $0 |

## License

MIT
