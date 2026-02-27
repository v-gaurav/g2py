"""Structured logging setup using structlog."""

from __future__ import annotations

import logging
import os
import sys

import structlog


def setup_logging() -> structlog.stdlib.BoundLogger:
    """Configure structlog with console output."""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Set root logger level
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO), stream=sys.stderr, format="%(message)s")

    return structlog.get_logger()


logger: structlog.stdlib.BoundLogger = setup_logging()


def install_exception_hooks() -> None:
    """Route uncaught exceptions through structlog."""

    def handle_exception(exc_type, exc_value, exc_traceback):  # type: ignore[no-untyped-def]
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception


install_exception_hooks()
