# src/tth/control/mapper.py
from __future__ import annotations
from tth.core.types import (
    CharacterControl,
    EmotionControl,
    EmotionLabel,
    TurnControl,
)


# ── OpenAI TTS mappings ───────────────────────────────────────────────────────

_OPENAI_VOICE_MAP: dict[EmotionLabel, str] = {
    EmotionLabel.NEUTRAL: "nova",
    EmotionLabel.HAPPY: "shimmer",
    EmotionLabel.SAD: "onyx",
    EmotionLabel.ANGRY: "echo",
    EmotionLabel.SURPRISED: "fable",
    EmotionLabel.FEARFUL: "alloy",
    EmotionLabel.DISGUSTED: "echo",
}


def map_emotion_to_openai_tts(emotion: EmotionControl, character: CharacterControl) -> dict:
    """
    OpenAI TTS has no direct emotion parameter, so we proxy it via:
    - voice selection (different voices carry different tonal qualities)
    - speed adjustment driven by arousal level (excited=faster, calm=slower)
    """
    speed_mod = 1.0 + (emotion.arousal * 0.15)  # ±15% speed from arousal
    speed = round(max(0.25, min(4.0, character.speech_rate * speed_mod)), 2)
    return {
        "voice": _OPENAI_VOICE_MAP.get(emotion.label, "alloy"),
        "speed": speed,
    }


# ── LLM system prompt injection ───────────────────────────────────────────────


def build_llm_system_prompt(control: TurnControl, persona_name: str = "Assistant") -> str:
    """
    Injects emotion + character into the LLM system prompt so the model
    generates text with the target emotional register before TTS is applied.
    """
    e, c = control.emotion, control.character
    parts = [f"You are {persona_name}."]

    if e.label != EmotionLabel.NEUTRAL or e.intensity > 0.3:
        parts.append(f"Respond with a {e.label.value} tone (intensity {e.intensity:.1f}/1.0).")
    if c.speech_rate < 0.85:
        parts.append("Speak slowly and deliberately.")
    elif c.speech_rate > 1.2:
        parts.append("Speak at a brisk, energetic pace.")
    if c.expressivity > 0.7:
        parts.append("Be expressive and emotionally engaged.")

    parts.append("Keep responses conversational and appropriately brief.")
    return " ".join(parts)


# ── Control merge ─────────────────────────────────────────────────────────────


def resolve(user_control: TurnControl, persona_defaults: TurnControl) -> TurnControl:
    """
    Merge user-supplied controls with persona defaults.
    User values win; fall back to persona defaults for unset fields.
    A field is considered "unset" if it equals the type default.
    """
    user_emotion_is_default = user_control.emotion == EmotionControl()
    user_character_is_default = user_control.character.persona_id == "default"
    return TurnControl(
        emotion=(persona_defaults.emotion if user_emotion_is_default else user_control.emotion),
        character=(
            persona_defaults.character if user_character_is_default else user_control.character
        ),
    )


def merge_controls(base: TurnControl, override: TurnControl) -> TurnControl:
    """
    Merge a stored pending_control (base) with a new UserTextEvent's control (override).
    Override fields win over base; base fills in defaults.
    Called in routes.py to apply ControlUpdateEvent on the next turn.
    """
    base_emotion_is_default = base.emotion == EmotionControl()
    base_character_is_default = base.character == CharacterControl()
    over_emotion_is_default = override.emotion == EmotionControl()
    over_character_is_default = override.character == CharacterControl()
    return TurnControl(
        emotion=(
            override.emotion
            if not over_emotion_is_default
            else base.emotion
            if not base_emotion_is_default
            else EmotionControl()
        ),
        character=(
            override.character
            if not over_character_is_default
            else base.character
            if not base_character_is_default
            else CharacterControl()
        ),
    )


# ── Future provider mappings (add here when upgrading) ────────────────────────
# def map_emotion_to_elevenlabs(emotion, character) -> dict: ...
# def map_emotion_to_heygen(emotion, character) -> dict: ...
