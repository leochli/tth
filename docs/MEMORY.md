# TTH Memory (Operational Notes)

## Stable Defaults
1. Config profile default: `api_only_mac`.
2. Deterministic local validation profile: `offline_mock`.
3. Session transport: WebSocket JSON events.
4. Media payloads are base64 in event JSON.

## Key Commands
1. Run full offline phases:
   - `.venv/bin/python scripts/run_phased_tests.py`
2. Run with live OpenAI phase:
   - `.venv/bin/python scripts/run_phased_tests.py --live`
3. Run only live phase:
   - `.venv/bin/python scripts/phase_04_live_openai.py`

## Important Implementation Decisions
1. One active turn task per session:
   - New `user_text` cancels previous task.
2. `control_update` is stored as `pending_control` and merged into next turn.
3. LLM->TTS pipeline is sentence-buffered for earlier TTFA.
4. Stub avatar intentionally emits `raw_rgb` payloads for no-external-video testing.

## Known Environment Constraints
1. In this sandbox, binding listen ports may be blocked.
2. In this sandbox, external DNS/network to provider APIs may be blocked.
3. In this sandbox, `uv run` may fail due `nice(5)` permission behavior.
4. Use `.venv/bin/python ...` directly when needed.

## Validation Baseline
1. `phase_01_unit.py`: must pass.
2. `phase_02_offline_smoke.py`: must pass with coherent text/audio/video events.
3. `phase_03_offline_multiturn.py`: must pass and show control update influence.
4. `phase_04_live_openai.py`: pass when network+key available, skip otherwise.

## Security Notes
1. Do not hardcode API keys in source.
2. Keep secrets only in `.env` (local) or environment variables in deployment.
3. If a key is ever pasted in chat/plaintext, rotate/revoke it.
