---
name: new-adapter
description: Scaffold a new TTH adapter with registry decorator, base class, async generator, tests, and config entry
user-invocable: true
disable-model-invocation: true
---

# New Adapter Scaffold

## 1. Gather Information

Ask the user:

1. **Adapter category**: `llm`, `tts`, or `avatar`?
2. **Provider name**: Registry name (e.g., `elevenlabs_streaming`, `simli_webrtc`)
3. **Module filename**: Python filename without `.py` (e.g., `elevenlabs_streaming`)

## 2. Create the Adapter File

Create `src/tth/adapters/{category}/{filename}.py` with this template:

```python
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from tth.adapters.base import AdapterBase
from tth.core.registry import register
from tth.core.types import (
    AudioChunk,
    HealthStatus,
    TurnControl,
    VideoFrame,
)

logger = logging.getLogger(__name__)


@register("{provider_name}")
class {ClassName}(AdapterBase):
    """TODO: One-line description of what this adapter does."""

    async def load(self) -> None:
        # Initialize client connections, load credentials from self.config
        pass

    async def infer_stream(
        self,
        input: str | bytes | AudioChunk,
        control: TurnControl,
        context: dict[str, Any],
    ) -> AsyncIterator[{yield_type}]:
        # Yield type depends on category:
        #   LLM   -> str
        #   TTS   -> AudioChunk
        #   Avatar -> VideoFrame
        try:
            # TODO: implement streaming logic
            yield ...
        except asyncio.CancelledError:
            # Clean up resources on cancellation
            logger.info("{provider_name} inference cancelled")
            raise

    async def interrupt(self) -> None:
        # Clear buffers, notify remote service if applicable
        pass

    async def health(self) -> HealthStatus:
        # Return HealthStatus(ok=True/False, detail="...")
        return HealthStatus(ok=True, detail="{provider_name} healthy")
```

**Yield type by category**:
- `llm` → `str`
- `tts` → `AudioChunk`
- `avatar` → `VideoFrame`

## 3. Create the Test File

Create `tests/test_{filename}.py`:

```python
from __future__ import annotations

import pytest
from tth.core.types import TurnControl


@pytest.fixture
def adapter():
    from tth.adapters.{category}.{filename} import {ClassName}
    return {ClassName}(config={{}})


@pytest.mark.asyncio
async def test_health(adapter):
    status = await adapter.health()
    assert status.ok


@pytest.mark.asyncio
async def test_infer_stream_yields(adapter):
    control = TurnControl()
    chunks = []
    async for chunk in adapter.infer_stream("test input", control, {{}}):
        chunks.append(chunk)
    assert len(chunks) > 0
```

## 4. Add Config Entry

Add an entry to `config/base.yaml` (or a profile YAML) under the appropriate section:

```yaml
{category}:
  provider: {provider_name}
  {provider_name}:
    # provider-specific config keys
    api_key: ${{{UPPER_PROVIDER}_API_KEY}}
```

## 5. Register the Import

Ensure the module is imported in `src/tth/adapters/{category}/__init__.py` so the `@register` decorator fires.

## 6. Verify

Run `make test` to confirm the new adapter loads and tests pass.
