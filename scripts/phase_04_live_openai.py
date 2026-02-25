#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient
from dotenv import load_dotenv

from _phase_common import (
    assert_decent_turn,
    load_app,
    parse_turn_events,
    print_summary,
    recv_until_turn_complete,
    send_json,
)


def main() -> int:
    print("[phase-04] live OpenAI validation (api_only_mac profile)")
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("TTH_OPENAI_API_KEY"):
        print("[phase-04] SKIP: OPENAI_API_KEY not set")
        return 2

    app = load_app("api_only_mac")
    with TestClient(app) as client:
        health = client.get("/v1/health")
        assert health.status_code == 200, health.text
        health_json = health.json()
        if not health_json["llm"]["healthy"] or not health_json["tts"]["healthy"]:
            detail = f"{health_json['llm'].get('detail','')} {health_json['tts'].get('detail','')}".lower()
            if "nodename nor servname provided" in detail or "name or service not known" in detail:
                print("[phase-04] SKIP: network/DNS unavailable in this environment")
                return 2
            raise RuntimeError(
                f"provider health check failed: llm={health_json['llm']} tts={health_json['tts']}"
            )

        r = client.post("/v1/sessions", json={"persona_id": "casual"})
        assert r.status_code == 200, r.text
        session_id = r.json()["session_id"]

        with client.websocket_connect(f"/v1/sessions/{session_id}/stream") as ws:
            send_json(
                ws,
                {
                    "type": "user_text",
                    "text": "Give one practical MLOps tip in exactly two short sentences.",
                    "control": {
                        "emotion": {"label": "happy", "intensity": 0.6, "arousal": 0.4},
                        "character": {"speech_rate": 1.0, "expressivity": 0.7},
                    },
                },
            )
            events = recv_until_turn_complete(ws)

    if events[-1]["type"] == "error":
        raise RuntimeError(f"turn error: {events[-1]}")
    summary = parse_turn_events(events)
    assert_decent_turn(summary)
    print_summary("[phase-04]", summary)
    print("[phase-04] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
