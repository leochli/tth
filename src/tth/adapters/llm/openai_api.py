# src/tth/adapters/llm/openai_api.py
from __future__ import annotations
import json
import time
from typing import Any, AsyncIterator
import httpx
from tth.adapters.base import AdapterBase
from tth.control.mapper import build_llm_system_prompt
from tth.core.config import settings
from tth.core.registry import register
from tth.core.types import HealthStatus, TurnControl


@register("openai_chat")
class OpenAIChatAdapter(AdapterBase):
    """Streams tokens from OpenAI Chat Completions (SSE)."""

    _BASE = "https://api.openai.com/v1"

    async def infer_stream(
        self, input: str, control: TurnControl, context: dict[str, Any]
    ) -> AsyncIterator[str]:
        system_prompt = build_llm_system_prompt(
            control,
            persona_name=context.get("persona_name", "Assistant"),
        )
        api_key = settings.openai_api_key
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {
            "model": self.config.get("model", "gpt-4o-mini"),
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                *context.get("history", []),
                {"role": "user", "content": input},
            ],
        }
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream(
                "POST",
                f"{self._BASE}/chat/completions",
                headers=headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for raw_line in resp.aiter_lines():
                    line = raw_line.strip()
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        delta = json.loads(line[6:])
                        token = delta["choices"][0]["delta"].get("content") or ""
                        if token:
                            yield token

    async def health(self) -> HealthStatus:
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(
                    f"{self._BASE}/models",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                )
            return HealthStatus(
                healthy=r.status_code == 200,
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        except Exception as exc:
            return HealthStatus(
                healthy=False,
                latency_ms=(time.monotonic() - t0) * 1000,
                detail=str(exc),
            )
