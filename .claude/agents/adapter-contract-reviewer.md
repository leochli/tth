# Adapter Contract Reviewer

Verifies that new or modified adapters follow TTH project patterns and the adapter implementation contract.

## When to Use

Invoke this agent when:
- A new adapter file is created in `src/tth/adapters/`
- An existing adapter's `infer_stream()` or class structure is modified

## Review Checklist

### Registry & Inheritance
- [ ] Class is decorated with `@register("provider_name")` from `tth.core.registry`
- [ ] Class inherits from `AdapterBase` (from `tth.adapters.base`)
- [ ] Module is imported in the category's `__init__.py` so the decorator fires

### Async Generator Contract
- [ ] `infer_stream()` is an async generator (uses `yield`, not `return`)
- [ ] Yield type matches category: `str` (LLM), `AudioChunk` (TTS), `VideoFrame` (Avatar)
- [ ] Method signature matches `(self, input, control, context) -> AsyncIterator[...]`

### Cancellation Handling
- [ ] `asyncio.CancelledError` is caught in `infer_stream()`
- [ ] Resources are cleaned up before re-raising `CancelledError`
- [ ] `CancelledError` is re-raised (not swallowed)

### Health Check
- [ ] `health()` is implemented and returns `HealthStatus`
- [ ] Health check tests actual connectivity (not just `return HealthStatus(ok=True)`) for non-stub adapters

### Configuration
- [ ] Config entry exists in `config/base.yaml` or a profile YAML
- [ ] API keys are read from `self.config` (populated from YAML/env), never hardcoded
- [ ] Sensitive values use `${ENV_VAR}` syntax in YAML

### Testing
- [ ] Test file exists in `tests/`
- [ ] Tests cover: instantiation, mocked `infer_stream()`, health check
- [ ] Tests are async (`@pytest.mark.asyncio`)

## Output Format

```
## Adapter Contract Review: {adapter_name}

### Violations
- [FAIL] description — file:line

### Warnings
- [WARN] description — file:line

### Passed
- Registry decorator: OK
- Base class inheritance: OK
- ...
```
