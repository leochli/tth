---
name: run-phases
description: Run the 4-phase TTH test suite in sequence, stopping on failure
user-invocable: true
disable-model-invocation: true
---

# Run Phased Tests

Run the TTH phased test suite. Each phase gates the next—stop on first failure.

## Phases

| Phase | Script | What it tests |
|-------|--------|---------------|
| 1 | `scripts/phase_01_unit.py` | Unit tests — types, config, registry |
| 2 | `scripts/phase_02_offline_smoke.py` | Offline pipeline smoke test |
| 3 | `scripts/phase_03_offline_multiturn.py` | Multi-turn session continuity |
| 4 | `scripts/phase_04_live_openai.py` | Live OpenAI API (requires key) |

## Execution

Run phases sequentially using Bash. Stop immediately if any phase fails.

### Step 1: Run phases 1–3 (offline)

```bash
.venv/bin/python scripts/run_phased_tests.py
```

If this fails, report which phase failed and show the output. Do NOT continue to phase 4.

### Step 2: Ask about phase 4

Ask the user: "Phases 1–3 passed. Run phase 4 (live OpenAI API, requires OPENAI_API_KEY)?"

If yes:

```bash
.venv/bin/python scripts/run_phased_tests.py --live
```

If no, report phases 1–3 passed and stop.

## Reporting

After completion, summarize results:

```
Phase 1 (Unit):            PASS / FAIL
Phase 2 (Offline Smoke):   PASS / FAIL
Phase 3 (Offline Multi):   PASS / FAIL
Phase 4 (Live OpenAI):     PASS / FAIL / SKIPPED
```

If any phase failed, include the relevant error output and suggest next steps.
