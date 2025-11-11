"""Human-like mouse interactions for Playwright pages.

Implements slow, slightly curved mouse movement paths and click helpers to
better mimic imperfect human motions (e.g., gentle curvature, variable speed).
"""

from __future__ import annotations

import asyncio
import math
import random
from copy import deepcopy
from typing import Iterable, Mapping, Tuple, Union
from weakref import WeakKeyDictionary

from playwright.async_api import Locator, Page

MousePos = Tuple[float, float]
LocatorLike = Union[Locator, str]

# Default parameter ranges emulate gentle yet imperfect cursor motion.
DEFAULT_MOUSE_CONFIG = {
    "enabled": True,
    "move_duration_range": (0.45, 0.9),
    "hover_delay_range": (0.08, 0.2),
    "press_duration_range": (0.05, 0.12),
    "curvature_range": (0.12, 0.35),
    "noise": 2.2,
    "steps_range": (18, 32),
}

# Track last known mouse position per Page without preventing garbage collection.
_mouse_positions: "WeakKeyDictionary[Page, MousePos]" = WeakKeyDictionary()
_GLOBAL_MOUSE_CONFIG = deepcopy(DEFAULT_MOUSE_CONFIG)


def set_humanlike_mouse_config(config: Mapping[str, object] | None) -> None:
    """Override module-level defaults for all future clicks (None resets)."""
    global _GLOBAL_MOUSE_CONFIG
    _GLOBAL_MOUSE_CONFIG = deepcopy(DEFAULT_MOUSE_CONFIG)
    if config:
        _GLOBAL_MOUSE_CONFIG.update(config)


def get_humanlike_mouse_config() -> dict[str, object]:
    """Return a copy of the currently active global mouse config."""
    return deepcopy(_GLOBAL_MOUSE_CONFIG)


def _get_viewport_center(page: Page) -> MousePos:
    viewport = page.viewport_size or {"width": 1920, "height": 1080}
    return (viewport["width"] / 2, viewport["height"] / 2)


def _get_mouse_position(page: Page) -> MousePos:
    return _mouse_positions.get(page) or _get_viewport_center(page)


def _set_mouse_position(page: Page, pos: MousePos) -> None:
    _mouse_positions[page] = pos


def _quadratic_bezier_points(
    start: MousePos,
    end: MousePos,
    curvature: float,
    steps: int,
    noise: float,
) -> Iterable[MousePos]:
    """Generate points along a quadratic Bézier curve with mild jitter."""
    steps = max(2, steps)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    distance = math.hypot(dx, dy) or 1.0
    norm_dx = dx / distance
    norm_dy = dy / distance
    # Perpendicular vector for curvature
    perp_dx = -norm_dy
    perp_dy = norm_dx
    mid_x = (start[0] + end[0]) / 2
    mid_y = (start[1] + end[1]) / 2
    control = (
        mid_x + perp_dx * distance * curvature * random.uniform(0.8, 1.2),
        mid_y + perp_dy * distance * curvature * random.uniform(0.8, 1.2),
    )

    for step in range(1, steps + 1):
        t = step / steps
        inv = 1 - t
        px = inv * inv * start[0] + 2 * inv * t * control[0] + t * t * end[0]
        py = inv * inv * start[1] + 2 * inv * t * control[1] + t * t * end[1]
        # Sine-based jitter dampened at start/end to stay within the element.
        jitter_scale = math.sin(math.pi * t)
        px += random.uniform(-noise, noise) * jitter_scale
        py += random.uniform(-noise, noise) * jitter_scale
        yield (px, py)


async def _move_mouse_humanlike(
    page: Page,
    start: MousePos,
    target: MousePos,
    *,
    duration: float,
    curvature: float,
    noise: float,
    steps: int,
) -> None:
    points = list(
        _quadratic_bezier_points(start, target, curvature=curvature, steps=steps, noise=noise)
    )
    steps = len(points)
    duration = max(duration, steps * 0.01)
    base_delay = duration / steps

    for px, py in points:
        await page.mouse.move(px, py, steps=1)
        await asyncio.sleep(max(0.0, base_delay + random.uniform(-0.005, 0.008)))

    _set_mouse_position(page, target)


async def _resolve_locator(page: Page, target: LocatorLike, timeout: float) -> Locator:
    locator: Locator = target if isinstance(target, Locator) else page.locator(target)
    handle = locator.first
    await handle.wait_for(state="visible", timeout=timeout)
    await handle.scroll_into_view_if_needed()
    return handle


async def _pick_target_point(locator: Locator) -> MousePos:
    box = await locator.bounding_box()
    if not box:
        raise RuntimeError("Element bounding box unavailable for human-like click.")
    x = box["x"] + random.uniform(box["width"] * 0.25, box["width"] * 0.75)
    y = box["y"] + random.uniform(box["height"] * 0.30, box["height"] * 0.70)
    return (x, y)


def _merge_mouse_config(config: Mapping[str, object] | None) -> dict[str, object]:
    merged = deepcopy(_GLOBAL_MOUSE_CONFIG)
    if config:
        merged.update(config)
    return merged


def _range(
    cfg: dict[str, object],
    key: str,
    *,
    fallback: Tuple[float, float] | Tuple[int, int],
) -> Tuple[float, float] | Tuple[int, int]:
    value = cfg.get(key)
    if isinstance(value, (list, tuple)) and len(value) == len(fallback):
        try:
            return (value[0], value[1])  # type: ignore[return-value]
        except Exception:
            pass
    return fallback


async def humanlike_click(
    page: Page,
    target: LocatorLike,
    *,
    config: Mapping[str, object] | None = None,
    timeout: float = 30000,
) -> None:
    """Move the mouse along a curved, imperfect path and issue a click."""
    cfg = _merge_mouse_config(config)
    locator = await _resolve_locator(page, target, timeout=timeout)
    if not cfg.get("enabled", True):
        await locator.click()
        return

    move_duration_range = _range(cfg, "move_duration_range", fallback=(0.45, 0.9))  # type: ignore[assignment]
    hover_delay_range = _range(cfg, "hover_delay_range", fallback=(0.08, 0.2))  # type: ignore[assignment]
    press_duration_range = _range(cfg, "press_duration_range", fallback=(0.05, 0.12))  # type: ignore[assignment]
    curvature_range = _range(cfg, "curvature_range", fallback=(0.12, 0.35))  # type: ignore[assignment]
    steps_range = _range(cfg, "steps_range", fallback=(18, 32))  # type: ignore[assignment]
    noise = float(cfg.get("noise", 2.2))

    target_point = await _pick_target_point(locator)
    start = _get_mouse_position(page)
    move_duration = random.uniform(*move_duration_range)  # type: ignore[arg-type]
    curvature = random.uniform(*curvature_range)  # type: ignore[arg-type]
    steps = random.randint(*steps_range)  # type: ignore[arg-type]
    await _move_mouse_humanlike(
        page,
        start,
        target_point,
        duration=move_duration,
        curvature=curvature,
        noise=noise,
        steps=steps,
    )
    await asyncio.sleep(random.uniform(*hover_delay_range))  # type: ignore[arg-type]
    await page.mouse.down()
    await asyncio.sleep(random.uniform(*press_duration_range))  # type: ignore[arg-type]
    await page.mouse.up()
