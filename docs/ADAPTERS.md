# TTH Adapters

This document describes the adapter system and all available adapters in TTH.

## Adapter Architecture

TTH uses a plugin architecture where adapters are registered via decorator and instantiated via configuration. This enables swapping providers without code changes.

### Adapter Types

There are two types of adapters in TTH:

1. **Streaming Adapters**: Traditional adapters that implement `infer_stream()` for per-turn processing
2. **Realtime Adapters**: Session-scoped adapters that maintain a persistent WebSocket connection

### Adapter Base Class

All adapters inherit from `AdapterBase`:

```python
# src/tth/adapters/base.py
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

### Registry

Adapters are registered using the `@register()` decorator:

```python
from tth.core.registry import register

@register("my_adapter")
class MyAdapter(AdapterBase):
    ...
```

And instantiated via the registry:

```python
from tth.core.registry import registry

adapter = registry.create("my_adapter", config)
```

---

## Realtime Adapters

### OpenAI Realtime (`openai_realtime`)

Combined LLM+TTS adapter using OpenAI's Realtime WebSocket API.

**Location**: `src/tth/adapters/realtime/openai_realtime.py`

**Features**:
- Single WebSocket connection for LLM + TTS
- Streams text deltas and PCM audio chunks
- Lower latency than separate LLM→TTS pipeline
- Supports interrupt via `response.cancel`

**Configuration**:
```yaml
components:
  realtime:
    primary: openai_realtime
    model: gpt-4o-realtime-preview-2024-12-17
```

**API Key**: `OPENAI_API_KEY`

**Lifecycle**:
```python
# Connect once at session start
await adapter.connect(system_instructions="You are a helpful assistant.", voice="alloy")

# Send user text and stream response
await adapter.send_user_text("Hello!")
async for event in adapter.stream_events():
    if isinstance(event, TextDeltaEvent):
        print(event.token)
    elif isinstance(event, AudioChunkEvent):
        play_audio(event.data)

# Cancel if needed
await adapter.cancel_response()

# Close at session end
await adapter.close()
```

**Voice Mapping**:
| Emotion | Voice |
|---------|-------|
| neutral | alloy |
| happy | echo |
| sad | onyx |
| angry | shimmer |
| surprised | nova |

---

## LLM Adapters

### OpenAI Chat (`openai_chat`)

Streaming LLM adapter using OpenAI Chat Completions API.

**Location**: `src/tth/adapters/llm/openai_api.py`

**Features**:
- Streaming token output
- System prompt injection via control mapper
- Multi-turn conversation support

**Configuration**:
```yaml
components:
  llm:
    primary: openai_chat
    model: gpt-4o-mini
```

**API Key**: `OPENAI_API_KEY`

**Note**: This adapter is used by the `offline_mock` profile. The default profile uses the Realtime API instead.

### Mock LLM (`mock_llm`)

Deterministic mock adapter for offline testing.

**Location**: `src/tth/adapters/llm/mock_llm.py`

**Features**:
- No API calls required
- Deterministic output based on input
- Fast for CI/local testing

**Configuration**:
```yaml
components:
  llm:
    primary: mock_llm
```

---

## TTS Adapters

### OpenAI TTS (`openai_tts`)

Streaming TTS adapter using OpenAI Text-to-Speech API.

**Location**: `src/tth/adapters/tts/openai_tts.py`

**Features**:
- Streaming PCM audio output
- Voice selection via emotion mapping
- Speed control via character settings

**Configuration**:
```yaml
components:
  tts:
    primary: openai_tts
    model: tts-1
```

**API Key**: `OPENAI_API_KEY`

**Note**: This adapter is used by the `offline_mock` profile. The default profile uses the Realtime API instead.

### Mock TTS (`mock_tts`)

Deterministic mock adapter for offline testing.

**Location**: `src/tth/adapters/tts/mock_tts.py`

**Features**:
- No API calls required
- Generates pseudo-audio data
- Fast for CI/local testing

**Configuration**:
```yaml
components:
  tts:
    primary: mock_tts
```

---

## Avatar Adapters

### Stub Avatar (`stub_avatar`)

Placeholder avatar adapter for testing and development.

**Location**: `src/tth/adapters/avatar/stub.py`

**Features**:
- No external API required
- Generates raw RGB frames
- Sync-friendly timestamps for drift testing

**Configuration**:
```yaml
components:
  avatar:
    primary: stub_avatar
```

**Output Format**:
- `content_type`: `"raw_rgb"`
- Dimensions: 320x240 pixels
- Data: `width * height * 3` bytes per frame

---

## Adding New Adapters

### Adding a Streaming Adapter

1. Create the adapter file:
```python
# src/tth/adapters/tts/my_tts.py
from tth.adapters.base import AdapterBase
from tth.core.registry import register
from tth.core.types import AudioChunk, HealthStatus, TurnControl

@register("my_tts")
class MyTTSAdapter(AdapterBase):
    async def infer_stream(self, input, control: TurnControl, context):
        # Convert input text to audio
        for chunk in generate_audio(input):
            yield AudioChunk(
                data=chunk.bytes,
                timestamp_ms=chunk.timestamp,
                duration_ms=chunk.duration,
                encoding="pcm",
                sample_rate=24000,
            )

    async def health(self) -> HealthStatus:
        return HealthStatus(healthy=True)
```

2. Add configuration:
```yaml
# config/base.yaml or profile
components:
  tts:
    primary: my_tts
```

### Adding a Realtime Adapter

1. Create the adapter file:
```python
# src/tth/adapters/realtime/my_realtime.py
from tth.adapters.base import AdapterBase
from tth.core.registry import register

@register("my_realtime")
class MyRealtimeAdapter(AdapterBase):
    async def connect(self, system_instructions: str, voice: str) -> None:
        """Establish connection at session start."""
        ...

    async def send_user_text(self, text: str) -> None:
        """Send user message."""
        ...

    async def stream_events(self):
        """Yield TextDeltaEvent, AudioChunkEvent, TurnCompleteEvent."""
        ...

    async def cancel_response(self) -> None:
        """Cancel current generation."""
        ...

    async def close(self) -> None:
        """Close connection."""
        ...

    async def infer_stream(self, input, control, context):
        raise NotImplementedError("Use send_user_text + stream_events")

    async def health(self) -> HealthStatus:
        return HealthStatus(healthy=self._is_connected)
```

2. Update orchestrator if needed to use the new adapter.

3. Add configuration:
```yaml
# config/base.yaml or profile
components:
  realtime:
    primary: my_realtime
```
