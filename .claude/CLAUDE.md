# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TTH (Text-to-Human) is a real-time text-to-human video synthesis system with emotion and character controllability. It uses an API-first architecture with pluggable adapters that let you swap between external APIs and self-hosted models via configuration—no code changes required.

## Development Commands

```bash
make install    # Install dependencies (requires uv package manager)
make dev        # Start development server at http://localhost:8000
make test       # Run unit tests (pytest)
make lint       # Run linter (ruff check + mypy)
make fmt        # Format code (ruff format)
make demo       # Run CLI demo client
make phase      # Run offline integration tests
make phase-live # Run tests with live API calls
```

## Architecture

```
src/tth/
├── core/          # Types (types.py), config (config.py), registry (registry.py)
├── adapters/      # Provider implementations: llm/, tts/, avatar/
├── control/       # Emotion/character mapping (mapper.py, personas.py)
├── pipeline/      # Orchestrator + session management
├── alignment/     # A/V synchronization (drift.py)
└── api/           # FastAPI app (main.py), routes (routes.py), schemas
```

**Data flow**: UserText → LLM (streaming tokens) → sentence buffer → TTS (audio chunks) → Avatar (video frames) → WebSocket client

### Key Patterns

**Adapter Registry**: Adapters are registered via `@register("name")` decorator and instantiated via `registry.create()`. This enables config-only provider switching. All adapters inherit from `AdapterBase` and implement `infer_stream()`, `health()`, and `capabilities()`.

**Control System**: `TurnControl` contains `EmotionControl` (label, intensity, valence, arousal) and `CharacterControl` (speech_rate, pitch_shift, expressivity, motion_gain). Controls are resolved via `control/mapper.py` which maps generic controls to provider-specific parameters (e.g., OpenAI voice selection, speech rate modulation).

**Orchestrator Pipeline** (`pipeline/orchestrator.py`): Uses bounded async queues to pipeline LLM → TTS → Avatar. LLM produces sentences; TTS starts as soon as the first sentence is ready. This reduces latency vs sequential execution.

**WebSocket Protocol**: See `core/types.py` for event schemas. Inbound: `user_text`, `interrupt`, `control_update`. Outbound: `text_delta`, `audio_chunk`, `video_frame`, `turn_complete`, `error`. Audio/video data is base64-encoded in JSON transport.

### Configuration

- `config/base.yaml` — Default configuration with OpenAI LLM/TTS and stub avatar
- `config/profiles/*.yaml` — Profile-specific overrides (merged via deep_merge)
- Environment variables: `OPENAI_API_KEY` (required), `ELEVENLABS_API_KEY`, `ANTHROPIC_API_KEY`, etc.
- Profile selection: Set `TTH_PROFILE=profile_name` or edit `profile` in settings

### Adding New Adapters

1. Create adapter class inheriting from `AdapterBase` in appropriate `adapters/{llm,tts,avatar}/` subdirectory
2. Decorate with `@register("provider_name")`
3. Implement `infer_stream()` as async generator yielding appropriate types (str for LLM, AudioChunk for TTS, VideoFrame for avatar)
4. Add config entry in `config/base.yaml` or profile YAML

## Workflow Orchestration

1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately – don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

3. Self-Improvement Loop
- After ANY correction from the user: update `docs/MEMORY.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes – don't over-engineer
- Challenge your own work before presenting it

6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests – then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

Task Management

1. **Plan First**: Write plan to `docs/IMPLEMENTATION_PLAN.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `docs/IMPLEMENTATION_PLAN.md`
6. **Capture Lessons**: Update `docs/MEMORY.md` after corrections

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.
