"""Structured logging configuration (JSON by default, pretty in development)."""
import logging
import sys


def configure_logging(json_logs: bool = True, level: str = "INFO") -> None:
    """Route both structlog and the stdlib ``logging`` tree through one handler.

    Every existing ``logging.getLogger(...)`` call in the codebase therefore emits
    the same structured format as structlog loggers.
    """
    import structlog

    numeric_level = getattr(logging, str(level).upper(), logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer()
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(numeric_level)

    # Quiet noisy libraries unless the root level is explicitly debug.
    if numeric_level > logging.DEBUG:
        for noisy in ("uvicorn.access", "httpcore", "httpx", "urllib3", "litellm"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
