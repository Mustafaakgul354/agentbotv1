"""Lightweight LLM client abstraction with optional OpenAI provider.

This module is optional. If the OpenAI Python SDK is not installed, importing
``OpenAIClient`` will raise a helpful error message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class LLMError(RuntimeError):
    pass


class LLMClient:
    async def generate(self, *, system: str, user: str, temperature: float = 0.2) -> str:  # pragma: no cover
        raise NotImplementedError


@dataclass
class OpenAIClient(LLMClient):
    api_key: str
    model: str = "gpt-4o-mini"

    def __post_init__(self) -> None:
        try:  # Lazy import to keep dependency optional
            from openai import OpenAI  # type: ignore

            self._OpenAI = OpenAI
        except Exception as exc:  # pragma: no cover - import-time failure only
            raise LLMError(
                "OpenAI SDK not installed. Add 'llm' extra or install 'openai' package."
            ) from exc

        # Create client
        self._client = self._OpenAI(api_key=self.api_key)

    async def generate(self, *, system: str, user: str, temperature: float = 0.2) -> str:
        # Use chat completions API for broad compatibility
        try:
            resp = await self._to_thread(
                self._client.chat.completions.create,
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=256,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:
            raise LLMError(str(exc))

    # Minimal thread offload to avoid blocking event loop on sync client
    async def _to_thread(self, func, /, *args, **kwargs):
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


__all__ = ["LLMClient", "OpenAIClient", "LLMError"]


