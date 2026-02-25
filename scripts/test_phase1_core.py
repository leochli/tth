#!/usr/bin/env python3
"""
Phase 1: Core Types & Config Test
Tests that all core types serialize/deserialize correctly and config loads.
"""
from __future__ import annotations
import sys


def test_core_types():
    print("=" * 60)
    print("PHASE 1: Core Types Test")
    print("=" * 60)

    from tth.core.types import (
        EmotionControl, EmotionLabel, CharacterControl, TurnControl,
        AudioChunk, VideoFrame, TextDeltaEvent, AudioChunkEvent,
        VideoFrameEvent, TurnCompleteEvent, ErrorEvent,
        UserTextEvent, InterruptEvent, ControlUpdateEvent,
        estimate_mp3_duration_ms,
    )
    import json

    # Test 1: EmotionControl
    print("\n[1/8] EmotionControl...")
    e = EmotionControl(label=EmotionLabel.HAPPY, intensity=0.8, arousal=0.5)
    assert e.label == EmotionLabel.HAPPY
    assert e.intensity == 0.8
    print("   ✓ EmotionControl works")

    # Test 2: CharacterControl
    print("[2/8] CharacterControl...")
    c = CharacterControl(persona_id="casual", speech_rate=1.2, expressivity=0.7)
    assert c.speech_rate == 1.2
    print("   ✓ CharacterControl works")

    # Test 3: TurnControl
    print("[3/8] TurnControl...")
    tc = TurnControl(emotion=e, character=c)
    assert tc.emotion.label == EmotionLabel.HAPPY
    print("   ✓ TurnControl works")

    # Test 4: AudioChunk with duration estimation
    print("[4/8] AudioChunk + duration estimation...")
    raw_audio = b"\xff\xfb\x90\x00" * 1000  # 4000 bytes
    dur = estimate_mp3_duration_ms(raw_audio, bitrate_kbps=128)
    assert dur > 0, "duration must be > 0"
    chunk = AudioChunk(data=raw_audio, timestamp_ms=0.0, duration_ms=dur)
    assert chunk.duration_ms == dur
    print(f"   ✓ AudioChunk works (duration={dur:.2f}ms)")

    # Test 5: VideoFrame
    print("[5/8] VideoFrame...")
    frame = VideoFrame(
        data=bytes(256 * 256 * 3),
        timestamp_ms=0.0,
        frame_index=0,
        width=256,
        height=256,
        content_type="raw_rgb",
    )
    assert frame.content_type == "raw_rgb"
    print("   ✓ VideoFrame works")

    # Test 6: Event JSON serialization (bytes as base64)
    print("[6/8] Event JSON serialization...")
    evt = AudioChunkEvent(data=b"\xff\xfb\x90\x00", timestamp_ms=100.0, duration_ms=50.0)
    j = evt.model_dump_json()
    parsed = json.loads(j)
    assert parsed["type"] == "audio_chunk"
    assert isinstance(parsed["data"], str)  # base64 string
    print("   ✓ Events serialize to JSON with base64 bytes")

    # Test 7: Inbound events parsing
    print("[7/8] Inbound events...")
    user_msg = '{"type": "user_text", "text": "Hello", "control": {}}'
    user_evt = UserTextEvent(**json.loads(user_msg))
    assert user_evt.text == "Hello"
    print("   ✓ Inbound events parse correctly")

    # Test 8: All emotion labels
    print("[8/8] All emotion labels...")
    for label in EmotionLabel:
        e = EmotionControl(label=label)
        assert e.label == label
    print(f"   ✓ All {len(EmotionLabel)} emotion labels work")

    print("\n" + "=" * 60)
    print("PHASE 1 PASSED: All core types working")
    print("=" * 60)
    return True


def test_config():
    print("\n" + "=" * 60)
    print("PHASE 1b: Config Test")
    print("=" * 60)

    from tth.core.config import settings

    # Check API key loaded
    assert settings.openai_api_key, "OPENAI_API_KEY not loaded!"
    print(f"[1/4] API Key loaded: {settings.openai_api_key[:15]}...")

    # Check profile
    print(f"[2/4] Profile: {settings.profile}")

    # Check components
    print(f"[3/4] Components:")
    print(f"      LLM:    {settings.components['llm']['primary']}")
    print(f"      TTS:    {settings.components['tts']['primary']}")
    print(f"      Avatar: {settings.components['avatar']['primary']}")

    # Check personas
    print(f"[4/4] Personas: {list(settings.personas.keys())}")

    print("\n" + "=" * 60)
    print("PHASE 1b PASSED: Config loaded correctly")
    print("=" * 60)
    return True


def test_registry():
    print("\n" + "=" * 60)
    print("PHASE 1c: Registry Test")
    print("=" * 60)

    import tth.adapters.llm.openai_api
    import tth.adapters.tts.openai_tts
    import tth.adapters.avatar.stub
    from tth.core.registry import list_registered, get

    registered = list_registered()
    print(f"Registered adapters: {registered}")

    assert "openai_chat" in registered
    assert "openai_tts" in registered
    assert "stub_avatar" in registered

    print("\n" + "=" * 60)
    print("PHASE 1c PASSED: Registry working")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        test_core_types()
        test_config()
        test_registry()
        print("\n✅ ALL PHASE 1 TESTS PASSED\n")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ ASSERTION FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
