"""Environment helper utilities."""

from __future__ import annotations

import os
import shlex
from typing import Sequence


_FALSE_VALUES = {"0", "false", "no", "off"}


def get_bool_env(name: str, *, default: bool = False) -> bool:
    """Return True/False for an environment flag."""
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if not value:
        return default
    return value not in _FALSE_VALUES


def get_list_env(name: str, *, default: Sequence[str] | None = None) -> list[str]:
    """
    Read a whitespace-delimited list from the environment.

    Values can be quoted, e.g. `--foo "--bar=baz qux"`.
    """
    raw = os.getenv(name)
    if raw is None:
        return list(default or [])
    value = raw.strip()
    if not value:
        return list(default or [])
    try:
        parsed = shlex.split(value)
    except ValueError:
        parsed = value.split()
    return [item for item in parsed if item]
