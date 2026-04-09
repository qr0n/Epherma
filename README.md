# Ephemera

A Minecraft world that builds itself around you. Every world is unique — not by random seed, but by real-world research. The architecture studies an obscure piece of folklore, a Fortean anomaly, or a historical mystery, then constructs every room as an expression of it.

You will never see the same world twice.

---

## How It Works

Ephemera runs as three components working together:

### 1. Fabric Mod (`src/`)
A Minecraft 1.20.1 Fabric mod that acts as the bridge between the game and the AI pipeline. It streams real-time telemetry (position, health, inventory, world seed) over WebSocket to the middleware, and executes commands sent back by the orchestrator. Also registers a custom Steve-skin NPC entity (`ephemera:npc`).

### 2. Middleware (`ephemera-server/main.py`)
A FastAPI server (port 8000) that holds the latest telemetry state and accepts commands to forward to the game. Acts as the message bus between the mod and the orchestrator.

### 3. Orchestrator (`ephemera-server/orchestrator.py`)
The brain. A polling loop that reads telemetry, manages world state, and drives the full AI generation pipeline.

---

## The Generation Pipeline

```
World Seed (Minecraft) 
    → DecompositionSearch
        → LLM picks an obscure real-world subject (Seed)
        → Decomposes it into 5–7 research questions
        → Answers each question with a deep model
        → Synthesizes an 800–1200 word "World Soul" bible
    → UltraDirector
        → Reads World Soul + player telemetry
        → Writes a 4–6 paragraph act treatment (covers ~20 rooms)
        → LOCUS plans 5-room scenes with deliberate size pacing
    → Builder
        → LLM generates a Python function that issues Minecraft fill/setblock commands
        → Executed live against the game
    → Content Layer
        → Injects journals (written books on lecterns), named artifacts, NPCs, and ambient sounds
        → All content is contextualised by the World Soul
```

---

## Room Types

| Class | Dimensions (W×H×D) | Purpose |
|---|---|---|
| corridor | 60×8×20 | Transition, pressure |
| chamber | 80×40×60 | Standard room |
| cathedral | 80×80×80 | Release after constriction |
| void | 120×60×120 | Overwhelming scale |

Rooms are placed on a static absolute grid: positive X is the travel axis. Each room is separated by a 20-block stone corridor with glowstone lighting. The world never wraps, never overlaps.

---

## Setup

### Requirements
- Minecraft 1.20.1 with Fabric Loader
- Python 3.11+
- One or more Gemini API keys

### Mod
Build the mod and drop the JAR into your mods folder:
```bash
./gradlew build
# Copy build/libs/coordlogger-1.0.0.jar to your Minecraft mods folder
```

### Server
```bash
cd ephemera-server
pip install -r requirements.txt
```

Create a `.env` file:
```
GEMINI_API_KEY=your_key_here
# Or multiple keys for rotation:
GEMINI_API_KEYS=key1,key2,key3
```

### Running
Start middleware first, then orchestrator:
```bash
cd ephemera-server
uvicorn main:app --port 8000
python orchestrator.py
```

Then launch Minecraft. On first load, world generation begins automatically. The first run takes several minutes — the pipeline is researching your world.

---

## Models

All three modules (`decomposition.py`, `ultra_director.py`, `orchestrator.py`) use the model names set in their respective `__init__` defaults and the `BUILDER_MODEL` / `CONTENT_MODEL` constants. Currently running on `gemini-3.1-flash-lite-preview` globally. Swap to a pro model for significantly richer output.

---

## State

World state is persisted per Minecraft world seed in `.ephemera_{seed}.json` inside the server directory. Switching to a different world generates a new World Soul from scratch. Restarting with the same world resumes exactly where you left off.

---

## What Gets Logged

Everything. Run `python orchestrator.py` and you'll see the full pipeline in real time — every LLM call with model, latency, token count, rate limit hits, room builds, corridor placements, and player position deltas. All output is mirrored to `ephemera.log`.
