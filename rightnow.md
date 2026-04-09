# Ephemera — Where We Are Right Now

## What This Project Is
A Minecraft AI orchestration system. A world that reads its inhabitant and builds itself in response. 

- **Element 1:** Fabric mod (Minecraft 1.20.1) — rich telemetry (speed, health delta, actions), command execution.
- **Element 2:** Python middleware server (FastAPI) — WebSocket bridge.
- **Element 3:** Two-tier AI orchestrator — Director (Narrative Arc) + Builder (Code Generation).
- **Element 4:** Lore & Artifact Layer — Signs, Books, and Ghost Entities integrated.

---

## The Architecture

```
Minecraft (Fabric mod)
    │  WebSocket — telemetry out, commands in
    ▼
ephemera-server/main.py  (FastAPI middleware)
    │  GET /state     — poll latest telemetry
    │  POST /command  — forward any JSON to mod
    ▼
orchestrator.py
    ├── Director LLM  — Plans sequences of 10 rooms with descriptive briefs and artifacts.
    └── Builder LLM   — Generates raw Python procedural functions to build the spaces.
```

---

## Recent Breakthroughs
- **Narrative Arc Implementation:** The Director now follows a 3-Act structure (Sterile -> Glitch -> Collapse).
- **Environmental Storytelling:** Support for rare Artifacts (Signs, Written Books on Lecterns) and Ghost sightings.
- **Seamless Connectivity:** Fixed! The Orchestrator now builds a continuous sequence of rooms connected by sealed corridors along the X-axis.
- **Rich Telemetry:** Mod now tracks sprinting, walking, mining, combat, and damage states.

---

## Live Test Results
- Full pipeline is airtight.
- Minecraft is successfully rendering complex, AI-coded geometry on the fly.
- Signs and Books are correctly placing text without formatting errors.
- Player connectivity is stable.

## Known Limitations
- Builder occasionally generates invalid block IDs (silently ignored by Minecraft).
- No persistence between separate world sessions.
- Environmental "cleanup" (deleting rooms behind the player) not yet implemented.

---

## Next
Refining the Act 3 "Collapse" aesthetics and exploring Element 4 (The Global ARG layer).
