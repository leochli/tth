# src/tth/api/schemas.py
from __future__ import annotations
from pydantic import BaseModel, Field
from tth.core.types import (
    AdapterCapabilities,
    EmotionControl,
    CharacterControl,
    HealthStatus,
)


# ── Session lifecycle ─────────────────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    persona_id: str = "default"
    emotion: EmotionControl | None = None
    character: CharacterControl | None = None


class CreateSessionResponse(BaseModel):
    session_id: str


# ── Health ────────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    llm: HealthStatus
    tts: HealthStatus
    avatar: HealthStatus

    @property
    def all_healthy(self) -> bool:
        return self.llm.healthy and self.tts.healthy and self.avatar.healthy


# ── Models/Capabilities ───────────────────────────────────────────────────────


class ModelsResponse(BaseModel):
    llm: AdapterCapabilities
    tts: AdapterCapabilities
    avatar: AdapterCapabilities
