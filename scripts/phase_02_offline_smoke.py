#!/usr/bin/env python3
from __future__ import annotations

from fastapi.testclient import TestClient

from _phase_common import (
    assert_decent_turn,
    load_app,
    parse_turn_events,
    print_summary,
    recv_until_turn_complete,
    send_json,
)


def main() -> int:
    print("[phase-02] offline smoke (mock_llm + mock_tts + stub_avatar)")
    app = load_app("offline_mock")

    with TestClient(app) as client:
        health = client.get("/v1/health")
        assert health.status_code == 200, health.text

        r = client.post("/v1/sessions", json={"persona_id": "casual"})
        assert r.status_code == 200, r.text
        session_id = r.json()["session_id"]

        with client.websocket_connect(f"/v1/sessions/{session_id}/stream") as ws:
            send_json(
                ws,
                {
                    "type": "user_text",
                    "text": "Explain one practical tip to improve model inference latency.",
                    "control": {
                        "emotion": {"label": "happy", "intensity": 0.7, "arousal": 0.6},
                        "character": {"speech_rate": 1.05, "expressivity": 0.8},
                    },
                },
            )
            events = recv_until_turn_complete(ws)

    if events[-1]["type"] == "error":
        raise RuntimeError(f"turn error: {events[-1]}")

    summary = parse_turn_events(events)
    assert_decent_turn(summary)
    print_summary("[phase-02]", summary)
    print("[phase-02] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
