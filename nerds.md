# Ephemera — Technical Deep Dive

For people who want to understand exactly what's happening and why every decision was made.

---

## System Topology

```
┌─────────────────────────────────────────────────────────┐
│  Minecraft 1.20.1 (JVM)                                 │
│                                                         │
│  ServerTickEvents.END_SERVER_TICK (every 20 ticks = 1s) │
│    → buildTelemetry(player)                             │
│    → wsClient.sendTelemetry(json)  ──────────────────┐  │
│                                                      │  │
│  EphemeraClient (java-websocket)  ◄──────────────────┘  │
│    also receives command packets ──────────────────┐    │
│    → server.execute(() → executeWithPrefix(...))   │    │
└──────────────────────────────────────────────┬─────┼────┘
                                               │     │
                                    WebSocket  │     │  WebSocket
                                    /ws/telemetry   /ws/telemetry
                                               │     │
┌──────────────────────────────────────────────▼─────▼────┐
│  FastAPI Middleware (uvicorn, port 8000)                 │
│                                                         │
│  telemetry.py                                           │
│    latest_state: dict  ← in-memory snapshot             │
│    active_connections: set[WebSocket]                   │
│                                                         │
│  GET  /state        → returns latest_state              │
│  POST /command      → fans out to all active WebSockets │
└──────────────────────────────────────────────┬──────────┘
                                               │
                              HTTP polling     │  HTTP POST
                              every 2s         │  per command
                                               │
┌──────────────────────────────────────────────▼──────────┐
│  Orchestrator (Python, blocking main loop)              │
│                                                         │
│  while True:                                            │
│    telemetry = GET /state                               │
│    _init_world()   (once per world seed)                │
│    _world_setup()  (once per world)                     │
│    replenish plan buffer   → UltraDirector              │
│    build from buffer       → Builder LLM                │
│    mark visited            → trigger rings              │
│    sleep(2.0)                                           │
└─────────────────────────────────────────────────────────┘
```

The middleware is deliberately stateless and dumb. It exists solely because the Minecraft server can't be polled directly from Python — the mod pushes state, and the orchestrator pulls it. The WebSocket stays open for the lifetime of the Minecraft server; commands fan out to all connected mods (useful for multi-instance setups later).

---

## The Telemetry Packet

Every second, the mod emits this JSON over WebSocket:

```json
{
  "player_pos": [x, y, z],
  "player_name": "iron",
  "facing": "North",
  "health": 20.0,
  "health_delta": -2.0,
  "speed": 5.6,
  "action": "sprinting",
  "inventory": ["minecraft:diamond_sword", "minecraft:torch"],
  "world_seed": -4234567890123456789
}
```

**Speed** is computed as the Euclidean distance between the player's position across two consecutive 20-tick snapshots — effectively blocks/second. Sprinting in Minecraft is ~5.6 b/s, walking ~4.3 b/s. The action classifier uses these thresholds plus the held item and health delta to classify what the player is doing. This is the data the Ultra Director reads as "confession, not data."

**health_delta** is negative when damage was taken, positive when healing, zero otherwise. Sampled once per second so a burst of damage may show as a single large negative delta.

**world_seed** comes from `currentServer.getOverworld().getSeed()` — the 64-bit long that Minecraft generates at world creation. This is the key for per-world state files on the Python side.

---

## Why WebSocket + HTTP Polling Instead of Direct Connection

The obvious question: why not have the orchestrator connect directly to the Minecraft WebSocket?

Because the command flow is bidirectional and async. The mod needs to *receive* commands (to execute them on the server thread) and *send* telemetry. A single WebSocket for both directions is possible but creates ordering problems — you'd need to multiplex command responses and telemetry frames over one channel.

The current design separates concerns cleanly:
- Telemetry flows **mod → middleware → orchestrator** (push model, always fresh)
- Commands flow **orchestrator → middleware → mod** (request model, fire and forget)

The orchestrator's 2-second polling loop is not tight enough to miss anything meaningful. Room transitions happen over tens of seconds.

---

## The Fabric Mod Architecture

### Entity Registration

```java
EPHEM_NPC = Registry.register(
    Registries.ENTITY_TYPE,
    new Identifier("ephemera", "npc"),
    EntityType.Builder.<EphemNpc>create(EphemNpc::new, SpawnGroup.MISC)
        .build("ephemera.npc")
);
FabricDefaultAttributeRegistry.register(EPHEM_NPC, EphemNpc.createAttributes().build());
```

