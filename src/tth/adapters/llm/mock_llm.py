# src/tth/adapters/llm/mock_llm.py
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from tth.adapters.base import AdapterBase
from tth.core.registry import register
from tth.core.types import AdapterCapabilities, HealthStatus, TurnControl


_TONE_PREFIX = {
    "neutral": "Here is a clear answer.",
    "happy": "Great question, this is exciting.",
    "sad": "I understand, here is a calm response.",
    "angry": "Let us be direct and focused.",
    "surprised": "Interesting twist, here is what matters.",
    "fearful": "Carefully and step by step, here is the answer.",
    "disgusted": "Let us keep this practical and concise.",
}


@register("mock_llm")
class MockLLMAdapter(AdapterBase):
    """Deterministic token-streaming adapter for offline/integration testing."""

    async def infer_stream(
        self, input: str, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[str]:
        tone = control.emotion.label.value
        prefix = _TONE_PREFIX.get(tone, _TONE_PREFIX["neutral"])
        text = (
            f"{prefix} You asked: {input.strip()} "
            f"I will keep the answer short, useful, and easy to act on."
        )
        # Emit word-level tokens to emulate LLM streaming behavior.
        for word in text.split():
            yield f"{word} "
            await asyncio.sleep(0.005)

    async def health(self) -> HealthStatus:
        return HealthStatus(healthy=True, latency_ms=0.1, detail="mock llm")

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_emotion=True,
            supports_identity=False,
            max_text_length=100000,
            supported_emotions=[
                "neutral",
                "happy",
                "sad",
                "angry",
                "surprised",
                "fearful",
                "disgusted",
            ],
        )
