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

    async def interrupt(self) -> None:
        """Interrupt current inference and clear buffers. Optional.

        Override in subclasses that support interruptible streaming.
        Called when user sends InterruptEvent or new user_text arrives.
        """

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
| fearful | fable |
| disgusted | ash |

---

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
- Dimensions: 256x256 pixels
- Data: `width * height * 3` bytes per frame

---

### Mock Cloud Avatar (`mock_cloud_avatar`)

Simulates cloud avatar service with configurable latency for development and CI testing.

**Location**: `src/tth/adapters/avatar/mock_cloud.py`

**Features**:
- Simulates network + inference latency
- No external API required
- Generates JPEG frames
- Supports interrupt handling

**Configuration**:
```yaml
components:
  avatar:
    primary: mock_cloud_avatar
    mock_cloud_avatar:
      simulated_latency_ms: 150  # Network + inference latency
      resolution: [512, 512]
      fps: 25
```

**Output Format**:
- `content_type`: `"jpeg"`
- Dimensions: Configurable (default 512x512)

---

### Simli (`simli`)

Real-time audio-to-avatar streaming via Simli's lip-sync model.

**Location**: `src/tth/adapters/avatar/simli.py`

**Pipeline fit**: Designed for OpenAI Realtime API — accepts raw PCM audio (resampled from 24kHz to 16kHz by `AudioChunkBuffer`) and returns JPEG frames over a binary WebSocket. No browser-side WebRTC relay needed; the server manages the Simli connection and sends `video_frame` events to the browser over the existing WebSocket.

**Push-model relay**: The orchestrator starts a persistent relay task at session start. Audio chunks from the Realtime API are continuously forwarded to Simli for the lifetime of the WebSocket connection, ensuring uninterrupted lip-sync across turns.

**Latency**: <300ms audio-to-video

**Configuration**:
```yaml
components:
  avatar:
    primary: simli
    simli:
      face_id: "5514e24d-6086-46a3-ace4-6a7264e5cb7c"  # preset face UUID
      api_key_env: "SIMLI_API_KEY"
      resolution: [512, 512]
      fps: 25
      min_chunk_ms: 100
      target_sample_rate: 16000
```

**API Key**: `SIMLI_API_KEY`. Preset face IDs: https://docs.simli.com/api-reference/preset-faces

**Protocol**:

| Direction | Transport | Format |
|-----------|-----------|--------|
| TTH → Simli (session init) | HTTP POST `/compose/token` | JSON — returns `session_token` |
| TTH → Simli (audio) | WebSocket binary | Raw PCM Int16, 16kHz mono |
| Simli → TTH (video) | WebSocket binary | JPEG bytes per frame |

**WebSocket URL**: `wss://api.simli.ai/compose/webrtc/p2p?session_token=<token>`

**Audio pipeline**:
1. `AudioChunk` from Realtime API (24kHz PCM)
2. Buffered until `min_chunk_ms` accumulated (default 100ms)
3. Resampled to 16kHz by `AudioChunkBuffer`
4. Sent as raw binary over Simli WebSocket
5. Binary JPEG frames received by `_listen()` loop and enqueued

---

### Cloud Avatar Base Class

Base class for implementing custom cloud avatar adapters.

**Location**: `src/tth/adapters/avatar/cloud_base.py`

**Features**:
- WebSocket connection management with retries
- Automatic reconnection with exponential backoff
- Health monitoring (stale connection detection)
- Frame queue with backpressure handling
- Interrupt support
- Fallback to stub adapter on failure

**To implement a custom cloud adapter**:
```python
from tth.adapters.avatar.cloud_base import CloudAvatarAdapterBase
from tth.core.registry import register

@register("my_cloud_avatar")
class MyCloudAvatarAdapter(CloudAvatarAdapterBase):
    def _get_auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {os.environ.get('MY_API_KEY')}"}

    async def load(self) -> None:
        # Validate endpoint, preload assets
        ...

    async def infer_stream(self, input, control, context):
        # Use inherited _connect(), _send_session_init(), _send_audio_chunk()
        ...
```

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
