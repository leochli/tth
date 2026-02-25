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


def _run_turn(ws, text: str, control: dict | None = None):
    payload = {"type": "user_text", "text": text}
    if control is not None:
        payload["control"] = control
    send_json(ws, payload)
    return recv_until_turn_complete(ws)


def main() -> int:
    print("[phase-03] offline multi-turn + control update validation")
    app = load_app("offline_mock")

    with TestClient(app) as client:
        r = client.post("/v1/sessions", json={"persona_id": "professional"})
        assert r.status_code == 200, r.text
        session_id = r.json()["session_id"]

        with client.websocket_connect(f"/v1/sessions/{session_id}/stream") as ws:
            # Turn 1 with explicit neutral control
            t1 = _run_turn(
                ws,
                text="Give one concise database optimization suggestion.",
                control={
                    "emotion": {"label": "neutral", "intensity": 0.5, "arousal": 0.0},
                    "character": {"speech_rate": 1.0, "expressivity": 0.4},
                },
            )
            assert t1[-1]["type"] == "turn_complete", t1[-1]
            s1 = parse_turn_events(t1)
            assert_decent_turn(s1)
            print_summary("[phase-03 turn-1]", s1)

            # Update control without sending text yet (must apply on next turn).
            send_json(
                ws,
                {
                    "type": "control_update",
                    "control": {
                        "emotion": {"label": "happy", "intensity": 0.8, "arousal": 0.8},
                        "character": {"speech_rate": 1.2, "expressivity": 0.9},
                    },
                },
            )

            # Turn 2 should inherit pending control update.
            t2 = _run_turn(ws, text="Now give one concise caching tip.")
            assert t2[-1]["type"] == "turn_complete", t2[-1]
            s2 = parse_turn_events(t2)
            assert_decent_turn(s2)
            print_summary("[phase-03 turn-2]", s2)

    # Mock LLM marks happy mood with 'exciting'.
    assert "exciting" in s2.text.lower(), "pending control did not affect next turn output"
    print("[phase-03] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
