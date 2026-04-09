# Ephemera — Fabric Mod Handoff Document

## Overview
Ephemera is a server-side Fabric mod for Minecraft 1.20.1. It is **element 1 of 4** in a larger AI orchestration system also called Ephemera.

The mod connects to a Python middleware server (`ephemera-server/`) over WebSocket and:
- **Streams player telemetry** (position, facing direction, health, inventory) to the server once per second
- **Receives Minecraft commands** from the server and executes them on the server thread

## System Architecture
```
Minecraft Server
  └── Ephemera Mod (this)
        │  WebSocket ws://localhost:8000/ws/telemetry
        ▼
  ephemera-server/   ← FastAPI Python middleware (element 2)
        │
        ▼
  [elements 3 & 4 — not yet built]
```

## Technical Specifications
- **Minecraft Version:** 1.20.1
- **Mod Loader:** Fabric Loader (0.14.21+)
- **Required Dependencies:** Fabric API (for 1.20.1)
- **Java Version:** Java 17
- **Build System:** Gradle 8.10 (via Docker for consistent builds on Apple Silicon)
- **Bundled library:** `org.java-websocket:Java-WebSocket:1.5.4` (included in JAR)

## Project Structure
```
/Users/iron/DevWork/Epherma/
├── build.gradle               # Gradle build — includes Java-WebSocket dependency
├── settings.gradle
├── gradle.properties          # Version pins
├── Dockerfile                 # Gradle 8.10 + JDK 17 build environment
├── ephemera-server/           # Python middleware server (element 2)
│   ├── main.py
│   ├── telemetry.py
│   ├── commander.py
│   ├── mock_client.py
│   └── requirements.txt
└── src/main/
    ├── java/com/example/coordlogger/
    │   ├── CoordLogger.java       # Mod entry point + tick loop
    │   └── EphemeraClient.java   # WebSocket client
    └── resources/
        └── fabric.mod.json
```

## Core Logic

### `CoordLogger.java`
- Implements `ModInitializer` — entry point called by Fabric on server start
- On `SERVER_STARTED`: creates an `EphemeraClient` and initiates the WebSocket connection
- On `SERVER_STOPPING`: cleanly closes the WebSocket
- Tick loop (`END_SERVER_TICK`): every 20 ticks (~1 second), sends a telemetry JSON packet for each online player via the WebSocket

Telemetry packet shape:
```json
{
  "player_name": "ARCL001",
  "player_pos": [123.45, 64.0, -56.78],
  "facing": "North",
  "health": 20.0,
  "inventory": ["minecraft:torch", "minecraft:diamond_sword"]
}
```

### `EphemeraClient.java`
- Extends `org.java_websocket.client.WebSocketClient`
- `onOpen`: logs successful connection
- `onMessage`: parses incoming `{"command": "/setblock ..."}` JSON and dispatches execution via `server.execute()` to ensure it runs on the Minecraft server thread
- `onClose` / `onError`: logs disconnection/errors
- `sendTelemetry(String json)`: sends a JSON string if the connection is open; silently drops if not

## Python Middleware (`ephemera-server/`)

| File | Role |
|---|---|
| `main.py` | FastAPI app — three routes: `WS /ws/telemetry`, `POST /command`, `GET /state` |
| `telemetry.py` | Accepts the mod's WebSocket, stores latest telemetry in memory, tracks `active_connection` |
| `commander.py` | Forwards `POST /command` payloads to the mod over the active WebSocket; returns `503` if mod is not connected |
| `mock_client.py` | Simulates the mod for testing without Minecraft running — sends fake telemetry at 1 Hz |

### Running the server
```bash
cd ephemera-server
pip install -r requirements.txt
python main.py
```

### Testing without Minecraft
```bash
# Terminal 1
python main.py

# Terminal 2
python mock_client.py

# Terminal 3 — send a command
curl -X POST http://localhost:8000/command \
  -H "Content-Type: application/json" \
  -d '{"command": "/setblock 100 64 100 minecraft:stone"}'

# Poll state
curl http://localhost:8000/state
```

## Build Instructions (Apple Silicon / Docker)
Due to Java version compatibility issues on macOS Apple Silicon, use Docker to build:

```bash
docker run --rm -v "$(pwd)":/home/gradle/src -w /home/gradle/src gradle:8.10-jdk17 gradle build --no-daemon
```

> **Note:** First build downloads Minecraft jars, mappings, and the Java-WebSocket library — expect 10–15 minutes.

Output JAR: `build/libs/coordlogger-1.0.0.jar`

## Installation
1. Set your launcher/server to **Fabric 1.20.1** with Fabric Loader 0.14.21+
2. Download **Fabric API** for 1.20.1 from Modrinth or CurseForge
3. Place both `Fabric API` and `coordlogger-1.0.0.jar` in the `mods/` folder
4. Start the server — ensure `ephemera-server` is running on `localhost:8000` first

## Troubleshooting History
- **Build Failures (initial):** Local Java version mismatches and Gradle wrapper issues — resolved by using Docker (`gradle:8.10-jdk17`).
- **ClassNotFoundException (early build):** Produced a 1KB jar that crashed the game — caused by `CoordLogger.java` being placed in `src/main/resources` instead of `src/main/java/com/example/coordlogger/`.
- **String Formatting:** Python-style `{:.2f}` was used in SLF4J — SLF4J doesn't support this. Fixed by using `String.format("%.2f")` before passing to the logger.
