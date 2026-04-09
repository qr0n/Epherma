import time
import requests
import json
import math
import os
import pathlib
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

MIDDLEWARE_URL = "http://localhost:8000"
POLL_INTERVAL = 2.0

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("Warning: GEMINI_API_KEY not set. Builder will use fallback rooms.")

client = OpenAI(
    api_key=api_key or "mock_key",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

# Keeping the requested models
DIRECTOR_MODEL = "gemini-3-flash-preview"
BUILDER_MODEL = "gemini-3-flash-preview"

_STATE_DIR = pathlib.Path(__file__).parent

# ---------------------------------------------------------------------------
# Static world grid — absolute layout along positive X axis.
# ---------------------------------------------------------------------------
WORLD_ANCHOR = [0, 64, 0]
SPAWN_HALF = 10 
ROOM_WIDTH = 80 
ROOM_DEPTH = 60 
ROOM_HEIGHT = 40 
CORRIDOR_LEN = 20 

_AX, _AY, _AZ = WORLD_ANCHOR
_FLOOR_Y = _AY - 1
_ROOM_STEP = ROOM_WIDTH + CORRIDOR_LEN 
_ROOM_X0 = _AX + SPAWN_HALF + CORRIDOR_LEN


def _room_origin(index: int) -> list:
    return [_ROOM_X0 + index * _ROOM_STEP, _FLOOR_Y, _AZ - ROOM_DEPTH // 2]


def _room_bounds(index: int) -> tuple:
    ox, oy, oz = _room_origin(index)
    return ox, oy, oz, ox + ROOM_WIDTH - 1, oy + ROOM_HEIGHT - 1, oz + ROOM_DEPTH - 1


class Orchestrator:
    def __init__(self):
        self.plan = []
        self.narrative_log = []
        self.room_counter = 0
        self._setup_done = False
        self._last_action = "idle"
        self._state_file = None   # set on first telemetry once world seed is known

    def _init_world(self, world_seed):
        """Called once we know the world seed. Loads per-world state."""
        self._state_file = _STATE_DIR / f".ephemera_{world_seed}.json"
        if self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text())
                self._setup_done  = data.get("setup_done", False)
                self.room_counter = data.get("room_counter", 0)
                if self._setup_done:
                    print(f"[State] World {world_seed}: resuming, {self.room_counter} rooms built.")
            except Exception:
                pass

    def _save_state(self):
        if self._state_file:
            self._state_file.write_text(json.dumps({
                "setup_done":   self._setup_done,
                "room_counter": self.room_counter,
            }))

    # ------------------------------------------------------------------ setup

    def _world_setup(self):
        print("[Setup] Configuring world...")
        for cmd in [
            "gamerule doDaylightCycle false",
            "gamerule doWeatherCycle false",
            "gamerule doMobSpawning false",
            "gamerule doMobLoot false",
            "gamerule keepInventory true",
            "gamerule naturalRegeneration true",
            "time set 18000",
            "weather clear 999999",
        ]:
            self.send_cmd(cmd)

        self.send_cmd(f"tp @a {_AX} {_AY} {_AZ}")
        time.sleep(0.5)

        fy = _FLOOR_Y
        # Spawn room
        _chunked_fill(self.send_cmd, _AX-10, fy, _AZ-10, _AX+10, fy+7, _AZ+10, "minecraft:smooth_stone")
        _chunked_fill(self.send_cmd, _AX-9, fy+1, _AZ-9, _AX+9, fy+6, _AZ+9, "minecraft:air")
        
        # Entrance to first corridor
        for dz in [-1, 0, 1]:
            for dy in range(1, 5):
                self.send_cmd(f"setblock {_AX+10} {fy+dy} {_AZ+dz} minecraft:air")

        self._build_corridor_between(_AX + 10, _ROOM_X0)
        self._setup_done = True
        self._save_state()

    def _build_corridor_between(self, from_x: int, to_x: int):
        fy = _FLOOR_Y
        _chunked_fill(self.send_cmd, from_x, fy, _AZ-3, to_x, fy+5, _AZ+3, "minecraft:smooth_stone")
        _chunked_fill(self.send_cmd, from_x, fy+1, _AZ-2, to_x, fy+4, _AZ+2, "minecraft:air")
        mid_x = (from_x + to_x) // 2
        self.send_cmd(f"setblock {mid_x} {fy+5} {_AZ} minecraft:glowstone")

    def _delete_corridor_between(self, from_x: int, to_x: int):
        """Erases a corridor."""
        _chunked_fill(self.send_cmd, from_x, _FLOOR_Y, _AZ-3, to_x, _FLOOR_Y+5, _AZ+3, "minecraft:air")

    # ------------------------------------------------------------------ comms

    def get_telemetry(self):
        try:
            resp = requests.get(f"{MIDDLEWARE_URL}/state")
            if resp.status_code == 200: return resp.json()
        except: return None

    def send_cmd(self, cmd):
        try: requests.post(f"{MIDDLEWARE_URL}/command", json={"command": cmd})
        except: pass

    # ---------------------------------------------------------------- tier 1

    def call_director(self, telemetry):
        print("[Director] Planning next 10 spaces (strictly enforcing scale and sparsity)...")
        narrative = "\n".join(f"{i+1}. {d}" for i, d in enumerate(self.narrative_log)) or "The player has just entered the system."

        system_prompt = """You are LOCUS — the Director of a non-existent world. 
Your goal is to make the player feel like they are exploring a broken, abandoned simulation. 

SPATIAL RULES:
- SCALE (MANDATORY): You have a massive 80x60x40 bounding box. USE IT. Do not make small corridors or narrow halls. Make cathedral-scale chambers, vast indoor voids, and vertically impossible structures. 
- VARIETY: Alternate between massive exposure and deliberate claustrophobia. If the last room was a hall, the next must be a giant atrium.

ARTIFACT SPARSITY RULES (CRITICAL):
- Artifacts (signs, books, ghosts) are EXTREMELY RARE. 
- At least 8 out of 10 rooms should have ZERO artifacts. Just empty, silent, vast architecture.
- NEVER place more than one artifact in a single room.
- Only place an artifact if it is a major narrative pivot.

Your Narrative Arc:
1. ACT 1 (Rooms 1-3): Sterile, industrial, helpful.
2. ACT 2 (Rooms 4-7): The simulation glitches. Architecture becomes organic, impossible, or vastly scaled.
3. ACT 3 (Rooms 8-10): Total collapse. The world 'unmaking' itself. Existential dread. No real-world IPs.

Output ONLY a raw JSON array of exactly 10 objects:
{
  "description": "2-4 vivid sentences. DESCRIBE THE SCALE (e.g. 'A 40-block high vault').",
  "artifacts": [
     {"type": "sign", "text": "..."},
     {"type": "book", "title": "...", "author": "...", "pages": ["..."]},
     {"type": "spawn_ghost", "note": "Brief figure"}
  ]
}
Note: If a room has no artifacts, OMIT the 'artifacts' key."""

        prompt = f"""Player state: {telemetry.get('action')} at {telemetry.get('player_pos')}.
History: {narrative}
Plan the next 10 spaces. Enforce extreme sparsity. Use the full 80x60x40 scale. Output raw JSON only."""

        try:
            resp = client.chat.completions.create(
                model=DIRECTOR_MODEL,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                temperature=1.0,
            )
            return json.loads(_strip_fences(resp.choices[0].message.content))
        except:
            return [{"description": "A cold, vast, featureless hall."} for _ in range(10)]

    # ---------------------------------------------------------------- tier 2

    def call_builder(self, room_data: dict, room_id: int):
        x1, y1, z1, x2, y2, z2 = _room_bounds(room_id)
        origin = _room_origin(room_id)
        desc = room_data["description"]
        artifacts = json.dumps(room_data.get("artifacts", []))

        print(f"[Builder] Coding room {room_id} (scale {x2-x1+1}x{y2-y1+1}x{z2-z1+1})...")
        system_prompt = f"""You are a Minecraft procedural builder. 
Write a Python function `def build(send_cmd, origin):` to build the described room.

TOOLKIT:
- chunked_fill(send_cmd, x1, y1, z1, x2, y2, z2, block)
- place_sign(send_cmd, x, y, z, text)
- place_lectern(send_cmd, x, y, z, title, author, pages_list)
- spawn_ghost(send_cmd, x, y, z)

GEOMETRY RULES:
1. CLEAR BOX: chunked_fill(send_cmd, {x1}, {y1}, {z1}, {x2}, {y2}, {z2}, "minecraft:air")
2. CENTERED CONNECTIVITY: You MUST keep a 3x4 air gap at the center of the X-axis start ({x1}) and end ({x2}) walls.
3. SCALE: The box is HUGE ({x2-x1+1}x{y2-y1+1}x{z2-z1+1}). Do not build tiny objects. Fill the space with architectural scale.
4. ADDITIVE ONLY: Build floors, then walls, then features.

Artifacts to place: {artifacts}
Output ONLY raw Python code."""

        prompt = f"Description: {desc}"

        try:
            resp = client.chat.completions.create(
                model=BUILDER_MODEL,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                temperature=0.7,
            )
            raw = _strip_fences(resp.choices[0].message.content)
            namespace = {
                "math": math, 
                "chunked_fill": _chunked_fill,
                "place_sign": _place_sign,
                "place_lectern": _place_lectern,
                "spawn_ghost": _spawn_ghost
            }
            exec(raw, namespace)
            return namespace["build"]
        except:
            return _fallback_build

    def run(self):
        print("Ephemera Orchestrator — Sparsity & Scale Fix Active")
        while True:
            telemetry = self.get_telemetry()
            if not telemetry or "player_pos" not in telemetry:
                time.sleep(POLL_INTERVAL)
                continue

            if self._state_file is None and "world_seed" in telemetry:
                self._init_world(telemetry["world_seed"])

            if not self._setup_done:
                self._world_setup()

            # --- GASLIGHTING REACTIONS ---
            action = telemetry.get("action", "idle")
            if action == "mining" and self._last_action != "mining":
                px, py, pz = telemetry["player_pos"]
                print(f"[Gaslight] Player is mining. Spooking...")
                self.send_cmd(f"playsound minecraft:entity.elder_guardian.curse ambient @a {px} {py} {pz} 1 0.5")
                _place_sign(self.send_cmd, px, py+1, pz, "THERE IS NOTHING BEYOND THE WALLS")
            self._last_action = action

            # Building & Connectivity
            if sum(1 for r in self.plan if r["built"] and not r["visited"]) < 2:
                if not any(not r["built"] for r in self.plan):
                    new_rooms = self.call_director(telemetry)
                    for r in new_rooms:
                        self.plan.append({"data": r, "built": False, "visited": False, "deleted": False, "id": self.room_counter})
                        self.room_counter += 1

                room = next((r for r in self.plan if not r["built"]), None)
                if room:
                    rid = room["id"]
                    origin = _room_origin(rid)
                    build_fn = self.call_builder(room["data"], rid)
                    try:
                        build_fn(self.send_cmd, origin)
                        room["built"] = True
                        self.narrative_log.append(room["data"]["description"][:80])
                        if len(self.narrative_log) > 5: self.narrative_log.pop(0)
                        cor_from = _ROOM_X0 + rid * _ROOM_STEP + ROOM_WIDTH
                        cor_to = _ROOM_X0 + (rid + 1) * _ROOM_STEP
                        self._build_corridor_between(cor_from, cor_to)
                        if rid == 0: self.send_cmd(f"tp @a {_ROOM_X0 + 5} {_AY} {_AZ}")
                        self._save_state()
                    except Exception as e:
                        print(f"Build Error: {e}")
                        room["built"] = True

            # Mark visited & Cleanup Engine
            p_pos = telemetry["player_pos"]
            for r in self.plan:
                if r["built"] and not r["visited"]:
                    ox, _, _ = _room_origin(r["id"])
                    if _dist(p_pos, [ox + 40, _AY, _AZ]) < 50:
                        r["visited"] = True
                        print(f"[World] Entered room {r['id']}. Checking for cleanup...")
                        
                        target_cleanup = r["id"] - 2
                        if target_cleanup >= 0:
                            for old_r in self.plan:
                                if old_r["id"] <= target_cleanup and not old_r.get("deleted"):
                                    print(f"[Cleanup] Erasing room {old_r['id']}")
                                    x1, y1, z1, x2, y2, z2 = _room_bounds(old_r["id"])
                                    _chunked_fill(self.send_cmd, x1, y1, z1, x2, y2, z2, "minecraft:air")
                                    c_from = _ROOM_X0 + (old_r["id"]-1) * _ROOM_STEP + ROOM_WIDTH if old_r["id"] > 0 else _AX + 10
                                    c_to = _ROOM_X0 + old_r["id"] * _ROOM_STEP
                                    self._delete_corridor_between(c_from, c_to)
                                    old_r["deleted"] = True

            time.sleep(POLL_INTERVAL)

# -------------------------------------------------------------------- helpers

def _place_sign(send_cmd, x, y, z, text):
    lines = [text[i:i+15] for i in range(0, len(text), 15)][:4]
    while len(lines) < 4: lines.append("")
    json_lines = [json.dumps({"text": line}) for line in lines]
    msgs = ",".join([f"'{jl}'" for jl in json_lines])
    cmd = f"setblock {int(x)} {int(y)} {int(z)} minecraft:oak_sign{{front_text:{{messages:[{msgs}]}}}}"
    send_cmd(cmd)

def _place_lectern(send_cmd, x, y, z, title, author, pages):
    json_pages = [json.dumps({"text": p}) for p in pages]
    pgs = ",".join([f"'{jl}'" for jl in json_pages])
    cmd = f'setblock {int(x)} {int(y)} {int(z)} minecraft:lectern{{Book:{{id:"minecraft:written_book",Count:1b,tag:{{title:"{title}",author:"{author}",pages:[{pgs}]}}}}}}'
    send_cmd(cmd)

def _spawn_ghost(send_cmd, x, y, z):
    send_cmd(f"summon ephemera:npc {x} {y} {z} {{CustomName:'\" \"',Tags:['ghost']}}")

def _strip_fences(text):
    text = text.strip()
    if text.startswith("```"): text = "\n".join(text.split("\n")[1:-1])
    return text.strip()

def _chunked_fill(send_cmd, x1, y1, z1, x2, y2, z2, block):
    CHUNK = 32
    lx, hx = sorted([int(x1), int(x2)])
    ly, hy = sorted([int(y1), int(y2)])
    lz, hz = sorted([int(z1), int(z2)])
    for x in range(lx, hx + 1, CHUNK):
        for y in range(ly, hy + 1, CHUNK):
            for z in range(lz, hz + 1, CHUNK):
                send_cmd(f"fill {x} {y} {z} {min(x+CHUNK-1,hx)} {min(y+CHUNK-1,hy)} {min(z+CHUNK-1,hz)} {block}")

def _dist(a, b): return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5

def _fallback_build(send_cmd, origin):
    _chunked_fill(send_cmd, origin[0], origin[1], _AZ-2, origin[0]+ROOM_WIDTH, origin[1]+5, _AZ+2, "minecraft:cobblestone")

if __name__ == "__main__":
    Orchestrator().run()
