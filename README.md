# TTH — Text-to-Human Video System

Real-time text-to-human video synthesis with emotion and character controllability. Built with an API-first architecture that lets you swap between external APIs and self-hosted models via configuration — no code changes required.

## Features

- **Real-time streaming** — WebSocket-based bidirectional communication
- **Emotion control** — Fine-grained emotion parameters (label, intensity, valence, arousal)
- **Character control** — Speech rate, pitch, expressivity, motion gain
- **Pluggable adapters** — Swap LLM, TTS, and avatar providers via config
- **Web UI** — Cinematic neo-futurism interface with glass-morphism effects

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/tth.git
cd tth

# Install dependencies
make install

# Configure environment
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### Try the Demo

```bash
# Start the server
make dev
```

Then open **http://localhost:8000** in your browser.

1. Click **Connect** to establish a WebSocket session
2. Type a message and press **Send**
3. Watch the AI respond with streaming text and audio

The web UI features real-time audio playback, animated status indicators, and a cinematic dark theme.

### CLI Demo (Optional)

For programmatic testing, you can also run the CLI demo:

```bash
# Terminal 1: Start server
make dev

# Terminal 2: Run CLI demo
make demo
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     CLIENT (browser / CLI)                   │
└──────────────────────────────┬──────────────────────────────┘
                               │  HTTP POST /v1/sessions
                               │  WS   /v1/sessions/{id}/stream
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   API GATEWAY (FastAPI)                      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR (async)                      │
│                                                              │
│  UserText ──► [LLM] ──► [Control Merge] ──► [TTS]           │
│                                               │              │
│                                               ▼              │
│                                          [Avatar]            │
│                                               │              │
│                                    [A/V Mux + Drift Ctrl]    │
└─────────────────────────────────────────────────────────────┘
```

## Project Structure

```
tth/
├── src/tth/
│   ├── core/          # Types, config, registry, logging
│   ├── adapters/      # Provider implementations (LLM, TTS, Avatar)
│   ├── control/       # Emotion/character mapping
│   ├── pipeline/      # Orchestrator + session management
│   ├── alignment/     # A/V synchronization
│   └── api/           # FastAPI app + routes + web UI
├── config/            # YAML configuration profiles
├── scripts/           # Demo and testing scripts
├── tests/             # pytest suite
└── docs/              # Architecture documentation
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/sessions` | POST | Create new session |
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

### Default Profile (API-only)

```yaml
# config/base.yaml
components:
  llm:
    primary: openai_chat
    model: gpt-4o-mini
  tts:
    primary: openai_tts
    model: tts-1
  avatar:
    primary: stub_avatar
```

### Environment Variables

```bash
# Required
OPENAI_API_KEY=sk-...

# Optional (for alternative providers)
ANTHROPIC_API_KEY=...
ELEVENLABS_API_KEY=...
TAVUS_API_KEY=...
HEYGEN_API_KEY=...
```

### Switching Providers

To use a different TTS provider:

```yaml
# config/profiles/api_only_mac.yaml
components:
  tts:
    primary: elevenlabs
```

```bash
# .env
ELEVENLABS_API_KEY=...
```

No code changes required.

## Development

```bash
make install    # Install dependencies
make dev        # Start development server
make test       # Run unit tests
make lint       # Run linter (ruff + mypy)
make fmt        # Format code
make phase      # Run offline integration tests
make phase-live # Run tests with live API calls
```

## Cost Estimates

| Component | Model | Cost |
|-----------|-------|------|
| LLM | gpt-4o-mini | ~$0.15/1M input tokens |
| TTS | tts-1 | $0.015/1000 chars |
| Avatar | stub | $0 |

Typical demo session (~5 turns, ~150 chars each): **~$0.01 per conversation**

## License

MIT
