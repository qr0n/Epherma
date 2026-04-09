# Gemini Implementation Prompt — Ultra Director + Decomposition Search

## What you are building

You are extending **Ephemera**, a Minecraft AI orchestration system. The codebase is at
`/Users/iron/DevWork/Epherma` (also on GitHub at https://github.com/qr0n/Epherma).

You are implementing two new modules that replace the current flat `call_director()` function
in `ephemera-server/orchestrator.py`:

1. **`decomposition.py`** — A research module that generates a deep "World Soul" document for
   each new Minecraft world by decomposing a seed concept, researching its branches via web
   search, and synthesizing the findings into a dense narrative bible.

2. **`ultra_director.py`** — A 3-tier narrative pipeline (Ultra Director → LOCUS → scene briefs)
   that reads the World Soul and produces richly contextualised room briefs for the Builder.

---

## Current system — read this first

### File structure
```
ephemera-server/
  orchestrator.py   ← main loop, Builder LLM, world grid, state persistence
  main.py           ← FastAPI server (telemetry WebSocket + /command + /state)
  telemetry.py      ← stores latest player state
  commander.py      ← forwards commands to the Minecraft mod via WebSocket
```

### How the current pipeline works
1. `Orchestrator.run()` polls `/state` every 2s for player telemetry
2. When `_setup_done` is False, `_world_setup()` runs: teleports player to [0,64,0],
   builds a spawn room, pre-builds the first corridor
3. When fewer than 2 unvisited built rooms exist, it calls `call_director()` to plan
   10 more rooms, then `call_builder()` for each one
4. `call_builder()` uses Gemini to write a Python `def build(send_cmd, origin)` function
   which is `exec()`d and called to place blocks via `/fill` and `/setblock` commands
5. State (setup_done, room_counter) is persisted to `.ephemera_{world_seed}.json`

### World grid (static, absolute coordinates)
- Travel axis: positive X
- `WORLD_ANCHOR = [0, 64, 0]` — spawn room centre
- `ROOM_WIDTH = 80`, `ROOM_DEPTH = 60`, `ROOM_HEIGHT = 40`
- Room N origin: `[30 + N*100, 63, -30]`
- Corridors: 20-block sealed stone tunnels between rooms

### LLM client (already configured)
```python
from openai import OpenAI
client = OpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)
# Use model: "gemini-2.0-flash" for fast calls
# Use model: "gemini-2.0-pro" or "gemini-2.5-pro-preview-05-06" for deep reasoning calls
```

### Telemetry shape (what the player sends every second)
```json
{
  "player_pos": [x, y, z],
  "player_name": "...",
  "facing": "North|South|East|West",
  "health": 20.0,
  "health_delta": 0.0,
  "speed": 4.3,
  "action": "idle|walking|sprinting|mining|in_combat|taking_damage",
  "inventory": ["minecraft:diamond_sword", ...],
  "world_seed": -1234567890
}
```

---

## Module 1 — `decomposition.py`

### Purpose
Generate a **World Soul** document: a dense 800–1200 word narrative bible that gives
each world a specific, researched identity grounded in real-world folklore, Fortean
phenomena, weird fiction, or historical anomaly. This runs ONCE per world at init time.
The result is saved to the state file so it survives orchestrator restarts.

### Seed generation
Do NOT use a hardcoded premise list — that defeats the point. Instead, call the LLM to
generate the seed:

```
System: You are a researcher of obscure phenomena. Name one specific, real-world thing —
        a piece of folklore, a Fortean event, a weird fiction element, an anomalous
        location, or a historical mystery — that has genuine cultural depth and is not
        widely known. Not a genre. Not a trope. A specific named thing.
        Respond with ONLY the name. Nothing else.

User:   Give me one seed for a world that should feel unique, unsettling, and real.
```

Examples of good seeds the model might return:
- "The Bélmez Faces" (faces that spontaneously appear in a Spanish farmhouse floor)
- "Kaspar Hauser" (a boy who appeared in 1820s Nuremberg claiming to have grown up in total darkness)
- "The Nullarbor Chunk" (a piece of the Nullarbor Plain that was allegedly removed and returned)
- "Robert Ley's unfinished city" (an abandoned Nazi resort for 20,000 people, never occupied)
- "The Toynbee Tiles" (mysterious mosaic tiles embedded in Philadelphia asphalt for decades)

Never use: vampires, haunted houses, "ancient evil", zombies, generic fantasy tropes.

### Decomposition step
Take the seed and decompose it into 5–7 research questions:

```
System: You are a research decomposer. Given a subject, generate 5-7 specific
        research questions that together would give a researcher deep understanding
        of the subject — not just facts, but atmosphere, cultural context, emotional
        register, symbolic meaning, and narrative possibility.
        Return ONLY a JSON array of question strings.

User:   Subject: "{seed}"
```

### Research step
For each question, perform a web search (use `google-generativeai` with search grounding
OR make a real HTTP request to a search API if available OR use the LLM's own knowledge
with a "research this specifically" prompt if no search API is available).

If using LLM knowledge only (fallback):
```
System: You are a research specialist. Answer the following question with maximum
        specificity. Cite specific names, dates, places, quotes where you know them.
        Do not pad. Do not hedge. If you don't know something specific, say so and
        move on. This research will be used to build a narrative world.

User:   Research question: "{question}"
        Subject context: "{seed}"
```

Collect all answers into a `research_notes` dict: `{question: answer}`.

### Synthesis step
Take the seed + all research notes and synthesize the World Soul:

```
System: You are a production designer and narrative architect. You have been given
        research notes about a subject. Your job is to write a World Soul document —
        a dense, specific, atmospheric narrative bible that will be used to generate
        a Minecraft world that feels like it IS this subject, not just themed around it.

        The document should read like the private notes of someone who has been inside
        this world. It should contain:
        - The specific atmosphere (sensory: light, sound, smell, texture)
        - The architectural logic (what kinds of spaces does this subject inhabit?)
        - The symbolic vocabulary (recurring objects, materials, patterns)
        - The emotional register (not "scary" — what SPECIFIC feeling?)
        - What the world knows that the player doesn't
        - One sentence that is the world's secret

        800-1200 words. Dense. No headings. No bullet points. Prose only.
        Write in present tense as if describing a place that exists right now.

User:   Seed: "{seed}"

        Research notes:
        {formatted research notes}

        Write the World Soul:
```

### Output and storage
Save to state file alongside existing fields:
```json
{
  "setup_done": true,
  "room_counter": 4,
  "world_seed": -1234567890,
  "world_soul_seed": "The Toynbee Tiles",
  "world_soul": "The floor is always the first thing..."
}
```

### Class interface
```python
class DecompositionSearch:
    def __init__(self, client, model_fast="gemini-2.0-flash",
                 model_deep="gemini-2.5-pro-preview-05-06"):
        ...

    def generate_world_soul(self) -> tuple[str, str]:
        """Returns (seed_name, world_soul_text). Takes 30-90 seconds."""
        seed = self._generate_seed()
        questions = self._decompose(seed)
        research = self._research_branches(seed, questions)
        soul = self._synthesize(seed, research)
        return seed, soul

    def _generate_seed(self) -> str: ...
    def _decompose(self, seed: str) -> list[str]: ...
    def _research_branches(self, seed: str, questions: list[str]) -> dict: ...
    def _synthesize(self, seed: str, research: dict) -> str: ...
```

---

## Module 2 — `ultra_director.py`

### Purpose
Replace the current flat `call_director()` (which plans 10 generic rooms) with a
3-tier narrative pipeline:

```
Ultra Director  (per act — every 20 rooms)
    reads World Soul + player telemetry aggregate
    writes a 4-6 paragraph narrative treatment
    "What is happening in this act of the world's story?"

LOCUS           (per scene — every 5 rooms)
    reads treatment + last 5 room descriptions
    writes 5 scene briefs, one per room
    each brief: description + size_class + mood + material_hint + content_hint

Builder         (unchanged — reads scene brief, writes geometry)
```

### Ultra Director

Called when `room_counter % 20 == 0` or the plan is empty on first run.

**Input:**
- `world_soul` (full text from DecompositionSearch)
- `world_soul_seed` (the seed name, e.g. "The Toynbee Tiles")
- `telemetry_aggregate` — computed from last 20 rooms' telemetry samples:
  ```python
  {
    "avg_speed": float,        # was player rushing or exploring?
    "total_health_lost": float,
    "time_in_rooms": float,    # seconds spent in built rooms
    "actions_seen": list[str], # unique actions observed
    "items_carried": list[str] # current inventory
  }
  ```
- `previous_act_summary` (str, or None on first call)

**System prompt:**
```
You are the Ultra Director of Ephemera — a world that is alive, aware of its player,
and building itself in response.

You have been given the World Soul of this specific world. This is not a theme or a
genre. It is a real thing that was researched and understood. Every space in this world
is an expression of that understanding.

You have also been given telemetry from the player's last act. Read it as confession,
not data. A player who sprinted through every room is afraid, or bored, or both. A
player who lost health slowly is in a different relationship with the world than one
who lost it all at once.

Write the treatment for the next act — 4 to 6 paragraphs. This is not a room list.
This is what the next 20 rooms ARE, collectively. Their emotional arc. What the world
is choosing to show the player. Whether the world is responding to the player or
deliberately ignoring them.

Do not describe individual rooms. Do not mention Minecraft. Write as if describing
a sequence in a film that has not been made yet.
```

**Output:** Raw prose, 4-6 paragraphs. Stored in memory as `self.current_treatment`.

### LOCUS

Called when fewer than 2 unbuilt rooms remain in the current 5-room scene batch.

**Input:**
- `current_treatment` (from Ultra Director)
- `narrative_log` (last 5 room descriptions)
- `rooms_into_act` (int — which room of 20 we're on, affects pacing)

**size_class mapping:**
```python
SIZE_CLASSES = {
    "corridor":  {"width": 20,  "depth": 60, "height": 8},   # tight, linear
    "chamber":   {"width": 80,  "depth": 60, "height": 40},  # default
    "cathedral": {"width": 80,  "depth": 80, "height": 80},  # vast, vertical
    "void":      {"width": 120, "depth": 120, "height": 60}, # overwhelming scale
}
```

**Output:** JSON array of 5 scene briefs:
```json
[
  {
    "description": "2-4 vivid sentences for the Builder. Specific materials, geometry, atmosphere.",
    "size_class": "corridor|chamber|cathedral|void",
    "mood": "clinical|sacred|decayed|liminal|oppressive|serene|wrong",
    "material_hint": "primary material palette — e.g. 'quartz and iron bars' or 'dark oak and soul sand'",
    "content_hint": "journal|artifact|npc|sound_only|empty",
    "connects_to_next": "doorway|gap|staircase|open"
  }
]
```

**System prompt:**
```
You are LOCUS — the scene planner for Ephemera.

You receive the act treatment (the emotional arc of the next 20 rooms) and plan
the next 5 rooms as a scene. A scene is a cluster of spaces that share a mood and
build toward a single emotional moment.

The description field is a brief for the Builder — it must be specific enough for
procedural geometry. Mention specific shapes (ribbed vault, descending spiral, wide
low ceiling), specific materials (smooth basalt, cracked quartz, hanging chains),
and specific spatial qualities (cramped, echoing, asymmetric).

Vary size_class deliberately. A cathedral after three corridors is a release.
A corridor after a void is a trap. Pacing is your primary tool.

content_hint tells the Content Layer what to place after geometry. Use it sparingly —
empty rooms are as important as full ones.

Output ONLY a raw JSON array of exactly 5 objects. No markdown. No explanation.
```

### Content Layer

After the Builder places geometry, run the content layer based on `content_hint`:

```python
def apply_content(self, room_id: int, brief: dict, origin: list):
    hint = brief.get("content_hint", "empty")
    world_soul = self.world_soul  # full text

    if hint == "journal":
        self._place_journal(room_id, brief, origin)
    elif hint == "artifact":
        self._place_artifact(room_id, brief, origin)
    elif hint == "npc":
        self._place_npc(origin)
    elif hint == "sound_only":
        self._schedule_sound(origin)
    # "empty" → do nothing
```

**`_place_journal`:** Generate 2-4 paragraph book text using LOCUS's scene description
+ world_soul. Place as a written book on a lectern at the room's centre.
Command sequence:
```
/setblock {x} {y} {z} minecraft:lectern
/give @a written_book{...NBT...}
```
Use JSON NBT for written_book. Pages are JSON text component arrays.

**`_place_artifact`:** Generate a name for the item using world_soul context.
Place as an item frame on a block at room centre. Use a thematically appropriate
base item (clock, compass, skull, totem_of_undying, etc. — chosen by LLM).
```
/setblock {x} {y} {z} minecraft:oak_log
/summon item_frame {x} {y+1} {z} {Item:{id:"minecraft:clock",Count:1b},CustomName:'{"text":"..."}'}
```

**`_place_npc`:** Spawn the mod's custom NPC entity at a specific point (not the
centre — off to one side, facing inward). The NPC already exists in the mod as
`ephemera:npc`. Command: `/summon ephemera:npc {x} {y} {z}`

**`_schedule_sound`:** Don't play immediately. Store `{origin, brief}` in
`self.pending_sounds`. In the run loop, when player enters trigger zone of a
sound_only room, play:
```
/playsound minecraft:{ambient_sound} ambient @a {x} {y} {z} 1.0 {pitch}
```
Sound and pitch chosen by a small LLM call based on mood.

---

## Integration into orchestrator.py

### Changes required

1. **Import at top:**
```python
from decomposition import DecompositionSearch
from ultra_director import UltraDirector
```

2. **In `Orchestrator.__init__`:**
```python
self.decomposer    = DecompositionSearch(client)
self.ultra_dir     = UltraDirector(client)
self.world_soul    = None
self.world_soul_seed = None
self.pending_sounds = []
```

3. **In `_load_state` / `_save_state`:** persist `world_soul` and `world_soul_seed`

4. **In `_init_world`:** after loading state, if `world_soul` is None:
```python
print("[Init] Generating World Soul — this takes 30-90 seconds...")
self.world_soul_seed, self.world_soul = self.decomposer.generate_world_soul()
print(f"[Init] World Soul generated. Seed: {self.world_soul_seed}")
self._save_state()
```
Pass `world_soul` and `world_soul_seed` into `UltraDirector`.

5. **Replace `call_director()` calls** with `self.ultra_dir.get_next_scene_briefs(telemetry)`,
   which returns a list of 5 dicts with `description`, `size_class`, `content_hint`, etc.

6. **After each room is built**, call `self.apply_content(rid, brief, origin)`.

7. **`_room_bounds` must use `size_class`** from the brief, not fixed constants.
   Update `_room_origin` and `_room_bounds` to accept an optional `size_class` param
   and look up dimensions from `SIZE_CLASSES`. The corridor between rooms should be
   sized to match the smaller of the two rooms it connects.

---

## Rules and constraints

- **Do not break the existing Builder pipeline.** The Builder still receives a `description`
  string and bounding box and writes a `def build(send_cmd, origin)` function. Nothing
  about that interface changes.
- **Do not add dependencies** beyond what's already in `requirements.txt` unless absolutely
  necessary. If you need web search, use the `google-generativeai` package's search
  grounding feature with the existing `GEMINI_API_KEY`, or make plain `requests` calls.
- **Decomposition runs ONCE per world** — gate it on `world_soul is None`. Never regenerate
  mid-session.
- **State file** continues to be `.ephemera_{world_seed}.json` in the server directory.
  Add `world_soul`, `world_soul_seed` to its schema.
- **All LLM calls follow the existing retry pattern** (3 attempts, 15s backoff on 429).
- **The fallback if DecompositionSearch fails** is a minimal World Soul generated directly
  from the world seed number: `"A place built from the number {seed}. Cold. Mathematical.
  Indifferent."` — this is intentionally sparse. It still produces something coherent.
- **Models to use:**
  - Seed generation: `gemini-2.0-flash`
  - Decomposition questions: `gemini-2.0-flash`
  - Research branches: `gemini-2.5-pro-preview-05-06` (needs depth)
  - Synthesis: `gemini-2.5-pro-preview-05-06` (needs depth)
  - Ultra Director treatment: `gemini-2.5-pro-preview-05-06`
  - LOCUS scene briefs: `gemini-2.0-flash`
  - Content (journal text, artifact names): `gemini-2.0-flash`

---

## What done looks like

1. `python3 orchestrator.py` starts
2. On first telemetry, it prints:
   `[Init] Generating World Soul — this takes 30-90 seconds...`
   `[Init] World Soul generated. Seed: The Toynbee Tiles`
3. World setup runs (spawn room, gamerules, teleport)
4. LOCUS plans a 5-room scene informed by the World Soul and act treatment
5. Builder builds each room with geometry sized to `size_class`
6. After each room, the Content Layer places a journal / artifact / NPC / nothing
7. Player enters room, reads a book that feels like it *belongs* to this specific world
8. On restart, World Soul is loaded from state file — no regeneration
9. Different Minecraft world (different seed) → different World Soul → genuinely different world

---

## Files to create
- `ephemera-server/decomposition.py` — standalone, no Ephemera imports
- `ephemera-server/ultra_director.py` — imports nothing from orchestrator

## Files to modify
- `ephemera-server/orchestrator.py` — wire in the two new modules, update room sizing,
  add content layer calls, persist world_soul in state

Do not modify: `main.py`, `telemetry.py`, `commander.py`, the Fabric mod.
