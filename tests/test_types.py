# tests/test_types.py
"""Unit tests for core types — serialization, validation, edge cases."""

import pytest
from tth.core.types import (
    EmotionControl,
    EmotionLabel,
    CharacterControl,
    TurnControl,
    AudioChunk,
    VideoFrame,
    TextDeltaEvent,
    AudioChunkEvent,
    VideoFrameEvent,
    TurnCompleteEvent,
    ErrorEvent,
    UserTextEvent,
    InterruptEvent,
    ControlUpdateEvent,
    estimate_mp3_duration_ms,
)


# ── EmotionControl ────────────────────────────────────────────────────────────


def test_emotion_defaults():
    e = EmotionControl()
    assert e.label == EmotionLabel.NEUTRAL
    assert e.intensity == 0.5
    assert e.valence == 0.0
    assert e.arousal == 0.0


def test_emotion_validation_intensity_bounds():
    with pytest.raises(Exception):
        EmotionControl(intensity=1.5)
    with pytest.raises(Exception):
        EmotionControl(intensity=-0.1)


def test_emotion_validation_valence_bounds():
    with pytest.raises(Exception):
        EmotionControl(valence=1.5)
    with pytest.raises(Exception):
        EmotionControl(valence=-1.5)


def test_emotion_all_labels():
    for label in EmotionLabel:
        e = EmotionControl(label=label)
        assert e.label == label


# ── CharacterControl ──────────────────────────────────────────────────────────


def test_character_defaults():
    c = CharacterControl()
    assert c.persona_id == "default"
    assert c.speech_rate == 1.0
    assert c.expressivity == 0.6
    assert c.motion_gain == 1.0


def test_character_speech_rate_bounds():
    with pytest.raises(Exception):
        CharacterControl(speech_rate=0.1)  # below 0.25
    with pytest.raises(Exception):
        CharacterControl(speech_rate=5.0)  # above 4.0


# ── TurnControl ───────────────────────────────────────────────────────────────


def test_turn_control_defaults():
    tc = TurnControl()
    assert tc.emotion == EmotionControl()
    assert tc.character == CharacterControl()


def test_turn_control_equality():
    tc1 = TurnControl()
    tc2 = TurnControl()
    assert tc1 == tc2


# ── AudioChunk ────────────────────────────────────────────────────────────────


def test_audio_chunk_fields():
    chunk = AudioChunk(
        data=b"\xff\xfb\x90\x00" * 100,
        timestamp_ms=1000.0,
        duration_ms=256.0,
    )
    assert chunk.encoding == "mp3"
    assert chunk.sample_rate == 24000
    assert chunk.duration_ms > 0


def test_estimate_mp3_duration_ms():
    # 4096 bytes at 128 kbps = (4096 * 8) / (128000) = 0.256 seconds = 256 ms
    dur = estimate_mp3_duration_ms(b"\x00" * 4096, bitrate_kbps=128)
    assert abs(dur - 256.0) < 0.01


def test_estimate_mp3_duration_nonzero():
    # Any non-empty chunk must yield duration > 0
    dur = estimate_mp3_duration_ms(b"\x00" * 1, bitrate_kbps=128)
    assert dur > 0


# ── VideoFrame ────────────────────────────────────────────────────────────────


def test_video_frame_content_type():
    frame = VideoFrame(
        data=bytes(256 * 256 * 3),
        timestamp_ms=0.0,
        frame_index=0,
        width=256,
        height=256,
        content_type="raw_rgb",
    )
    assert frame.content_type == "raw_rgb"


def test_video_frame_invalid_content_type():
    with pytest.raises(Exception):
        VideoFrame(
            data=b"x",
            timestamp_ms=0.0,
            frame_index=0,
            width=1,
            height=1,
            content_type="invalid_type",
        )


# ── Event serialization ───────────────────────────────────────────────────────


def test_text_delta_event_json():
    evt = TextDeltaEvent(token="Hello")
    j = evt.model_dump_json()
    assert '"type":"text_delta"' in j
    assert '"token":"Hello"' in j


def test_audio_chunk_event_bytes_base64():
    """bytes data field must be serialized as base64 in JSON (field_serializer)."""
    import base64

    raw = b"\xff\xfb\x90\x00"
    evt = AudioChunkEvent(data=raw, timestamp_ms=100.0, duration_ms=50.0)
    j = evt.model_dump_json()
    # field_serializer encodes bytes as base64 string
    b64 = base64.b64encode(raw).decode()
    assert b64 in j
    assert '"type":"audio_chunk"' in j


def test_video_frame_event_json():
    raw = bytes(256 * 256 * 3)
    evt = VideoFrameEvent(
        data=raw,
        timestamp_ms=0.0,
        frame_index=0,
        width=256,
        height=256,
        content_type="raw_rgb",
        drift_ms=5.0,
    )
    j = evt.model_dump_json()
    assert '"type":"video_frame"' in j
    assert '"content_type":"raw_rgb"' in j


def test_turn_complete_event():
    evt = TurnCompleteEvent(turn_id="abc-123")
    j = evt.model_dump_json()
    assert '"type":"turn_complete"' in j
    assert "abc-123" in j


def test_error_event():
    evt = ErrorEvent(code="turn_error", message="Something went wrong")
    j = evt.model_dump_json()
    assert '"type":"error"' in j
    assert "turn_error" in j


# ── Inbound event parsing ─────────────────────────────────────────────────────


def test_user_text_event():
    evt = UserTextEvent(type="user_text", text="Hello!")
    assert evt.text == "Hello!"
    assert evt.control == TurnControl()


def test_user_text_event_with_control():
    evt = UserTextEvent(
        type="user_text",
        text="Hi",
        control={"emotion": {"label": "happy", "intensity": 0.8}, "character": {}},
    )
    assert evt.control.emotion.label == EmotionLabel.HAPPY
    assert evt.control.emotion.intensity == 0.8


def test_interrupt_event():
    evt = InterruptEvent()
    assert evt.type == "interrupt"


def test_control_update_event():
    evt = ControlUpdateEvent(
        type="control_update",
        control={"emotion": {"label": "sad"}, "character": {}},
    )
    assert evt.control.emotion.label == EmotionLabel.SAD
