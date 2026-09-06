"""Process logging for the served MCP server. A host never calls this."""

from __future__ import annotations

import logging
import sys
from typing import Literal

import structlog
from pydantic_settings import BaseSettings, SettingsConfigDict
from structlog.types import Processor

_QUIET_LOGGERS = ("httpx", "httpcore")
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class LoggingSettings(BaseSettings):
    """How this process renders its log."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_ignore_empty=True,
        extra="ignore",
    )

    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"


def setup_logging() -> None:
    """Render this process's log through structlog, once, at startup."""
    settings = LoggingSettings()
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)

    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    # uvicorn ships with propagate off, so its request lines need it flipped.
    for name in _UVICORN_LOGGERS:
        served = logging.getLogger(name)
        served.setLevel(logging.INFO)
        served.propagate = True
        served.handlers.clear()
