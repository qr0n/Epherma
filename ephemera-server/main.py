import uvicorn
from fastapi import FastAPI, Request, WebSocket

from telemetry import telemetry_ws, get_latest_state
from commander import send_command

app = FastAPI(title="Ephemera Server", version="0.1.0")


@app.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket):
    await telemetry_ws(websocket)


@app.post("/command")
async def post_command(request: Request):
    return await send_command(request)


@app.get("/state")
async def get_state():
    return get_latest_state()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
