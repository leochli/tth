# src/tth/alignment/drift.py
from __future__ import annotations
from collections import deque


class DriftController:
    """
    Tracks audio vs video timestamp drift and emits correction hints.

    audio_ts: expected wall-clock time of audio chunk in ms
    video_ts: actual timestamp on the emitted video frame in ms

    drift_ms = video_ts - audio_ts
    Positive drift: video is ahead of audio (slow down video or speed up audio)
    Negative drift: video is behind audio (speed up video or skip frames)
    """

    def __init__(self, window: int = 10) -> None:
        self._window = window
        self._history: deque[float] = deque(maxlen=window)

    def update(self, audio_ts_ms: float, video_ts_ms: float) -> float:
        """Record a new timestamp pair and return current drift in ms."""
        drift = video_ts_ms - audio_ts_ms
        self._history.append(drift)
        return drift

    @property
    def mean_drift_ms(self) -> float:
        if not self._history:
            return 0.0
        return sum(self._history) / len(self._history)

    @property
    def max_drift_ms(self) -> float:
        if not self._history:
            return 0.0
        return max(abs(d) for d in self._history)

    def reset(self) -> None:
        self._history.clear()

    def is_within_budget(self, budget_ms: float = 80.0) -> bool:
        """Returns True if mean drift is within the acceptable budget."""
        return abs(self.mean_drift_ms) <= budget_ms
