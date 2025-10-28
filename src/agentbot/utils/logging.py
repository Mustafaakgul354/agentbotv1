"""Logging helpers with consistent formatting."""

from __future__ import annotations

import logging
import sys
from typing import Optional

from rich.logging import RichHandler


def get_logger(name: str, level: int = logging.INFO, *, rich: bool = True) -> logging.Logger:
    """Configure and return a logger."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)

    if rich:
        handler: logging.Handler = RichHandler(
            level=level,
            markup=True,
            rich_tracebacks=True,
            tracebacks_show_locals=False,
            show_time=True,
            show_path=False,
        )
    else:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    logger.propagate = False
    return logger

