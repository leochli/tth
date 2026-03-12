# src/tth/api/routes.py
from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Any, Optional
from tth.api.schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    HealthResponse,
    ModelsResponse,
)
from tth.core.types import (
    InterruptEvent,
    UserTextEvent,
    ControlUpdateEvent,
    ErrorEvent,
)
from tth.control.mapper import merge_controls

router = APIRouter()

# These are set by main.py at startup
_session_manager = None
_orchestrator = None


def set_session_manager(sm) -> None:
    global _session_manager
    _session_manager = sm


def set_orchestrator(orch) -> None:
    global _orchestrator
    _orchestrator = orch


def get_session_manager():
    return _session_manager


def get_orchestrator():
    return _orchestrator


# ── D-ID WebRTC Session Schemas ───────────────────────────────────────────────

class DIDConnectionResponse(BaseModel):
    """Response with D-ID WebRTC connection info."""
    agent_id: str
    stream_id: str
    session_id: str
    offer: Optional[dict[str, Any]] = None
    ice_servers: Optional[list[dict]] = None


class DIDSDPAnswerRequest(BaseModel):
    """SDP answer from browser."""
    sdp: str
    type: str = "answer"


class DIDICECandidateRequest(BaseModel):
    """ICE candidate from browser (flat RTCIceCandidate fields)."""
    candidate: str
    sdpMid: Optional[str] = None
    sdpMLineIndex: Optional[int] = None
    usernameFragment: Optional[str] = None


class DIDTextRequest(BaseModel):
    """Text to send to D-ID chat."""
    text: str


# ── Session lifecycle ─────────────────────────────────────────────────────────


@router.post("/v1/sessions", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest):
    sm = get_session_manager()
    session = sm.create(
        persona_id=req.persona_id,
        emotion=req.emotion,
        character=req.character,
    )
    return CreateSessionResponse(session_id=session.id)


# ── Real-time WebSocket ───────────────────────────────────────────────────────


@router.websocket("/v1/sessions/{session_id}/stream")
async def session_stream(ws: WebSocket, session_id: str):
    sm = get_session_manager()
    orch = get_orchestrator()

    try:
        session = sm.get_or_404(session_id)
    except KeyError:
        await ws.close(code=4004, reason="Session not found")
        return

    output_q: asyncio.Queue = asyncio.Queue(maxsize=64)
    await ws.accept()

    # ── Outbound: relay events to client; keep alive across turns ────────────
    async def send_loop() -> None:
        while True:
            event = await output_q.get()
            try:
                await ws.send_text(event.model_dump_json())
            except WebSocketDisconnect:
                return
            except Exception:
                return

    # ── Inbound: handle client messages ──────────────────────────────────────
    async def recv_loop() -> None:
        try:
            async for raw in ws.iter_text():
                evt = _parse_inbound(raw)
                if evt is None:
                    continue

                if isinstance(evt, UserTextEvent):
                    # Cancel any running turn, then start the new one.
                    await session.cancel_current_turn()

                    # Merge pending_control (from prior ControlUpdateEvent) with
                    # this turn's control, then clear pending so it isn't double-applied.
                    effective_control = (
                        merge_controls(session.pending_control, evt.control)
                        if session.pending_control is not None
                        else evt.control
                    )
                    session.pending_control = None

                    # Capture loop-local copies to avoid closure-over-loop-var bugs
                    _text = evt.text
                    _control = effective_control

                    async def _run(text=_text, control=_control) -> None:
                        try:
                            await orch.run_turn(session, text, control, output_q)
                        except asyncio.CancelledError:
                            pass  # clean interrupt; no error event needed
                        except Exception as exc:
                            await output_q.put(ErrorEvent(code="turn_error", message=str(exc)))

                    session.current_turn_task = asyncio.create_task(_run())

                elif isinstance(evt, InterruptEvent):
                    # Cancel the turn task
                    await session.cancel_current_turn()
                    # Also cancel the Realtime API response
                    await orch.realtime.cancel_response()
                    # Clear avatar buffers
                    await orch.avatar.interrupt()

                elif isinstance(evt, ControlUpdateEvent):
                    # Stored; will be merged into the control of the next UserTextEvent
                    session.pending_control = evt.control

        except WebSocketDisconnect:
            pass

    send_task = asyncio.create_task(send_loop())
    recv_task = asyncio.create_task(recv_loop())

    try:
        await recv_task  # exits on disconnect
    finally:
        send_task.cancel()
        await session.cancel_current_turn()
        sm.close(session_id)


