# src/tth/api/main.py
from __future__ import annotations
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from tth.core.config import settings
from tth.core.logging import configure_logging, get_logger
from tth.control.mapper import build_llm_system_prompt, map_emotion_to_realtime_voice
from tth.core.types import TurnControl
from tth.control.personas import get_persona_defaults, get_persona_name
import tth.core.registry as registry

# Import adapters to trigger @register decorators
import tth.adapters.realtime.openai_realtime  # noqa: F401
import tth.adapters.avatar.stub  # noqa: F401

from tth.pipeline.session import SessionManager
from tth.pipeline.orchestrator import Orchestrator
from tth.api.routes import router, set_session_manager, set_orchestrator

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.app.log_level)
    log.info("tth starting", profile=settings.profile)

    # Instantiate adapters from config
    realtime_cfg = settings.components.get("realtime", {})
    avatar_cfg = settings.components.get("avatar", {})

    realtime_adapter = registry.create(
        realtime_cfg.get("primary", "openai_realtime"), realtime_cfg
    )
    avatar_adapter = registry.create(avatar_cfg.get("primary", "stub_avatar"), avatar_cfg)

    # Load adapters
    await realtime_adapter.load()
    await avatar_adapter.load()

    log.info(
        "adapters loaded",
        realtime=realtime_cfg.get("primary", "openai_realtime"),
        avatar=avatar_cfg.get("primary", "stub_avatar"),
    )

    # Get persona defaults for initial connection
    persona_id = "default"
    persona_defaults = get_persona_defaults(persona_id)
    persona_name = get_persona_name(persona_id)

    # Build system instructions and voice for Realtime API
    system_instructions = build_llm_system_prompt(
        TurnControl(emotion=persona_defaults.emotion, character=persona_defaults.character),
        persona_name=persona_name,
    )
    voice = map_emotion_to_realtime_voice(persona_defaults.emotion)

    # Connect to Realtime API once at startup
    await realtime_adapter.connect(system_instructions, voice)
    log.info("Realtime API connected", voice=voice)

    # Wire up orchestrator + session manager
    orch = Orchestrator(realtime=realtime_adapter, avatar=avatar_adapter)
    sm = SessionManager()

    set_orchestrator(orch)
    set_session_manager(sm)

    log.info("tth ready", host=settings.app.host, port=settings.app.port)
    yield

    # Cleanup
    log.info("tth shutting down")
    await realtime_adapter.close()


app = FastAPI(
    title="TTH — Text-to-Human",
    version="0.1.0",
    description="Real-time text-to-human video with emotion and character controllability",
    lifespan=lifespan,
)

app.include_router(router)

# Serve web UI at root (must come after router so /v1/* routes take precedence)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
