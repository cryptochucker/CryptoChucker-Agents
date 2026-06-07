from __future__ import annotations

import sys

from loguru import logger


def setup_logging(log_dir: str = "logs", json_sink: bool = False) -> "logger":
    """Configure loguru with a colored console sink and a rotating file sink.

    Args:
        log_dir: Directory for log files (created if missing).
        json_sink: When True, also write JSON-structured logs to a second file.

    Returns:
        The configured loguru logger instance.
    """
    import os

    os.makedirs(log_dir, exist_ok=True)

    # Remove default handler
    logger.remove()

    # Colored console sink
    logger.add(
        sys.stdout,
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
        level="DEBUG",
    )

    # Rotating file sink
    logger.add(
        f"{log_dir}/app_{{time}}.log",
        rotation="10 MB",
        retention="10 days",
        encoding="utf-8",
        level="DEBUG",
    )

    # Optional JSON sink
    if json_sink:
        logger.add(
            f"{log_dir}/app_json_{{time}}.log",
            rotation="10 MB",
            retention="10 days",
            encoding="utf-8",
            serialize=True,
            level="DEBUG",
        )

    return logger
