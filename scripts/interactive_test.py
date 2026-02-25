#!/usr/bin/env python3
"""
Interactive TTH test - sends text, saves audio to MP3 and video to GIF.

Usage:
    # Terminal 1: Start server
    make dev

    # Terminal 2: Run test
    uv run python scripts/interactive_test.py "What is machine learning?"
    # Output: output.mp3, output.gif
"""
import asyncio
import base64
import json
import sys
from pathlib import Path

try:
    import httpx
    import websockets
    from PIL import Image
    import numpy as np
except ImportError as e:
    print(f"Missing dep: {e}. Run: uv add httpx websockets pillow numpy")
    sys.exit(1)


async def test(text: str, host: str = "127.0.0.1", port: int = 8000) -> None:
    base_url = f"http://{host}:{port}"
    ws_base = f"ws://{host}:{port}"

    print(f"Connecting to {base_url}...")

    # Create session
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{base_url}/v1/sessions", json={"persona_id": "casual"})
        session_id = r.json()["session_id"]
        print(f"Session: {session_id}")

    # Collect audio and video
    audio_chunks: list[bytes] = []
    video_frames: list[tuple[int, bytes]] = []  # (frame_index, rgb_bytes)

    ws_url = f"{ws_base}/v1/sessions/{session_id}/stream"
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({
            "type": "user_text",
            "text": text,
            "control": {"emotion": {"label": "happy"}, "character": {}}
        }))
        print(f"\nSent: {text}\n")
        print("Response: ", end="", flush=True)

        async for raw in ws:
            evt = json.loads(raw)
            t = evt.get("type")

            if t == "text_delta":
                print(evt["token"], end="", flush=True)
            elif t == "audio_chunk":
                audio_chunks.append(base64.b64decode(evt["data"]))
            elif t == "video_frame":
                frame_data = base64.b64decode(evt["data"])
                video_frames.append((evt["frame_index"], frame_data))
            elif t == "turn_complete":
                break

    print("\n")

    # Save audio to MP3
    audio_path = Path("output.mp3")
    audio_path.write_bytes(b"".join(audio_chunks))
    print(f"Saved audio: {audio_path} ({len(audio_chunks)} chunks, {audio_path.stat().st_size} bytes)")

    # Save video frames as animated GIF
    if video_frames:
        frames_pil: list[Image.Image] = []
        for idx, rgb_bytes in sorted(video_frames, key=lambda x: x[0]):
            # raw_rgb is 256x256x3 bytes
            arr = np.frombuffer(rgb_bytes, dtype=np.uint8).reshape(256, 256, 3)
            img = Image.fromarray(arr, "RGB")
            frames_pil.append(img)

        gif_path = Path("output.gif")
        frames_pil[0].save(
            gif_path,
            save_all=True,
            append_images=frames_pil[1:],
            duration=40,  # 25 FPS = 40ms per frame
            loop=0
        )
        print(f"Saved video: {gif_path} ({len(frames_pil)} frames)")

    print("\nDone! Open output.mp3 and output.gif to see/hear results.")


if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) or "Hello! Tell me something interesting."
    asyncio.run(test(text))
