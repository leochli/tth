#!/usr/bin/env python3
"""
TTH Demo Script — smoke test end-to-end pipeline.
Usage: python scripts/demo.py [--host HOST] [--port PORT]
"""
from __future__ import annotations
import argparse
import asyncio
import base64
import json
import sys


async def run_demo(host: str, port: int) -> None:
    try:
        import websockets
    except ImportError:
        print("Error: websockets package not installed. Run: uv add websockets")
        sys.exit(1)

    import httpx

    base_url = f"http://{host}:{port}"
    ws_base  = f"ws://{host}:{port}"

    print(f"\nTTH Demo — connecting to {base_url}\n")

    # ── 1. Health check ───────────────────────────────────────────────────────
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{base_url}/v1/health")
        if r.status_code != 200:
            print(f"[FAIL] Health check failed: {r.status_code}")
            sys.exit(1)
        health = r.json()
        print(f"[health] llm={health['llm']['healthy']}  "
              f"tts={health['tts']['healthy']}  "
              f"avatar={health['avatar']['healthy']}")

        # ── 2. Create session ─────────────────────────────────────────────────
        r = await client.post(
            f"{base_url}/v1/sessions",
            json={"persona_id": "casual"},
        )
        r.raise_for_status()
        session_id = r.json()["session_id"]
        print(f"[session created] {session_id}\n")

    # ── 3. WebSocket turn ─────────────────────────────────────────────────────
    ws_url = f"{ws_base}/v1/sessions/{session_id}/stream"
    async with websockets.connect(ws_url) as ws:
        # Send a user message
        msg = {
            "type": "user_text",
            "text": "Hello! Tell me something interesting in one sentence.",
            "control": {
                "emotion": {"label": "happy", "intensity": 0.6},
                "character": {"speech_rate": 1.0, "expressivity": 0.7},
            },
        }
        await ws.send(json.dumps(msg))
        print(f"[sent] {msg['text']}\n")

        text_tokens: list[str] = []
        audio_chunks = 0
        video_frames = 0
        turn_complete = False

        async for raw in ws:
            evt = json.loads(raw)
            etype = evt.get("type")

            if etype == "text_delta":
                text_tokens.append(evt["token"])
                print(evt["token"], end="", flush=True)

            elif etype == "audio_chunk":
                audio_chunks += 1
                raw_bytes = base64.b64decode(evt["data"])
                print(
                    f"\n[audio_chunk #{audio_chunks}] "
                    f"{len(raw_bytes)} bytes @ {evt['timestamp_ms']:.1f}ms  "
                    f"dur={evt['duration_ms']:.1f}ms",
                    flush=True,
                )
                assert evt["duration_ms"] > 0, "duration_ms must be > 0!"

            elif etype == "video_frame":
                video_frames += 1
                raw_bytes = base64.b64decode(evt["data"])
                if video_frames <= 3:   # only print first few to avoid spam
                    print(
                        f"[video_frame #{video_frames}] "
                        f"{evt['width']}x{evt['height']} {evt['content_type']} "
                        f"@ {evt['timestamp_ms']:.1f}ms  drift={evt['drift_ms']:.1f}ms",
                        flush=True,
                    )
                elif video_frames == 4:
                    print("[video_frame ...] (suppressing further frame logs)")

            elif etype == "turn_complete":
                turn_complete = True
                print(f"\n\n[turn_complete] turn_id={evt['turn_id']}")
                break

            elif etype == "error":
                print(f"\n[ERROR] {evt['code']}: {evt['message']}")
                sys.exit(1)

    print(f"\n{'─'*60}")
    print(f"Full response: {''.join(text_tokens)}")
    print(f"Audio chunks:  {audio_chunks}")
    print(f"Video frames:  {video_frames}")
    print(f"Turn complete: {turn_complete}")
    print(f"{'─'*60}")

    if not turn_complete:
        print("[FAIL] Turn did not complete")
        sys.exit(1)
    if audio_chunks == 0:
        print("[FAIL] No audio chunks received")
        sys.exit(1)

    print("\n[PASS] Smoke test passed!")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    asyncio.run(run_demo(args.host, args.port))


if __name__ == "__main__":
    main()
