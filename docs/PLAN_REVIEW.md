# Plan Review: Real-Time Avatar Implementation

**Review Date:** 2026-03-10
**Plan File:** `~/.claude/plans/cheerful-knitting-chipmunk.md`

## Executive Summary

The plan is **significantly out of date**. Most implementation work has already been completed. The only remaining blocking issue is a single-line fix in the OpenAI Realtime adapter.

---

## Critical Finding: Blocking Issue

### OpenAI Realtime API Session Type

**Location:** `src/tth/adapters/realtime/openai_realtime.py:68`

**Problem:** The `session.type` is set to `"text"` but should be `"realtime"` for speech-to-speech.

**Current code (broken):**
```python
session_update = {
    "type": "session.update",
    "session": {
        "type": "text",  # WRONG
        ...
    },
}
```

**Fix:**
```python
session_update = {
    "type": "session.update",
    "session": {
        "type": "realtime",  # CORRECT
        ...
    },
}
```

**Reference:** OpenAI Realtime API docs show `session.type: "realtime"` for speech-to-speech sessions.

---

## Phase Status Summary

| Phase | Plan Status | Actual Status | Notes |
|-------|-------------|---------------|-------|
| 0: LivePortrait Spike | Pending | **Pending** | Still needs to be done |
| 1: Infrastructure | Planned | **COMPLETE** | All files exist |
| 1.5: Audio Pipeline | Planned | **COMPLETE** | audio_utils.py, buffer.py exist |
| 1.6: Orchestrator Integration | Planned | **COMPLETE** | Already implemented |
| 2: Cloud Adapter | Planned | **COMPLETE** | All files exist |
| 3: Modal Deployment | Planned | **COMPLETE** | app.py exists with full impl |
| 4: Emotion Control | Planned | **COMPLETE** | map_emotion_to_avatar() exists |
| 5: Client Rendering | Planned | **COMPLETE** | All client files exist |

---

## Detailed Verification

### Phase 1.6 "Prerequisites" - ALREADY DONE

| Claim in Plan | File | Line | Reality |
|---------------|------|------|---------|
| "Add session_id to orchestrator context" | `orchestrator.py` | 96 | Already has `"session_id": session.id` |
| "Add interrupt() to AdapterBase" | `base.py` | 41-47 | Already implemented |
| "Call interrupt() in routes.py" | `routes.py` | 128 | Already calls `orch.avatar.interrupt()` |

### Phase 1 & 2 Files - ALL EXIST

| File | Purpose | Status |
|------|---------|--------|
| `adapters/avatar/audio_utils.py` | AudioResampler (24kHz → 16kHz) | Complete |
| `adapters/avatar/buffer.py` | AudioChunkBuffer with configurable size | Complete |
| `adapters/avatar/cloud_base.py` | WebSocket management, reconnection, health | Complete |
| `adapters/avatar/liveportrait_cloud.py` | LivePortrait cloud adapter | Complete |
| `adapters/avatar/mock_cloud.py` | Mock adapter for testing | Complete |
| `adapters/avatar/metrics.py` | AvatarMetrics tracking | Complete |

### Phase 3: Modal Deployment - EXISTS

**File:** `deployment/modal/avatar_service/app.py`

Features implemented:
- WebSocket endpoint at `/ws`
- Health check at `/health`
- Ready probe at `/health/ready`
- Metrics at `/metrics`
- Session management
- Interrupt handling
- Stub mode for testing without LivePortrait

### Phase 4: Emotion Control - EXISTS

**File:** `adapters/avatar/liveportrait_cloud.py:18-53`

`map_emotion_to_avatar()` function maps:
- Emotion labels to expression weights
- Intensity scaling
- Head motion scale from character control

### Phase 5: Client Rendering - ALL EXIST

| File | Purpose |
|------|---------|
| `client/avatar_renderer.js` | Canvas rendering with A/V sync |
| `client/av_sync.js` | Web Audio API synchronization |
| `client/demo.html` | Demo page UI |
| `client/demo.js` | Demo client logic |

---

## Remaining Work

### 1. Immediate Fix (5 minutes)

- [ ] Change `session.type` from `"text"` to `"realtime"` in `openai_realtime.py:68`
- [ ] Test with `make dev` and verify connection works

### 2. Phase 0: LivePortrait Spike (1-2 days)

- [ ] Deploy LivePortrait on Modal test instance
- [ ] Verify streaming/chunking capabilities
- [ ] Measure actual inference latency
- [ ] Document real API signatures
- [ ] **Go/No-Go decision point**

### 3. Integration Testing

- [ ] Test with actual OpenAI Realtime API after fix
- [ ] Deploy Modal service with real LivePortrait
- [ ] Verify end-to-end latency meets <300ms target
- [ ] Test interrupt handling
- [ ] Test reconnection scenarios

---

## Recommendations

1. **Update the original plan** to reflect current implementation state
2. **Fix the blocking issue first** before any other work
3. **Run Phase 0 spike** to validate LivePortrait assumptions
4. **Add integration tests** for the full pipeline

---

## File Structure (Current State)

```
src/tth/adapters/avatar/
├── __init__.py              # Exports all adapters
├── stub.py                  # Stub adapter (existing)
├── mock_cloud.py            # Mock cloud adapter
├── cloud_base.py            # Base class for cloud adapters
├── liveportrait_cloud.py    # LivePortrait implementation
├── buffer.py                # Audio chunk buffering
├── audio_utils.py           # Resampling utilities
└── metrics.py               # Performance tracking

deployment/modal/avatar_service/
├── app.py                   # Modal deployment
└── test_liveportrait.py     # Spike test script

client/
├── avatar_renderer.js       # Canvas rendering
├── av_sync.js               # Audio sync
├── demo.html                # Demo page
└── demo.js                  # Demo logic
```
