#!/usr/bin/env python3
"""
Phase 3: TTS Adapter Test
Tests the OpenAI TTS adapter with real API calls.
"""
from __future__ import annotations
import asyncio
import sys


async def test_tts_adapter():
    print("=" * 60)
    print("PHASE 3: TTS Adapter Test (Real API)")
    print("=" * 60)

    from tth.core.config import settings
    from tth.adapters.tts.openai_tts import OpenAITTSAdapter
    from tth.core.types import TurnControl

    # Check API key
    if not settings.openai_api_key:
        print("❌ OPENAI_API_KEY not set!")
        return False

    print(f"[1/4] API Key present: {settings.openai_api_key[:15]}...")

    # Create adapter
    print("[2/4] Creating OpenAITTSAdapter...")
    adapter = OpenAITTSAdapter({"model": "tts-1"})

    # Test health check
    print("[3/4] Health check...")
    health = await adapter.health()
    print(f"      healthy={health.healthy}, latency={health.latency_ms:.0f}ms")
    if not health.healthy:
        print(f"      detail: {health.detail}")
        return False

    # Test streaming inference
    print("[4/4] Streaming inference test...")
    control = TurnControl()
    context = {}

    chunks = []
    total_bytes = 0
    total_duration = 0.0

    async for chunk in adapter.infer_stream("Hello, this is a test.", control, context):
        chunks.append(chunk)
        total_bytes += len(chunk.data)
        total_duration += chunk.duration_ms
        print(f"      chunk: {len(chunk.data)} bytes, duration={chunk.duration_ms:.1f}ms")

    print(f"\n      Total chunks: {len(chunks)}")
    print(f"      Total bytes: {total_bytes}")
    print(f"      Total duration: {total_duration:.1f}ms ({total_duration/1000:.2f}s)")

    assert len(chunks) > 0, "No audio chunks received!"
    assert total_bytes > 0, "No audio data received!"
    assert total_duration > 0, "Total duration must be > 0!"

    # Verify all chunks have valid duration_ms
    for i, chunk in enumerate(chunks):
        assert chunk.duration_ms > 0, f"Chunk {i} has invalid duration_ms={chunk.duration_ms}"

    print("\n" + "=" * 60)
    print("PHASE 3 PASSED: TTS adapter working with real API")
    print("=" * 60)
    return True


async def test_tts_emotion_mapping():
    print("\n" + "=" * 60)
    print("PHASE 3b: TTS Emotion Mapping Test")
    print("=" * 60)

    from tth.adapters.tts.openai_tts import OpenAITTSAdapter
    from tth.core.types import TurnControl, EmotionControl, EmotionLabel, CharacterControl
    from tth.control.mapper import map_emotion_to_openai_tts

    adapter = OpenAITTSAdapter({"model": "tts-1"})

    # Test different emotions produce different voice mappings
    emotions = [
        EmotionLabel.NEUTRAL,
        EmotionLabel.HAPPY,
        EmotionLabel.SAD,
        EmotionLabel.ANGRY,
    ]

    voices_used = set()
    for label in emotions:
        control = TurnControl(
            emotion=EmotionControl(label=label, intensity=0.5),
        )
        params = map_emotion_to_openai_tts(control.emotion, control.character)
        voice = params["voice"]
        speed = params["speed"]
        voices_used.add(voice)
        print(f"   {label.value:10} → voice={voice}, speed={speed}")

    print(f"\n   Unique voices used: {len(voices_used)}")
    assert len(voices_used) >= 2, "Expected different voices for different emotions!"

    # Test arousal affects speed
    print("\n   Testing arousal → speed mapping:")
    for arousal in [-1.0, 0.0, 1.0]:
        control = TurnControl(
            emotion=EmotionControl(arousal=arousal),
            character=CharacterControl(speech_rate=1.0),
        )
        params = map_emotion_to_openai_tts(control.emotion, control.character)
        print(f"      arousal={arousal:4.1f} → speed={params['speed']:.2f}")

    print("\n" + "=" * 60)
    print("PHASE 3b PASSED: Emotion mapping working")
    print("=" * 60)
    return True


async def main():
    try:
        if not await test_tts_adapter():
            sys.exit(1)
        if not await test_tts_emotion_mapping():
            sys.exit(1)
        print("\n✅ ALL PHASE 3 TESTS PASSED\n")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ ASSERTION FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
