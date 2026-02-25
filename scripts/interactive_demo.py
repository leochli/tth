#!/usr/bin/env python3
"""
Interactive TTH demo - multi-turn conversation with live audio/video.

Usage:
    # Terminal 1: Start server
    make dev

    # Terminal 2: Run demo
    uv run python scripts/interactive_demo.py

    Type your messages, get responses with audio/video.
    - Audio saved to: output_turn_{N}.mp3
    - Video saved to: output_turn_{N}.gif
    - Type 'quit' to exit
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


async def run_turn(
    ws: websockets.WebSocketClientProtocol,
    text: str,
    turn_num: int,
) -> bool:
    """Send text and collect response. Returns True if should continue."""
    audio_chunks: list[bytes] = []
    video_frames: list[tuple[int, bytes]] = []

    await ws.send(json.dumps({
        "type": "user_text",
        "text": text,
        "control": {"emotion": {"label": "happy"}, "character": {}}
    }))

    print(f"\n[You]: {text}")
    print("[Avatar]: ", end="", flush=True)

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
        elif t == "error":
            print(f"\n[Error]: {evt.get('message', evt)}")
            return True

    print("\n")

    # Save audio
    if audio_chunks:
        audio_path = Path(f"output_turn_{turn_num}.mp3")
        audio_path.write_bytes(b"".join(audio_chunks))
        print(f"  -> Audio: {audio_path} ({len(audio_chunks)} chunks)")

    # Save video as GIF
    if video_frames:
        frames_pil: list[Image.Image] = []
        for idx, rgb_bytes in sorted(video_frames, key=lambda x: x[0]):
            arr = np.frombuffer(rgb_bytes, dtype=np.uint8).reshape(256, 256, 3)
            img = Image.fromarray(arr, "RGB")
            frames_pil.append(img)

        gif_path = Path(f"output_turn_{turn_num}.gif")
        frames_pil[0].save(
            gif_path,
            save_all=True,
            append_images=frames_pil[1:],
            duration=40,
            loop=0
        )
        print(f"  -> Video: {gif_path} ({len(frames_pil)} frames)")

    return True


async def demo(host: str = "127.0.0.1", port: int = 8000) -> None:
    base_url = f"http://{host}:{port}"
    ws_base = f"ws://{host}:{port}"

    print(f"Connecting to {base_url}...")

    # Create session
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{base_url}/v1/sessions", json={"persona_id": "casual"})
        session_id = r.json()["session_id"]
        print(f"Session: {session_id}")

    print("\n" + "=" * 50)
    print("Interactive TTH Demo")
    print("Type your message and press Enter to send.")
    print("Type 'quit' to exit.")
    print("=" * 50 + "\n")

    turn_num = 0
    ws_url = f"{ws_base}/v1/sessions/{session_id}/stream"

    async with websockets.connect(ws_url) as ws:
        while True:
            try:
                text = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting...")
                break

            if not text:
                continue
            if text.lower() in ("quit", "exit", "q"):
                print("Goodbye!")
                break

            turn_num += 1
            await run_turn(ws, text, turn_num)

    print("\nDemo complete!")


if __name__ == "__main__":
    asyncio.run(demo())
