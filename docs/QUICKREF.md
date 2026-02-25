# TTH Quick Reference

## Commands

```bash
# Development
make install      # Install dependencies
make dev          # Start dev server (port 8000)
make test         # Run unit tests
make lint         # Run linter
make fmt          # Format code

# Testing
make phase        # Run offline phased tests
make phase-live   # Run all tests including live OpenAI

# Demo
make demo         # Run end-to-end demo (requires running server)

# Interactive Testing
make test-interactive "Your message"  # Test pipeline with playable output
make demo-interactive                 # Interactive demo (requires running server)
```

## File Locations

| What | Where |
|------|-------|
| Core types | `src/tth/core/types.py` |
| Config | `src/tth/core/config.py`, `config/base.yaml` |
| LLM adapter | `src/tth/adapters/llm/openai_api.py` |
| TTS adapter | `src/tth/adapters/tts/openai_tts.py` |
| Avatar stub | `src/tth/adapters/avatar/stub.py` |
| Control mapping | `src/tth/control/mapper.py` |
| Orchestrator | `src/tth/pipeline/orchestrator.py` |
| Session | `src/tth/pipeline/session.py` |
| API routes | `src/tth/api/routes.py` |
| Tests | `tests/`, `scripts/phase_*.py` |
| Interactive test | `scripts/interactive_test.py` |
| Interactive demo | `scripts/interactive_demo.py` |

## Key Patterns

### Add new adapter
```python
# src/tth/adapters/tts/new_provider.py
from tth.adapters.base import AdapterBase
from tth.core.registry import register

@register("new_provider")
class NewProviderAdapter(AdapterBase):
    async def infer_stream(self, input, control, context):
        # Yield AudioChunk or VideoFrame or str
        yield chunk

    async def health(self):
        return HealthStatus(healthy=True)
```

### Add new emotion mapping
```python
# src/tth/control/mapper.py
def map_emotion_to_new_provider(emotion, character) -> dict:
    return {"provider_param": value}
```

### Switch adapter in config
```yaml
# config/profiles/api_only_mac.yaml
components:
  tts:
    primary: new_provider
```

## Event Types

| Direction | Type | Purpose |
|-----------|------|---------|
| In | `user_text` | User message with optional control |
| In | `interrupt` | Cancel current turn |
| In | `control_update` | Update control for next turn |
| Out | `text_delta` | LLM token |
| Out | `audio_chunk` | MP3 bytes (base64 in JSON) |
| Out | `video_frame` | Frame bytes (base64 in JSON) |
| Out | `turn_complete` | Turn finished |
| Out | `error` | Error occurred |

## Environment Variables

```bash
OPENAI_API_KEY=sk-...       # Required for v1
TTH_PROFILE=api_only_mac    # Config profile
```

## Acceptance Criteria

- [x] `make dev` starts server
- [x] Multi-turn conversation via WebSocket
- [x] Turn cancellation works
- [x] `duration_ms > 0` on all audio chunks
- [x] `content_type` set on all video frames
- [x] Emotion affects TTS voice/speed
- [x] Config-driven adapter switching
- [x] A/V drift tracked per session
- [x] `/v1/health` and `/v1/models` endpoints
