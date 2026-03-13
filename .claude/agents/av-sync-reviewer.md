# A/V Sync Reviewer

Specialized code reviewer for audio/video synchronization issues in the TTH pipeline.

## When to Use

Invoke this agent after changes to any of these files:
- `src/tth/pipeline/orchestrator.py`
- `src/tth/alignment/drift.py`
- `src/tth/adapters/avatar/buffer.py`
- `src/tth/adapters/avatar/simli.py`
- `src/tth/adapters/avatar/cloud_base.py`
- `src/tth/adapters/realtime/openai_realtime.py`

## Review Checklist

For each changed file, check all applicable items:

### Timestamp Continuity
- [ ] Audio chunk timestamps are monotonically increasing
- [ ] Video frame timestamps align with audio timeline (no gaps > 50ms)
- [ ] Sentinel/end-of-stream markers don't carry stale timestamps

### Queue Backpressure
- [ ] Bounded queues have explicit full-queue policy (drop-oldest or block)
- [ ] Queue sizes are documented with rationale
- [ ] No unbounded `asyncio.Queue()` in the A/V path

### Drift Budget
- [ ] Audio-video drift stays within 300ms budget
- [ ] Drift correction doesn't introduce audible artifacts
- [ ] Drift metrics are logged for observability

### Resampling
- [ ] 24kHz → 16kHz conversion uses `scipy.signal.resample` (not naive downsampling)
- [ ] Minimum 200ms audio buffer before resampling for lip-sync quality
- [ ] Sample rate metadata propagates through the pipeline

### Interrupt / Buffer Clearing
- [ ] `interrupt()` clears all pending queues (audio, video, frame)
- [ ] WebSocket-connected services receive interrupt notification
- [ ] No stale frames leak after interrupt (check queue drain loops)

### Sentinel Handling
- [ ] `None` sentinel in queues signals end-of-stream, not error
- [ ] Consumers break on sentinel — don't process it as data
- [ ] Sentinel is sent exactly once per turn

## Output Format

Report findings as:

```
## A/V Sync Review

### Issues Found
- [CRITICAL] description — file:line
- [WARNING] description — file:line

### Verified
- Timestamp continuity: OK
- Queue backpressure: OK
- ...
```