In Yarn mappings for 1.20.1, `EntityType.Builder` requires a string translation key argument to `.build()`. This is not documented anywhere obvious — `.build()` with no args doesn't exist in this version. The `SpawnGroup.MISC` is important: MISC entities don't participate in the natural mob spawning budget, so they won't be suppressed by `doMobSpawning false`.

### EphemNpc Goal Stack

```java
goalSelector.add(1, new LookAtEntityGoal(this, PlayerEntity.class, 8.0f));
goalSelector.add(2, new LookAroundGoal(this));
goalSelector.add(3, new WanderAroundFarGoal(this, 0.5));
```

Goals are evaluated in priority order each tick. Priority 1 (look at player) preempts priority 2 (idle look), which preempts priority 3 (wander). The result: NPCs notice you immediately, hold eye contact, and wander when you're out of range. `PathAwareEntity` base class handles full navmesh pathfinding for free.

### Renderer

```java
extends BipedEntityRenderer<EphemNpc, PlayerEntityModel<EphemNpc>>
// Texture: minecraft:textures/entity/player/wide/steve.png
// Constructor: super(ctx, new PlayerEntityModel<>(ctx.getPart(EntityModelLayers.PLAYER), false), 0.5f)
```

`PlayerEntityModel` takes a boolean `thinArms` — `false` means Steve's 4px arms rather than Alex's 3px arms. The `0.5f` is the shadow radius in blocks. Registered in `EphemeraClientMod` which implements `ClientModInitializer` — client-side code in Fabric must be isolated in a separate entrypoint to avoid crashing dedicated servers.

### Command Execution

```java
server.getCommandManager().executeWithPrefix(server.getCommandSource(), cmd);
```

`getCommandSource()` returns the server's own command source — equivalent to running commands from the server console. It has operator-level permissions and bypasses all permission checks. `executeWithPrefix` handles the `/` prefix stripping automatically.

---

## The Static World Grid

```python
WORLD_ANCHOR = [0, 64, 0]   # origin point
SPAWN_HALF   = 10            # spawn room extends ±10 blocks from anchor
CORRIDOR_LEN = 20            # gap between rooms

_room_origin(n) = [30 + n*100, 63, -dims[2]//2]
```

Rooms sit on a 100-block slot grid along positive X. With the largest room type (void, 120 wide) a room fits in a 100-block slot only if CORRIDOR_LEN is reduced — current config lets void rooms slightly overlap their nominal slot, which is acceptable because the corridor is built after the room.

**Why absolute coordinates?** Earlier versions used player-relative coordinates — rooms generated at `pos + offset`. This caused catastrophic failures: if the player moved during generation, subsequent rooms spawned offset from the previous ones. Race condition between the 2-second poll loop and the time it takes to generate 5 briefs + build a room (~30-120 seconds with LLM calls). Absolute grid eliminates this entirely.

**Y=63 for `_FLOOR_Y`** means the floor is at Y=63, one block below the `WORLD_ANCHOR` Y=64. Room origins are `[x, 63, z]` and rooms extend upward. This places the floor at the standard Minecraft sea level (Y=63), with the player walking on Y=64.

---

## The Chunked Fill Problem

Minecraft's `/fill` command has a hard limit of 32,768 blocks (32³ = 32,768). Any fill larger than that silently fails or throws a command error.

A void room is 120×60×120 = 864,000 blocks. That's 26× the limit.

```python
def _chunked_fill(send_cmd, x1, y1, z1, x2, y2, z2, block):
    CHUNK = 32
    lx, hx = sorted([int(x1), int(x2)])
    ly, hy = sorted([int(y1), int(y2)])
    lz, hz = sorted([int(z1), int(z2)])
    for x in range(lx, hx + 1, CHUNK):
        for y in range(ly, hy + 1, CHUNK):
            for z in range(lz, hz + 1, CHUNK):
                send_cmd(f"fill {x} {y} {z} "
                         f"{min(x+CHUNK-1,hx)} {min(y+CHUNK-1,hy)} {min(z+CHUNK-1,hz)} {block}")
```

This decomposes any fill into ≤32³ sub-fills. For a void room air clear: `ceil(120/32) × ceil(60/32) × ceil(120/32)` = `4 × 2 × 4` = 32 fill commands. Each one is synchronous from the server's perspective; there's no parallelism, but Minecraft processes them fast enough that the visual effect is near-instant.

The sorted `lx, hx = sorted(...)` handles inverted coordinates gracefully — if the LLM-generated builder code passes `x1 > x2`, it still works.

---

## The Three-Tier LLM Pipeline

### Why Three Tiers?

A single LLM call per room would produce rooms with no narrative coherence — each would be generated in isolation with no memory of what came before and no overarching emotional arc.

