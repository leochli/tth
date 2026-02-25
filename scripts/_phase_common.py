#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@dataclass
class TurnSummary:
    text: str
    audio_chunks: int
    audio_bytes: int
    video_frames: int
    mean_abs_drift_ms: float


def _assert_event_shape(evt: dict[str, Any]) -> None:
    assert "type" in evt, f"event missing type: {evt}"


def _is_decent_text(text: str) -> tuple[bool, str]:
    stripped = text.strip()
    if len(stripped) < 30:
        return False, "text too short"
    if re.search(r"(.)\1{6,}", stripped):
        return False, "text contains repeated-character artifacts"
    words = re.findall(r"[A-Za-z']+", stripped)
    if len(words) < 8:
        return False, "not enough words"
    uniq = len({w.lower() for w in words}) / max(1, len(words))
    if uniq < 0.35:
        return False, "low lexical diversity"
    if not re.search(r"[.!?]", stripped):
        return False, "missing sentence punctuation"
    return True, "ok"


def parse_turn_events(events: list[dict[str, Any]]) -> TurnSummary:
    text_tokens: list[str] = []
    audio_chunks = 0
    audio_bytes = 0
    video_frames = 0
    drift_values: list[float] = []

    for evt in events:
        _assert_event_shape(evt)
        t = evt["type"]
        if t == "text_delta":
            text_tokens.append(evt.get("token", ""))
        elif t == "audio_chunk":
            raw = base64.b64decode(evt["data"])
            audio_bytes += len(raw)
            audio_chunks += 1
            assert evt["duration_ms"] > 0, "audio chunk duration must be > 0"
        elif t == "video_frame":
            _ = base64.b64decode(evt["data"])
            video_frames += 1
            drift_values.append(abs(float(evt.get("drift_ms", 0.0))))
        elif t in {"turn_complete", "error"}:
            continue

    mean_abs_drift = sum(drift_values) / len(drift_values) if drift_values else 0.0
    return TurnSummary(
        text="".join(text_tokens),
        audio_chunks=audio_chunks,
        audio_bytes=audio_bytes,
        video_frames=video_frames,
        mean_abs_drift_ms=mean_abs_drift,
    )


def assert_decent_turn(summary: TurnSummary) -> None:
    ok, why = _is_decent_text(summary.text)
    assert ok, f"text quality check failed: {why}; text={summary.text!r}"
    assert summary.audio_chunks > 0, "expected at least one audio chunk"
    assert summary.audio_bytes > 0, "expected non-empty audio payload"
    assert summary.video_frames > 0, "expected at least one video frame"
    # Stub-avatar mode uses chunk-level timestamps, so drift can be larger than
    # production renderers. Keep a practical upper bound for phased checks.
    assert summary.mean_abs_drift_ms <= 250.0, "mean drift too high"


def print_summary(prefix: str, summary: TurnSummary) -> None:
    print(f"{prefix} text: {summary.text.strip()}")
    print(
        f"{prefix} stats: audio_chunks={summary.audio_chunks} "
        f"audio_bytes={summary.audio_bytes} video_frames={summary.video_frames} "
        f"mean_abs_drift_ms={summary.mean_abs_drift_ms:.1f}"
    )


def load_app(profile: str):
    """
    Load FastAPI app with a specific config profile.
    Each phase script is a separate process, so module-level settings are safe.
    """
    os.environ["TTH_PROFILE"] = profile
    from tth.api.main import app  # imported after profile selection

    return app


def recv_until_turn_complete(ws, max_events: int = 1200) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for _ in range(max_events):
        evt = ws.receive_json()
        events.append(evt)
        if evt.get("type") in {"turn_complete", "error"}:
            return events
    raise RuntimeError("turn did not complete within event budget")


def send_json(ws, payload: dict[str, Any]) -> None:
    ws.send_text(json.dumps(payload))
