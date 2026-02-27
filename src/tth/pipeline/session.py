# src/tth/pipeline/session.py
from __future__ import annotations
import asyncio
import uuid
from typing import Any
from tth.alignment.drift import DriftController
from tth.core.types import EmotionControl, CharacterControl, TurnControl
from tth.control.personas import get_persona_defaults, get_persona_name


class Session:
    """Per-session state machine."""

    VALID_STATES = frozenset(
        {
            "IDLE",
            "LLM_RUN",
            "CTRL_MERGE",
            "TTS_RUN",
            "AVATAR_RUN",
            "STREAMING_OUTPUT",
            "TURN_COMPLETE",
            "TURN_ERROR",
            "INTERRUPTED",
        }
    )

    def __init__(
        self,
        session_id: str,
        persona_defaults: TurnControl,
        persona_name: str = "Assistant",
    ) -> None:
        self.id = session_id
        self.persona_defaults = persona_defaults
        self.context: dict[str, Any] = {
            "history": [],
            "persona_name": persona_name,
        }
        self.pending_control: TurnControl | None = None
        self.current_turn_task: asyncio.Task[None] | None = None
        self.drift_controller = DriftController()
        self._state: str = "IDLE"

    def transition(self, state: str) -> None:
        assert state in self.VALID_STATES, f"Unknown state: {state}"
        self._state = state

    @property
    def state(self) -> str:
        return self._state

    async def cancel_current_turn(self) -> None:
        if self.current_turn_task and not self.current_turn_task.done():
            self.current_turn_task.cancel()
            try:
                await self.current_turn_task
            except asyncio.CancelledError:
                pass
        self.current_turn_task = None
        self._state = "IDLE"

    def append_history(self, role: str, content: str) -> None:
        """Append a message to conversation history for multi-turn context."""
        self.context["history"].append({"role": role, "content": content})

    def reset_drift(self) -> None:
        self.drift_controller.reset()


class SessionManager:
    """Global registry of active sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(
        self,
        persona_id: str = "default",
        emotion: EmotionControl | None = None,
        character: CharacterControl | None = None,
    ) -> Session:
        session_id = str(uuid.uuid4())
        persona_defaults = get_persona_defaults(persona_id)
        persona_name = get_persona_name(persona_id)
        session = Session(
            session_id=session_id,
            persona_defaults=persona_defaults,
            persona_name=persona_name,
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def get_or_404(self, session_id: str) -> Session:
        session = self.get(session_id)
        if session is None:
            raise KeyError(f"Session '{session_id}' not found")
        return session

    def close(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def __len__(self) -> int:
        return len(self._sessions)