# ── Utility endpoints ─────────────────────────────────────────────────────────


@router.get("/v1/health", response_model=HealthResponse)
async def health():
    orch = get_orchestrator()
    return HealthResponse(
        llm=await orch.realtime.health(),  # Realtime serves as combined LLM+TTS
        tts=await orch.realtime.health(),
        avatar=await orch.avatar.health(),
    )


@router.get("/v1/models", response_model=ModelsResponse)
async def models():
    orch = get_orchestrator()
    return ModelsResponse(
        llm=orch.realtime.capabilities(),  # Realtime serves as combined LLM+TTS
        tts=orch.realtime.capabilities(),
        avatar=orch.avatar.capabilities(),
    )


# ── D-ID WebRTC Session Endpoints ───────────────────────────────────────────
# These endpoints manage D-ID streaming sessions for browser WebRTC clients.
# The server creates sessions and relays SDP/ICE, while the browser connects
# directly to D-ID for video streaming.


@router.post("/v1/did/sessions/{session_id}/connect")
async def did_connect(session_id: str):
    """Create a D-ID streaming connection for a session.

    Returns connection info including SDP offer for browser WebRTC setup.
    """
    from tth.adapters.avatar.did_streaming import DIDStreamingAvatar
    from fastapi import HTTPException

    orch = get_orchestrator()
    if not orch or not isinstance(orch.avatar, DIDStreamingAvatar):
        raise HTTPException(status_code=503, detail="D-ID streaming not configured")

    conn_info = await orch.avatar.create_connection(session_id)
    if not conn_info:
        raise HTTPException(status_code=502, detail="Failed to create D-ID connection")

    return DIDConnectionResponse(
        agent_id=conn_info.agent_id,
        stream_id=conn_info.stream_id,
        session_id=conn_info.session_id,
        offer=conn_info.offer,
        ice_servers=conn_info.ice_servers,
    )


@router.post("/v1/did/sessions/{session_id}/sdp")
async def did_sdp(session_id: str, req: DIDSDPAnswerRequest) -> dict:
    """Submit SDP answer from browser to D-ID."""
    from tth.adapters.avatar.did_streaming import DIDStreamingAvatar

    orch = get_orchestrator()
    if not orch or not isinstance(orch.avatar, DIDStreamingAvatar):
        return {"success": False, "error": "D-ID streaming not configured"}

    success = await orch.avatar.submit_sdp_answer(session_id, {"sdp": req.sdp, "type": req.type})
    return {"success": success}


@router.post("/v1/did/sessions/{session_id}/ice")
async def did_ice(session_id: str, req: DIDICECandidateRequest) -> dict:
    """Submit ICE candidate from browser to D-ID."""
    from tth.adapters.avatar.did_streaming import DIDStreamingAvatar

    orch = get_orchestrator()
    if not orch or not isinstance(orch.avatar, DIDStreamingAvatar):
        return {"success": False, "error": "D-ID streaming not configured"}

    success = await orch.avatar.submit_ice_candidate(session_id, req.model_dump(exclude_none=True))
    return {"success": success}


@router.post("/v1/did/sessions/{session_id}/chat")
async def did_chat(session_id: str, req: DIDTextRequest) -> dict:
    """Send text to D-ID agent for speaking."""
    from tth.adapters.avatar.did_streaming import DIDStreamingAvatar

    orch = get_orchestrator()
    if not orch or not isinstance(orch.avatar, DIDStreamingAvatar):
        return {"success": False, "error": "D-ID streaming not configured"}

    success = await orch.avatar.send_text(session_id, req.text)
    if not success:
        return {"success": False, "error": "Failed to send message to D-ID"}
    return {"success": True}


@router.delete("/v1/did/sessions/{session_id}")
async def did_disconnect(session_id: str) -> dict:
    """Close a D-ID streaming connection."""
    from tth.adapters.avatar.did_streaming import DIDStreamingAvatar

    orch = get_orchestrator()
    if not orch or not isinstance(orch.avatar, DIDStreamingAvatar):
        return {"success": False, "error": "D-ID streaming not configured"}

    await orch.avatar.close_connection(session_id)
    return {"success": True}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_inbound(raw: str):
    try:
        data = json.loads(raw)
        t = data.get("type")
        if t == "user_text":
            return UserTextEvent(**data)
        if t == "interrupt":
            return InterruptEvent(**data)
        if t == "control_update":
            return ControlUpdateEvent(**data)
    except Exception:
        pass
    return None
