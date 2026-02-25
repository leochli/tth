# src/tth/control/personas.py
from __future__ import annotations
from tth.core.types import CharacterControl, EmotionControl, EmotionLabel, TurnControl


# Named persona presets — mirrors config/base.yaml personas section.
# Used when persona_id is specified but full config is not loaded.
_PRESETS: dict[str, TurnControl] = {
    "default": TurnControl(
        emotion=EmotionControl(
            label=EmotionLabel.NEUTRAL,
            intensity=0.5,
            valence=0.0,
            arousal=0.0,
        ),
        character=CharacterControl(
            persona_id="default",
            speech_rate=1.0,
            pitch_shift=0.0,
            expressivity=0.6,
            motion_gain=1.0,
        ),
    ),
    "professional": TurnControl(
        emotion=EmotionControl(
            label=EmotionLabel.NEUTRAL,
            intensity=0.3,
            valence=0.1,
            arousal=-0.1,
        ),
        character=CharacterControl(
            persona_id="professional",
            speech_rate=0.95,
            pitch_shift=0.0,
            expressivity=0.4,
            motion_gain=0.7,
        ),
    ),
    "casual": TurnControl(
        emotion=EmotionControl(
            label=EmotionLabel.HAPPY,
            intensity=0.4,
            valence=0.3,
            arousal=0.1,
        ),
        character=CharacterControl(
            persona_id="casual",
            speech_rate=1.05,
            pitch_shift=0.0,
            expressivity=0.7,
            motion_gain=1.1,
        ),
    ),
    "excited": TurnControl(
        emotion=EmotionControl(
            label=EmotionLabel.HAPPY,
            intensity=0.8,
            valence=0.7,
            arousal=0.6,
        ),
        character=CharacterControl(
            persona_id="excited",
            speech_rate=1.2,
            pitch_shift=0.05,
            expressivity=0.9,
            motion_gain=1.5,
        ),
    ),
}


def get_persona_defaults(persona_id: str) -> TurnControl:
    """Return persona preset defaults, falling back to 'default' if not found."""
    return _PRESETS.get(persona_id, _PRESETS["default"])


def get_persona_name(persona_id: str) -> str:
    names = {
        "default": "Assistant",
        "professional": "Professional",
        "casual": "Casual",
        "excited": "Excited",
    }
    return names.get(persona_id, "Assistant")


def list_personas() -> list[str]:
    return list(_PRESETS.keys())
