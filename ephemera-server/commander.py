from datetime import datetime
from fastapi import HTTPException, Request
import json

from telemetry import get_active_connections


async def send_command(request: Request) -> dict:
    body = await request.json()

    conns = get_active_connections()
    if not conns:
        print(f"[{_ts()}] command dropped (no mod connected) | {body}")
        raise HTTPException(status_code=503, detail="Fabric mod not connected")

    payload = json.dumps(body)
    for conn in list(conns):
        await conn.send_text(payload)

    label = body.get("command") or body.get("action") or "unknown"
    print(f"[{_ts()}] command sent | {label}")
    return {"status": "sent"}


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]
