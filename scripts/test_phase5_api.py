#!/usr/bin/env python3
"""
Phase 5: API Server Test
Tests the FastAPI server endpoints and WebSocket streaming.
Requires the server to be running (make dev).
"""
from __future__ import annotations
import asyncio
import json
import sys
import base64

try:
    import httpx
    import websockets
except ImportError:
    print("Install deps: uv add httpx websockets")
    sys.exit(1)


async def test_health_endpoint():
    print("=" * 60)
    print("PHASE 5: API Health Endpoint Test")
    print("=" * 60)

    base_url = "http://127.0.0.1:8000"

    async with httpx.AsyncClient(timeout=10) as client:
        print("[1/3] GET /v1/health...")
        r = await client.get(f"{base_url}/v1/health")
        print(f"      Status: {r.status_code}")

        if r.status_code != 200:
            print(f"      Response: {r.text}")
            print("      ❌ Server not running? Start with: make dev")
            return False

        data = r.json()
        print(f"      LLM healthy: {data['llm']['healthy']}")
        print(f"      TTS healthy: {data['tts']['healthy']}")
        print(f"      Avatar healthy: {data['avatar']['healthy']}")

        assert data['llm']['healthy'], "LLM not healthy"
        assert data['tts']['healthy'], "TTS not healthy"
        assert data['avatar']['healthy'], "Avatar not healthy"

    print("\n" + "=" * 60)
    print("PHASE 5 PASSED: Health endpoint working")
    print("=" * 60)
    return True


async def test_session_creation():
    print("\n" + "=" * 60)
    print("PHASE 5b: Session Creation Test")
    print("=" * 60)

    base_url = "http://127.0.0.1:8000"

    async with httpx.AsyncClient(timeout=10) as client:
        print("[1/2] POST /v1/sessions...")
        r = await client.post(
            f"{base_url}/v1/sessions",
            json={"persona_id": "casual"},
        )
        print(f"      Status: {r.status_code}")

        if r.status_code != 200:
            print(f"      Response: {r.text}")
            return False

        data = r.json()
        session_id = data["session_id"]
        print(f"      Session ID: {session_id}")

        print("[2/2] GET /v1/models...")
        r = await client.get(f"{base_url}/v1/models")
        print(f"      Status: {r.status_code}")
        data = r.json()
        print(f"      LLM streaming: {data['llm']['supports_streaming']}")
        print(f"      TTS emotion: {data['tts']['supports_emotion']}")

    print("\n" + "=" * 60)
    print("PHASE 5b PASSED: Session creation working")
    print("=" * 60)
    return True


async def test_websocket_streaming():
    print("\n" + "=" * 60)
    print("PHASE 5c: WebSocket Streaming Test")
    print("=" * 60)

    base_url = "http://127.0.0.1:8000"
    ws_url = "ws://127.0.0.1:8000"

    # Create session
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{base_url}/v1/sessions", json={"persona_id": "default"})
        session_id = r.json()["session_id"]
        print(f"[1/2] Created session: {session_id}")

    # Connect WebSocket
    print(f"[2/2] Connecting WebSocket...")
    ws_endpoint = f"{ws_url}/v1/sessions/{session_id}/stream"

    async with websockets.connect(ws_endpoint) as ws:
        # Send user message
        msg = {
            "type": "user_text",
            "text": "Say hello in exactly 3 words.",
            "control": {
                "emotion": {"label": "happy", "intensity": 0.7},
                "character": {"speech_rate": 1.0},
            },
        }
        await ws.send(json.dumps(msg))
        print(f"      Sent: {msg['text']}")

        # Collect events
        text_tokens = []
        audio_chunks = 0
        video_frames = 0
        total_audio_bytes = 0
        total_audio_duration = 0.0

        while True:
            raw = await ws.recv()
            evt = json.loads(raw)
            evt_type = evt.get("type")

            if evt_type == "text_delta":
                text_tokens.append(evt["token"])
                print(f"      [text] {evt['token']}", end="", flush=True)

            elif evt_type == "audio_chunk":
                audio_chunks += 1
                data_bytes = base64.b64decode(evt["data"])
                total_audio_bytes += len(data_bytes)
                total_audio_duration += evt["duration_ms"]
                print(f"\n      [audio] chunk #{audio_chunks}: {len(data_bytes)} bytes, dur={evt['duration_ms']:.0f}ms")

            elif evt_type == "video_frame":
                video_frames += 1
                if video_frames <= 3:
                    print(f"      [video] frame {evt['frame_index']}, drift={evt['drift_ms']:.1f}ms")
                elif video_frames == 4:
                    print("      [video] ... (suppressing further frame logs)")

            elif evt_type == "turn_complete":
                print(f"\n\n      Turn complete: {evt['turn_id']}")
                break

            elif evt_type == "error":
                print(f"\n      ERROR: {evt['code']} - {evt['message']}")
                return False

        # Summary
        full_text = "".join(text_tokens)
        print(f"\n      Summary:")
        print(f"      - Response: {full_text}")
        print(f"      - Text tokens: {len(text_tokens)}")
        print(f"      - Audio chunks: {audio_chunks}")
        print(f"      - Total audio: {total_audio_bytes} bytes, {total_audio_duration:.0f}ms")
        print(f"      - Video frames: {video_frames}")

        assert len(text_tokens) > 0, "No text tokens received"
        assert audio_chunks > 0, "No audio chunks received"
        assert video_frames > 0, "No video frames received"
        assert total_audio_duration > 0, "No audio duration"

    print("\n" + "=" * 60)
    print("PHASE 5c PASSED: WebSocket streaming working")
    print("=" * 60)
    return True


async def main():
    try:
        if not await test_health_endpoint():
            sys.exit(1)
        if not await test_session_creation():
            sys.exit(1)
        if not await test_websocket_streaming():
            sys.exit(1)
        print("\n✅ ALL PHASE 5 TESTS PASSED\n")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ ASSERTION FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
