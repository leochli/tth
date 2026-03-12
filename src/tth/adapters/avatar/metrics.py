# src/tth/adapters/avatar/metrics.py
"""Performance metrics tracking for avatar adapters."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, List


@dataclass
class AvatarMetrics:
    """Track avatar performance metrics.

    Used for monitoring latency, frame rates, and quality metrics
    in cloud avatar adapters.

    Attributes:
        frames_generated: Total frames successfully generated
        frames_dropped: Frames dropped due to queue overflow
        total_latency_ms: Cumulative latency across all frames
        latency_samples: List of recent latency measurements (last 100)
        connection_errors: Number of connection/reconnection failures
        chunks_sent: Number of audio chunks sent to cloud
    """

    frames_generated: int = 0
    frames_dropped: int = 0
    total_latency_ms: float = 0.0
    latency_samples: List[float] = field(default_factory=list)
    connection_errors: int = 0
    chunks_sent: int = 0
    _start_time: float = field(default_factory=time.monotonic)

    def record_frame(self, latency_ms: float) -> None:
        """Record a successfully generated frame.

        Args:
            latency_ms: Time from audio sent to frame received
        """
        self.frames_generated += 1
        self.total_latency_ms += latency_ms
        self.latency_samples.append(latency_ms)

        # Keep last 100 samples for rolling average
        if len(self.latency_samples) > 100:
            self.latency_samples.pop(0)

    def record_drop(self) -> None:
        """Record a dropped frame."""
        self.frames_dropped += 1

    def record_connection_error(self) -> None:
        """Record a connection error."""
        self.connection_errors += 1

    def record_chunk_sent(self) -> None:
        """Record an audio chunk sent to cloud."""
        self.chunks_sent += 1

    @property
    def avg_latency_ms(self) -> float:
        """Average latency across all samples."""
        if not self.latency_samples:
            return 0.0
        return sum(self.latency_samples) / len(self.latency_samples)

    @property
    def p95_latency_ms(self) -> float:
        """95th percentile latency."""
        if not self.latency_samples:
            return 0.0
        sorted_samples = sorted(self.latency_samples)
        idx = int(len(sorted_samples) * 0.95)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]

    @property
    def drop_rate(self) -> float:
        """Frame drop rate (0.0 to 1.0)."""
        total = self.frames_generated + self.frames_dropped
        if total == 0:
            return 0.0
        return self.frames_dropped / total

    @property
    def effective_fps(self) -> float:
        """Effective frames per second since start."""
        elapsed = time.monotonic() - self._start_time
        if elapsed == 0:
            return 0.0
        return self.frames_generated / elapsed

    def to_dict(self) -> dict[str, Any]:
        """Export metrics as dictionary for logging/API."""
        return {
            "frames_generated": self.frames_generated,
            "frames_dropped": self.frames_dropped,
            "drop_rate": round(self.drop_rate, 3),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "p95_latency_ms": round(self.p95_latency_ms, 1),
            "connection_errors": self.connection_errors,
            "chunks_sent": self.chunks_sent,
            "effective_fps": round(self.effective_fps, 1),
        }

    def reset(self) -> None:
        """Reset all metrics."""
        self.frames_generated = 0
        self.frames_dropped = 0
        self.total_latency_ms = 0.0
        self.latency_samples.clear()
        self.connection_errors = 0
        self.chunks_sent = 0
        self._start_time = time.monotonic()
