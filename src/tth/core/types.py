# src/tth/core/types.py
from __future__ import annotations
import base64
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, field_serializer


# ── Controls ──────────────────────────────────────────────────────────────────


class EmotionLabel(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    FEARFUL = "fearful"
    DISGUSTED = "disgusted"


class EmotionControl(BaseModel):
    label: EmotionLabel = EmotionLabel.NEUTRAL
    intensity: float = Field(0.5, ge=0.0, le=1.0)
    valence: float = Field(0.0, ge=-1.0, le=1.0)  # -1=negative  +1=positive
    arousal: float = Field(0.0, ge=-1.0, le=1.0)  # -1=calm      +1=excited


class CharacterControl(BaseModel):
    persona_id: str = "default"
    speech_rate: float = Field(1.0, ge=0.25, le=4.0)
    pitch_shift: float = Field(0.0, ge=-1.0, le=1.0)
    expressivity: float = Field(0.6, ge=0.0, le=1.0)
    motion_gain: float = Field(1.0, ge=0.0, le=2.0)


class TurnControl(BaseModel):
    emotion: EmotionControl = Field(default_factory=EmotionControl)
    character: CharacterControl = Field(default_factory=CharacterControl)


# ── Media ─────────────────────────────────────────────────────────────────────


class AudioChunk(BaseModel):
    """Internal pipeline type — not sent over WS directly."""

    data: bytes  # raw MP3 bytes (not base64 — internal only)
    timestamp_ms: float
    duration_ms: float  # computed from byte count + bitrate (never 0.0)
    sample_rate: int = 24000
    encoding: str = "mp3"


def estimate_mp3_duration_ms(data: bytes, bitrate_kbps: int = 128) -> float:
    """Duration of raw MP3 bytes at a known constant bitrate."""
    return (len(data) * 8) / (bitrate_kbps * 1000) * 1000


def estimate_pcm_duration_ms(data: bytes, sample_rate: int = 24000) -> float:
    """Duration of raw PCM bytes (16-bit mono)."""
    samples = len(data) / 2  # 16-bit = 2 bytes per sample
    return (samples / sample_rate) * 1000


class VideoFrame(BaseModel):
    """Internal pipeline type — not sent over WS directly."""

    data: bytes  # raw bytes (not base64 — internal only)
    timestamp_ms: float
    frame_index: int
    width: int
    height: int
    content_type: Literal["jpeg", "h264_nal", "raw_rgb"] = "jpeg"
    # "raw_rgb":  stub adapter only — width*height*3 bytes, not a valid JPEG
    # "jpeg":     all production adapters — decodable by standard image libs
    # "h264_nal": future video streaming adapters


# ── Status ────────────────────────────────────────────────────────────────────


class HealthStatus(BaseModel):
    healthy: bool
    latency_ms: float | None = None
    detail: str = ""


class AdapterCapabilities(BaseModel):
    supports_streaming: bool = True
    supports_emotion: bool = False
    supports_identity: bool = False
    max_text_length: int = 5000
    supported_emotions: list[str] = []


# ── Events (outbound to client) ───────────────────────────────────────────────


class TextDeltaEvent(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    token: str


class AudioChunkEvent(BaseModel):
    """WS outbound event. `data` is base64-encoded audio bytes in JSON transport.
    Clients must base64-decode `data` before playback. encoding tells client format."""

    type: Literal["audio_chunk"] = "audio_chunk"
    data: bytes  # base64 in JSON; raw bytes in memory
    timestamp_ms: float
    duration_ms: float
    encoding: str = "pcm"  # "pcm" | "mp3"
    sample_rate: int = 24000  # Hz

    @field_serializer("data")
    def _encode_data(self, v: bytes) -> str:
        return base64.b64encode(v).decode()


class VideoFrameEvent(BaseModel):
    """WS outbound event. `data` is base64-encoded in JSON transport.
    content_type tells the client how to interpret the decoded bytes:
    'raw_rgb' → width*height*3 raw bytes; 'jpeg' → standard JPEG."""

    type: Literal["video_frame"] = "video_frame"
    data: bytes  # base64 in JSON; raw bytes in memory
    timestamp_ms: float
    frame_index: int
    width: int
    height: int
    content_type: str  # "jpeg" | "raw_rgb" | "h264_nal"
    drift_ms: float

    @field_serializer("data")
    def _encode_data(self, v: bytes) -> str:
        return base64.b64encode(v).decode()


class TurnCompleteEvent(BaseModel):
    type: Literal["turn_complete"] = "turn_complete"
    turn_id: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


# ── Events (inbound from client) ─────────────────────────────────────────────


class UserTextEvent(BaseModel):
    type: Literal["user_text"] = "user_text"
    text: str
    control: TurnControl = Field(default_factory=TurnControl)


class InterruptEvent(BaseModel):
    type: Literal["interrupt"] = "interrupt"


class ControlUpdateEvent(BaseModel):
    type: Literal["control_update"] = "control_update"
    control: TurnControl


InboundEvent = UserTextEvent | InterruptEvent | ControlUpdateEvent
