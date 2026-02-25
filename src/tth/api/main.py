# src/tth/api/main.py
from __future__ import annotations
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from tth.core.config import settings
from tth.core.logging import configure_logging, get_logger
import tth.core.registry as registry

# Import adapters to trigger @register decorators
import tth.adapters.llm.openai_api  # noqa: F401
import tth.adapters.llm.mock_llm  # noqa: F401
import tth.adapters.tts.openai_tts  # noqa: F401
import tth.adapters.tts.mock_tts  # noqa: F401
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
    llm_cfg = settings.components.get("llm", {})
    tts_cfg = settings.components.get("tts", {})
    avatar_cfg = settings.components.get("avatar", {})

    llm_adapter = registry.create(llm_cfg.get("primary", "openai_chat"), llm_cfg)
    tts_adapter = registry.create(tts_cfg.get("primary", "openai_tts"), tts_cfg)
    avatar_adapter = registry.create(avatar_cfg.get("primary", "stub_avatar"), avatar_cfg)

    # Load adapters
    await llm_adapter.load()
    await tts_adapter.load()
    await avatar_adapter.load()

    log.info(
        "adapters loaded",
        llm=llm_cfg.get("primary"),
        tts=tts_cfg.get("primary"),
        avatar=avatar_cfg.get("primary"),
    )

    # Wire up orchestrator + session manager
    orch = Orchestrator(llm=llm_adapter, tts=tts_adapter, avatar=avatar_adapter)
    sm = SessionManager()

    set_orchestrator(orch)
    set_session_manager(sm)

    log.info("tth ready", host=settings.app.host, port=settings.app.port)
    yield

    log.info("tth shutting down")


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
