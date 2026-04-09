from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
import json

# In-memory store for the latest telemetry snapshot
latest_state: dict = {}

# Active WebSocket connections pool
active_connections: set[WebSocket] = set()


async def telemetry_ws(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    print(f"[{_ts()}] Fabric mod connected from {websocket.client}")
    try:
        while True:
            raw = await websocket.receive_text()
            packet = json.loads(raw)
            latest_state.update(packet)
            latest_state["_received_at"] = _ts()
            print(f"[{_ts()}] telemetry | pos={packet.get('player_pos')} "
                  f"facing={packet.get('facing')} health={packet.get('health')} "
                  f"action={packet.get('action')} inv={packet.get('inventory')}")
    except WebSocketDisconnect:
        print(f"[{_ts()}] Fabric mod disconnected")
    finally:
        active_connections.discard(websocket)


def get_latest_state() -> dict:
    return latest_state


def get_active_connections() -> set[WebSocket]:
    return active_connections


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]
