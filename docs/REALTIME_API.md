# OpenAI Realtime API Integration

This document describes the integration of OpenAI's Realtime API into TTH.

## Overview

The Realtime API provides a combined LLM+TTS experience via a single WebSocket connection. This significantly reduces latency compared to the traditional LLM → TTS pipeline by:

1. Eliminating the need for sentence buffering
2. Streaming audio directly from the model
3. Maintaining a persistent connection across turns

## Architecture

### Previous Pipeline (LLM → TTS → Avatar)

```
User Text → LLM (streaming tokens) → Sentence Buffer → TTS (audio chunks) → Avatar → Video
                    │
                    └── Wait for complete sentence before TTS starts
```

### Current Pipeline (Realtime → Avatar)

```
User Text → Realtime API (WebSocket) → Text + Audio (parallel) → Avatar → Video
                    │
                    └── Audio starts immediately, no buffering
```

## Connection Lifecycle

The Realtime adapter uses a session-scoped WebSocket connection:

```
Session Start                    Turn(s)                        Session End
     │                             │                                 │
     ▼                             ▼                                 ▼
┌─────────┐    ┌──────────────────────────────────────┐    ┌─────────┐
│ connect │───►│ send_user_text → stream_events (×N)  │───►│  close  │
└─────────┘    └──────────────────────────────────────┘    └─────────┘
```

### Connection

```python
# Called once at session start
await adapter.connect(
    system_instructions="You are a helpful assistant.",
    voice="alloy"  # Voice selection based on emotion
)
```

The `connect()` method:
1. Establishes WebSocket connection to `wss://api.openai.com/v1/realtime`
2. Sends `session.update` with configuration
3. Waits for `session.created` confirmation
4. Starts background listener task

### Turn Processing

```python
# For each user turn
await adapter.send_user_text("Hello, how are you?")

# Stream events until turn complete
async for event in adapter.stream_events():
    if isinstance(event, TextDeltaEvent):
        # Display text incrementally
        print(event.token, end="", flush=True)
    elif isinstance(event, AudioChunkEvent):
        # Play audio chunk
        audio_player.play(event.data)
    elif isinstance(event, TurnCompleteEvent):
        # Turn finished
        break
```

### Interrupt Handling

```python
# Cancel current response
await adapter.cancel_response()
```

This sends `response.cancel` to the API and clears the event queue.

### Session End

```python
# Close connection when session ends
await adapter.close()
```

## Event Types

### Server Events (from Realtime API)

| Event | Description |
|-------|-------------|
| `session.created` | Connection established |
| `session.updated` | Session configuration updated |
| `response.output_audio.delta` | Audio chunk (base64 PCM) |
| `response.output_audio_transcript.delta` | Text transcript delta |
| `response.done` | Response complete |
| `error` | API error |

### Internal Events (yielded by `stream_events()`)

| Event | Description |
|-------|-------------|
| `TextDeltaEvent` | Text token for display |
| `AudioChunkEvent` | PCM audio data |
| `TurnCompleteEvent` | Turn finished |

## Audio Format

The Realtime API outputs:

- **Format**: PCM (uncompressed)
- **Sample Rate**: 24000 Hz
- **Bit Depth**: 16-bit
- **Channels**: Mono

### Duration Calculation

```python
# For PCM data
duration_ms = len(data) / 2 / 24000 * 1000  # 16-bit = 2 bytes per sample
```

### Browser Playback

PCM audio can be played in browsers using the Web Audio API:

```javascript
// Convert Int16 PCM to Float32 for Web Audio API
const float32Data = new Float32Array(pcmData.length / 2);
const view = new DataView(pcmData.buffer);
for (let i = 0; i < float32Data.length; i++) {
    float32Data[i] = view.getInt16(i * 2, true) / 32768.0;
}

// Schedule playback
const buffer = audioContext.createBuffer(1, float32Data.length, 24000);
buffer.getChannelData(0).set(float32Data);

const source = audioContext.createBufferSource();
source.buffer = buffer;
source.connect(audioContext.destination);
source.start(nextStartTime);
nextStartTime += buffer.duration;
```

## Voice Selection

Voices are selected based on `EmotionControl.label`:

```python
VOICE_MAP = {
    EmotionLabel.NEUTRAL: "alloy",
    EmotionLabel.HAPPY: "echo",
    EmotionLabel.SAD: "onyx",
    EmotionLabel.ANGRY: "shimmer",
    EmotionLabel.SURPRISED: "nova",
    EmotionLabel.FEARFUL: "fable",
    EmotionLabel.DISGUSTED: "ash",
}
```

## Limitations

The Realtime API has some limitations compared to separate LLM+TTS:

1. **No speech rate control**: `CharacterControl.speech_rate` is not supported
2. **No pitch shift**: `CharacterControl.pitch_shift` is not supported
3. **Limited expressivity**: `CharacterControl.expressivity` is not directly controllable
4. **Voice selection only**: Emotion affects voice selection, not speech characteristics

The orchestrator logs warnings when these parameters are non-default:

```python
# pipeline/orchestrator.py
if cc.speech_rate != 1.0 or cc.pitch_shift != 0.0:
    logger.warning("CharacterControl params not supported by Realtime API")
```

## Configuration

### Base Configuration

```yaml
# config/base.yaml
components:
  realtime:
    primary: openai_realtime
    model: gpt-4o-realtime-preview-2024-12-17
  avatar:
    primary: stub_avatar
```

### Environment Variables

```bash
OPENAI_API_KEY=sk-...  # Required
```

## Error Handling

### Connection Errors

```python
try:
    await adapter.connect(system_instructions, voice)
except Exception as e:
    logger.error(f"Failed to connect: {e}")
    # Fall back to alternative adapter or retry
```

### WebSocket Disconnects

The adapter handles disconnects gracefully:

```python
async def _listen(self) -> None:
    try:
        async for message in self._ws:
            event = json.loads(message)
            await self._handle_server_event(event)
    except websockets.ConnectionClosed as e:
        logger.warning(f"WebSocket closed: code={e.code}")
        self._is_connected = False
```

### API Errors

```python
# Error events from the API
if event_type == "error":
    error = event.get("error", {})
    logger.error(f"Realtime API error: {error}")
```

## Cost

The Realtime API is billed per minute of audio output:

- **Model**: `gpt-4o-realtime-preview-2024-12-17`
- **Cost**: ~$0.06 per minute of audio output

For a typical 5-turn conversation (~30 seconds audio):
- Estimated cost: ~$0.03

## Migration from LLM → TTS Pipeline

The separate LLM → TTS pipeline has been replaced by the Realtime API. Legacy LLM and TTS adapter files have been removed from the codebase. The orchestrator is hardcoded to use the Realtime API.

If you need speech rate or pitch control, these are not supported by the Realtime API (see Limitations above). A future mock realtime adapter could enable fully offline testing.
