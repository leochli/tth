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
| Realtime adapter | `src/tth/adapters/realtime/openai_realtime.py` |
| Avatar adapters | `src/tth/adapters/avatar/` |
| - Simli (primary) | `src/tth/adapters/avatar/simli.py` |
| - Mock cloud | `src/tth/adapters/avatar/mock_cloud.py` |
| - Stub | `src/tth/adapters/avatar/stub.py` |
| - Cloud base | `src/tth/adapters/avatar/cloud_base.py` |
| Audio utilities | `src/tth/adapters/avatar/audio_utils.py`, `buffer.py` |
| Control mapping | `src/tth/control/mapper.py` |
| Orchestrator | `src/tth/pipeline/orchestrator.py` |
| Session | `src/tth/pipeline/session.py` |
| API routes | `src/tth/api/routes.py` |
| Client rendering | `client/avatar_renderer.js`, `client/av_sync.js` |
| Tests | `tests/`, `scripts/phase_*.py` |
| Interactive test | `scripts/interactive_test.py` |
| Interactive demo | `scripts/interactive_demo.py` |

## Key Patterns

### Add new streaming adapter (Avatar, LLM, TTS)
```python
# src/tth/adapters/avatar/new_provider.py
from tth.adapters.base import AdapterBase
from tth.core.registry import register

@register("new_provider")
class NewProviderAdapter(AdapterBase):
    async def infer_stream(self, input, control, context):
        # Yield AudioChunk or VideoFrame or str
        yield chunk

    async def interrupt(self):
        # Optional: Clear buffers on interrupt
        ...

    async def health(self):
        return HealthStatus(healthy=True)
```

### Add new cloud avatar adapter
```python
# src/tth/adapters/avatar/my_cloud.py
from tth.adapters.avatar.cloud_base import CloudAvatarAdapterBase
from tth.core.registry import register

@register("my_cloud_avatar")
class MyCloudAvatarAdapter(CloudAvatarAdapterBase):
    def _get_auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {os.environ.get('MY_API_KEY')}"}

    async def load(self) -> None:
        # Validate endpoint, preload avatars
        ...

    # infer_stream() inherits from CloudAvatarAdapterBase
    # Just implement auth and initialization
```

### Add new realtime adapter (Combined LLM+TTS)
```python
# src/tth/adapters/realtime/my_realtime.py
from tth.core.registry import register

@register("my_realtime")
class MyRealtimeAdapter(AdapterBase):
    async def connect(self, system_instructions: str, voice: str) -> None:
        """Establish connection ONCE at session start."""
        ...

    async def send_user_text(self, text: str) -> None:
        """Send user message and trigger response."""
        ...

    async def stream_events(self) -> AsyncIterator[...]:
        """Yield events until TurnCompleteEvent."""
        ...

    async def cancel_response(self) -> None:
        """Cancel current response."""
        ...

    async def close(self) -> None:
        """Close connection."""
        ...
```

### Add new emotion mapping
```python
# src/tth/control/mapper.py
def map_emotion_to_new_provider(emotion, character) -> dict:
    return {"provider_param": value}
```

### Switch adapter in config
```yaml
# config/base.yaml — change primary to switch
components:
  avatar:
    primary: new_provider
```

## Event Types

| Direction | Type | Purpose |
|-----------|------|---------|
| In | `user_text` | User message with optional control |
| In | `interrupt` | Cancel current turn |
| In | `control_update` | Update control for next turn |
| Out | `text_delta` | LLM token |
| Out | `audio_chunk` | PCM bytes (base64 in JSON) |
| Out | `video_frame` | Frame bytes (base64 in JSON) |
| Out | `turn_complete` | Turn finished |
| Out | `error` | Error occurred |

## Realtime API Notes

- **Connection**: Established once at session start via `connect()`
- **Audio Format**: PCM, 24kHz, 16-bit, mono
- **Latency**: Lower than separate LLM→TTS pipeline (no sentence buffering)
- **Interrupt**: Use `cancel_response()` to stop generation
- **Voice Selection**: Controlled via `EmotionControl.label`

## Environment Variables

```bash
OPENAI_API_KEY=sk-...       # Required for Realtime API
SIMLI_API_KEY=...           # Required for Simli avatar
TTH_PROFILE=offline_mock    # Use stub avatar (no Simli API needed)
```

## Avatar Profiles

```yaml
# Default (base.yaml): Simli real-time lip-sync
components:
  avatar:
    primary: simli
    fallback: [stub_avatar]

# Offline testing (config/profiles/offline_mock.yaml)
components:
  avatar:
    primary: stub_avatar
    fallback: []

# Development: Mock cloud with simulated latency
components:
  avatar:
    primary: mock_cloud_avatar
    mock_cloud_avatar:
      simulated_latency_ms: 150
```

## Acceptance Criteria

- [x] `make dev` starts server
- [x] Multi-turn conversation via WebSocket
- [x] Turn cancellation works
- [x] `duration_ms > 0` on all audio chunks
- [x] `content_type` set on all video frames
- [x] Emotion affects voice selection
- [x] Config-driven adapter switching
- [x] A/V drift tracked per session
- [x] `/v1/health` and `/v1/models` endpoints
