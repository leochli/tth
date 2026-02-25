# tests/test_mapper.py
"""Unit tests for control mapper."""

import pytest
from tth.core.types import (
    CharacterControl,
    EmotionControl,
    EmotionLabel,
    TurnControl,
)
from tth.control.mapper import (
    map_emotion_to_openai_tts,
    build_llm_system_prompt,
    resolve,
    merge_controls,
)


# ── map_emotion_to_openai_tts ─────────────────────────────────────────────────


def test_openai_tts_neutral_voice():
    result = map_emotion_to_openai_tts(EmotionControl(), CharacterControl())
    assert result["voice"] == "nova"
    assert result["speed"] == 1.0


def test_openai_tts_happy_voice():
    e = EmotionControl(label=EmotionLabel.HAPPY)
    result = map_emotion_to_openai_tts(e, CharacterControl())
    assert result["voice"] == "shimmer"


def test_openai_tts_sad_voice():
    e = EmotionControl(label=EmotionLabel.SAD)
    result = map_emotion_to_openai_tts(e, CharacterControl())
    assert result["voice"] == "onyx"


def test_openai_tts_all_emotions_have_voice():
    """Every emotion label should map to a valid voice name."""
    for label in EmotionLabel:
        e = EmotionControl(label=label)
        result = map_emotion_to_openai_tts(e, CharacterControl())
        assert isinstance(result["voice"], str)
        assert len(result["voice"]) > 0


def test_openai_tts_speed_clamped():
    # Extreme speech_rate + arousal should still be within [0.25, 4.0]
    e = EmotionControl(arousal=1.0)
    c = CharacterControl(speech_rate=4.0)
    result = map_emotion_to_openai_tts(e, c)
    assert 0.25 <= result["speed"] <= 4.0


def test_openai_tts_arousal_affects_speed():
    e_calm = EmotionControl(arousal=-1.0)
    e_excited = EmotionControl(arousal=1.0)
    c = CharacterControl(speech_rate=1.0)
    speed_calm = map_emotion_to_openai_tts(e_calm, c)["speed"]
    speed_excited = map_emotion_to_openai_tts(e_excited, c)["speed"]
    assert speed_excited > speed_calm


def test_openai_tts_character_speech_rate():
    e = EmotionControl()
    c_slow = CharacterControl(speech_rate=0.5)
    c_fast = CharacterControl(speech_rate=2.0)
    speed_slow = map_emotion_to_openai_tts(e, c_slow)["speed"]
    speed_fast = map_emotion_to_openai_tts(e, c_fast)["speed"]
    assert speed_fast > speed_slow


# ── build_llm_system_prompt ───────────────────────────────────────────────────


def test_llm_system_prompt_default():
    ctrl = TurnControl()
    prompt = build_llm_system_prompt(ctrl, "Assistant")
    assert "Assistant" in prompt
    assert "conversational" in prompt


def test_llm_system_prompt_happy_emotion():
    ctrl = TurnControl(emotion=EmotionControl(label=EmotionLabel.HAPPY, intensity=0.8))
    prompt = build_llm_system_prompt(ctrl, "Bob")
    assert "happy" in prompt
    assert "0.8" in prompt


def test_llm_system_prompt_slow_speech():
    ctrl = TurnControl(character=CharacterControl(speech_rate=0.7))
    prompt = build_llm_system_prompt(ctrl)
    assert "slowly" in prompt


def test_llm_system_prompt_fast_speech():
    ctrl = TurnControl(character=CharacterControl(speech_rate=1.5))
    prompt = build_llm_system_prompt(ctrl)
    assert "brisk" in prompt or "energetic" in prompt


def test_llm_system_prompt_high_expressivity():
    ctrl = TurnControl(character=CharacterControl(expressivity=0.9))
    prompt = build_llm_system_prompt(ctrl)
    assert "expressive" in prompt


# ── resolve ───────────────────────────────────────────────────────────────────


def test_resolve_uses_persona_defaults_when_user_default():
    """If user sends default controls, persona defaults should win."""
    user = TurnControl()
    persona = TurnControl(
        emotion=EmotionControl(label=EmotionLabel.HAPPY, intensity=0.8),
    )
    result = resolve(user, persona)
    assert result.emotion.label == EmotionLabel.HAPPY


def test_resolve_user_wins_over_persona():
    """If user explicitly sets emotion, it should override persona."""
    user = TurnControl(
        emotion=EmotionControl(label=EmotionLabel.ANGRY, intensity=0.9),
    )
    persona = TurnControl(
        emotion=EmotionControl(label=EmotionLabel.HAPPY),
    )
    result = resolve(user, persona)
    assert result.emotion.label == EmotionLabel.ANGRY


# ── merge_controls ────────────────────────────────────────────────────────────


def test_merge_controls_override_wins():
    base = TurnControl(emotion=EmotionControl(label=EmotionLabel.SAD))
    override = TurnControl(emotion=EmotionControl(label=EmotionLabel.HAPPY))
    result = merge_controls(base, override)
    assert result.emotion.label == EmotionLabel.HAPPY


def test_merge_controls_base_fills_defaults():
    base = TurnControl(emotion=EmotionControl(label=EmotionLabel.SAD))
    override = TurnControl()  # all defaults
    result = merge_controls(base, override)
    assert result.emotion.label == EmotionLabel.SAD


def test_merge_controls_both_default_returns_default():
    base = TurnControl()
    override = TurnControl()
    result = merge_controls(base, override)
    assert result.emotion == EmotionControl()