The three tiers solve different temporal scales:

| Tier | Scope | Model | Regenerates |
|---|---|---|---|
| UltraDirector (treatment) | 20 rooms (one act) | deep | Every act, weighted by telemetry |
| LOCUS (scene briefs) | 5 rooms (one scene) | fast | Every 5 rooms, within act context |
| Builder | 1 room | fast | Every room |

The treatment is a 4-6 paragraph prose document — not a room list, but an emotional and atmospheric arc. It tells LOCUS *what this sequence of spaces IS* before LOCUS decides what each individual space looks like. This is the same separation that exists between a film's story treatment and its shot list.

### DecompositionSearch

The decomposition pattern is borrowed from multi-hop question answering research. Rather than asking a single LLM "describe a creepy world," you:

1. Ask for a specific real-world subject (seed)
2. Decompose that subject into orthogonal research questions
3. Answer each question independently with maximum specificity
4. Synthesize all answers into a coherent document

The independence of step 3 is key. Each research branch is answered without knowledge of the other branches, which prevents the model from anchoring on early answers. The synthesis step then finds the connections.

Research branches typically cover: historical record, cultural transmission, sensory/atmospheric qualities, symbolic vocabulary, narrative possibility, and emotional register. The synthesizer is explicitly told to write in present tense as if describing a place that *exists right now* — this kills hedging language and forces specificity.

### The exec() Pattern

```python
namespace = {"math": math, "chunked_fill": _chunked_fill}
exec(raw, namespace)
build_fn = namespace["build"]
build_fn(self.send_cmd, origin)
```

The Builder LLM generates Python source code that is `exec()`'d at runtime. The namespace is intentionally minimal — only `math` and `chunked_fill` are provided. The generated function receives `send_cmd` and `origin` as arguments at call time, not at definition time, which means it can't capture ambient state.

This is the riskiest part of the architecture from a security standpoint. `exec()` with a restricted namespace is not a sandbox — a sufficiently motivated model could still import modules or do harm. In practice, the prompt constrains output tightly enough that this hasn't been an issue, and the system runs locally against a local Minecraft server. It would need a real sandbox (subprocess, restricted interpreter) before any multi-tenant deployment.

Compilation errors (syntax errors in the generated code) are caught separately from runtime errors (errors during actual block placement). Compilation errors log and retry; runtime errors catch, clear the bounding box with air, and mark the room built to prevent infinite retry loops.

---

## The RotatingClient

```python
@property
def chat(self):
    client = self.clients[self.index]
    self.index = (self.index + 1) % len(self.clients)
    return client.chat
```

The Gemini API is accessed via the OpenAI-compatible endpoint. Rate limits are per API key per minute (RPM) and per day (RPD). With multiple keys, each successive `.chat` access returns the next key's client in round-robin order.

The property pattern means rotation happens at the point of access — `client.chat.completions.create(...)` resolves `client.chat` once, which increments the index and returns the correct underlying client's `.chat` object. The chained `.completions.create(...)` then runs against that specific client.

Edge case: `DecompositionSearch` and `UltraDirector` are initialized with the `RotatingClient` instance, so their internal `self.client.chat` calls also rotate. All three modules compete for the same key pool, which is the correct behavior — it prevents one module from exhausting a key while others wait.

---

## Rate Limiting Strategy

```python
# Before every call
time.sleep(REQUEST_DELAY)  # 2.0s

# On 429
wait = 30 * (2 ** attempt)  # 30s, 60s, 120s
time.sleep(wait)
```

The 2-second pre-call delay spaces out calls across the key pool. With 3 keys rotating and a 2-second delay, the effective rate is ~1.5 calls per key per 6 seconds, well under typical RPM limits for flash models.

The exponential backoff on 429 is more aggressive than the original 15s/30s/45s linear schedule. Most Gemini rate limit windows reset within 60 seconds, so a 30s wait for the first failure and 60s for the second gives the window time to fully reset before the third attempt.

`_research_branches` is the worst case: 5-7 sequential deep model calls with 2s delays between each = minimum 10-14 seconds of sleep time before the actual API calls. At pro model latency (10-30s per call), first-world generation takes 3-8 minutes. This is a known limitation — parallelizing with `ThreadPoolExecutor` would cut it to ~max(single_branch_time) + overhead.

---

## Room Sizing and Corridor Matching

```python
SIZE_CLASSES = {
    "corridor": {"width": 60, "depth": 20, "height": 8},   # long in X, narrow in Z
    "chamber":  {"width": 80, "depth": 60, "height": 40},
    "cathedral":{"width": 80, "depth": 80, "height": 80},
    "void":     {"width": 120,"depth": 120,"height": 60},
}
```

