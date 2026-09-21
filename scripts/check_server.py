"""Read-only smoke check against a running local dashboard."""

import asyncio
import json

import httpx
from websockets.asyncio.client import connect


async def check() -> None:
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=5, trust_env=False) as client:
        for path in ("/", "/static/style.css", "/static/app.js", "/api/session/state"):
            response = await client.get(path)
            response.raise_for_status()
            print(f"OK {path}")
    async with connect("ws://localhost:8000/ws", origin="http://localhost:8000", open_timeout=5) as websocket:
        state = json.loads(await asyncio.wait_for(websocket.recv(), timeout=5))
        assert "running_count" in state and "player_hands" in state
        print(f"OK WebSocket: revision {state['revision']}, camera {state['camera']['status']}")


if __name__ == "__main__":
    asyncio.run(check())
