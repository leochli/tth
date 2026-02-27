# src/tth/adapters/tts/__init__.py
"""TTS adapter implementations."""

from tth.adapters.tts.openai_tts import OpenAITTSAdapter
from tth.adapters.tts.mock_tts import MockTTSAdapter

__all__ = ["OpenAITTSAdapter", "MockTTSAdapter"]
