# src/tth/core/logging.py
from __future__ import annotations
import logging
import structlog


def configure_logging(log_level: str = "info") -> None:
    """Configure structlog with timestamps, levels, and trace IDs."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        level=level,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)


def bind_trace(session_id: str, turn_id: str | None = None) -> None:
    """Bind trace context to all subsequent log calls in this async context."""
    ctx: dict = {"session_id": session_id}
    if turn_id:
        ctx["turn_id"] = turn_id
    structlog.contextvars.bind_contextvars(**ctx)


def clear_trace() -> None:
    structlog.contextvars.clear_contextvars()
