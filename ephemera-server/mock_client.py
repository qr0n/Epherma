"""
Simulates the Fabric mod — connects to the telemetry WebSocket and streams
fake player telemetry at 1 Hz until interrupted.
"""

import asyncio
import json
import random
import websockets

WS_URL = "ws://localhost:8000/ws/telemetry"

ACTIONS = ["walking", "walking", "walking", "mining_stone", "opening_chest"]

async def run():
    print(f"Connecting to {WS_URL} ...")
    async with websockets.connect(WS_URL) as ws:
        print("Connected. Streaming telemetry (Ctrl-C to stop).\n")
        z = 256
        while True:
            z += random.randint(3, 5)
            packet = {
                "player_pos": [128, 64, z],
                "facing": "North",
                "action": random.choice(ACTIONS),
                "inventory": random.sample(
                    ["torch", "book", "iron_sword", "oak_log", "diamond", "bread"],
                    k=random.randint(1, 4),
                ),
            }
            await ws.send(json.dumps(packet))
            print(f"  sent: {packet}")
            await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nMock client stopped.")