Width = X extent (travel axis). Depth = Z extent. Height = Y extent.

Corridor entrance matching was a recurring bug. The corridor is built with known dimensions `(h, d)` and the Builder LLM is told explicitly what size opening to leave:

```python
ch = min(dims[1], 10)   # corridor height capped at 10
cd = min(dims[2], 10)   # corridor depth capped at 10
entrance_h = ch - 1     # interior clear height (wall thickness = 1)
entrance_w = cd
```

The cap at 10 prevents cathedral (80-block tall) rooms from requiring 80-block tall corridors. The cost is that the entrance in the cathedral wall is 9 blocks tall while the room is 80 blocks tall — architecturally this is actually desirable (low entrance into vast space = compression-release, a classic spatial narrative tool).

---

## Particle Trigger Rings

```python
TRIGGER_R = 40
ex = float(room["origin"][0])  # entrance face, not room center

for deg in range(0, 360, 20):  # 18 particles per ring
    rad = math.radians(deg)
    px = ex + TRIGGER_R * math.cos(rad)
    pz = _AZ + TRIGGER_R * math.sin(rad)
    send_cmd(f"particle minecraft:end_rod {px:.1f} {fy:.1f} {pz:.1f} 0 0.1 0 0 1 force")
```

The ring is centered at the entrance face of the room (not the room center), so from inside the corridor you see a ring of particles around the entrance you're approaching. `force` mode bypasses the client's particle distance culling so the ring is visible from further away. The vertical pillar at the entrance X is a beacon visible from altitude.

Previously centered at room center — this meant the ring appeared at the exact moment you'd trigger "visited," making it useless as a visual warning. Moving to entrance face gives ~20-40 blocks of approach time to see the ring before entering.

---

## State Persistence

```
.ephemera_{world_seed}.json
```

World state is keyed on the 64-bit Minecraft world seed. File contents:

```json
{
  "setup_done": true,
  "room_counter": 14,
  "world_soul": "...(1000 words)...",
  "world_soul_seed": "The Eilean Mor Lighthouse Disappearance",
  "world_seed": -4234567890123456789,
  "plan": [...],
  "narrative_log": ["last 5 room descriptions..."]
}
```

`plan` contains the full list of all rooms ever generated for this world — origin, dimensions, brief, built/visited/deleted flags, corridor metadata. On restart, `next_x` is reconstructed from the last room's origin + dimensions + CORRIDOR_LEN. The World Soul is stored in full (not recomputed) — this is critical because regenerating it would produce a different soul, breaking narrative coherence mid-world.

The `narrative_log` (last 5 room descriptions, truncated to 80 chars each) is passed to LOCUS as the "last 5 rooms history" context. It's a rolling window rather than a full history to keep prompt size bounded.

---

## The Lectern Book Problem

```python
def _place_lectern(send_cmd, x, y, z, title, author, pages):
    pgs = ",".join([json.dumps({"text": p}) for p in pages])
    cmd = (f'setblock {int(x)} {int(y)} {int(z)} '
           f'minecraft:lectern{{Book:{{id:"minecraft:written_book",Count:1b,'
           f'tag:{{title:"{title}",author:"{author}",pages:[{pgs}]}}}}}}')
    send_cmd(cmd)
```

Written book NBT in 1.20.1 expects `pages` as a list of JSON-encoded text component strings. Each page is a JSON string (`{"text": "..."}`) serialized as a string *within* the NBT array. The double-serialization is intentional and required by the format — the NBT parser expects string values in the pages array, not embedded objects.

Special characters in journal content (quotes, backslashes) will break the NBT parsing. This is unguarded and is a known fragility point.

---

## What "Never Experience the Same World Twice" Actually Means

The claim isn't procedural randomness — it's epistemic uniqueness. Two playthroughs might both explore "a dark stone dungeon" but one was built from research into the Centralia mine fire and the other from research into the Fading Island of Hy-Brasil. The geometry may converge; the *meaning* never does.

The World Soul document contains architectural logic, symbolic vocabulary, emotional register, and "one sentence that is the world's secret." Every room generated after that document exists in relation to it — the Builder, LOCUS, and UltraDirector all receive it as context. When the model works correctly, rooms feel *about* something, not just *like* something.

This is the core design bet: that a well-researched, well-synthesized context document produces more coherent atmospheric output than any amount of fine-tuning or careful prompt engineering on the geometry layer alone. The geometry is a consequence of the soul, not the other way around.
