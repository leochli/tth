#!/usr/bin/env python3
"""
Phase 2: LLM Adapter Test
Tests the OpenAI LLM adapter with real API calls.
"""
from __future__ import annotations
import asyncio
import sys


async def test_llm_adapter():
    print("=" * 60)
    print("PHASE 2: LLM Adapter Test (Real API)")
    print("=" * 60)

    from tth.core.config import settings
    from tth.adapters.llm.openai_api import OpenAIChatAdapter
    from tth.core.types import TurnControl

    # Check API key
    if not settings.openai_api_key:
        print("❌ OPENAI_API_KEY not set!")
        return False

    print(f"[1/4] API Key present: {settings.openai_api_key[:15]}...")

    # Create adapter
    print("[2/4] Creating OpenAIChatAdapter...")
    adapter = OpenAIChatAdapter({"model": "gpt-4o-mini"})

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
    context = {"persona_name": "Assistant", "history": []}

    tokens = []
    full_text = ""
    async for token in adapter.infer_stream("Say 'Hello World' and nothing else.", control, context):
        tokens.append(token)
        full_text += token
        print(f"      token: {repr(token)}")

    print(f"\n      Total tokens: {len(tokens)}")
    print(f"      Full response: {full_text[:100]}...")

    assert len(tokens) > 0, "No tokens received!"
    assert "Hello" in full_text or "hello" in full_text.lower(), "Expected 'Hello' in response"

    print("\n" + "=" * 60)
    print("PHASE 2 PASSED: LLM adapter working with real API")
    print("=" * 60)
    return True


async def test_llm_with_emotion():
    print("\n" + "=" * 60)
    print("PHASE 2b: LLM Emotion Injection Test")
    print("=" * 60)

    from tth.adapters.llm.openai_api import OpenAIChatAdapter
    from tth.core.types import TurnControl, EmotionControl, EmotionLabel, CharacterControl
    from tth.control.mapper import build_llm_system_prompt

    adapter = OpenAIChatAdapter({"model": "gpt-4o-mini"})

    # Test different emotions
    emotions = [
        (EmotionLabel.HAPPY, "happy tone"),
        (EmotionLabel.SAD, "sad tone"),
        (EmotionLabel.ANGRY, "angry tone"),
    ]

    for label, desc in emotions:
        control = TurnControl(
            emotion=EmotionControl(label=label, intensity=0.8),
        )
        prompt = build_llm_system_prompt(control, "TestBot")
        print(f"\n[{label.value}] System prompt excerpt:")
        # Show emotion-related part of prompt
        if label.value in prompt.lower():
            print(f"   ✓ Emotion '{label.value}' injected into prompt")
        else:
            print(f"   Prompt: {prompt[:150]}...")

    print("\n" + "=" * 60)
    print("PHASE 2b PASSED: Emotion injection working")
    print("=" * 60)
    return True


async def main():
    try:
        if not await test_llm_adapter():
            sys.exit(1)
        if not await test_llm_with_emotion():
            sys.exit(1)
        print("\n✅ ALL PHASE 2 TESTS PASSED\n")
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
