import json
import logging
import math
import os
import pathlib
import time

import requests
from dotenv import load_dotenv
from openai import OpenAI

from decomposition import DecompositionSearch
from ultra_director import UltraDirector, SIZE_CLASSES

load_dotenv()

log = logging.getLogger(__name__)

MIDDLEWARE_URL = "http://localhost:8000"
POLL_INTERVAL = 2.0
REQUEST_DELAY = 2.0  # seconds between builder LLM calls

# ---------------------------------------------------------------------------
# API Key Cycler
# ---------------------------------------------------------------------------


class RotatingClient:
    def __init__(self, keys, base_url):
        self.clients = [
            OpenAI(api_key=k.strip(), base_url=base_url) for k in keys if k.strip()
        ]
        self.index = 0
        if not self.clients:
            log.warning("No API keys found — using mock key. Calls will fail.")
            self.clients = [OpenAI(api_key="mock_key", base_url=base_url)]
        else:
            log.info(f"RotatingClient initialised with {len(self.clients)} key(s)")

    @property
    def chat(self):
        client = self.clients[self.index]
        log.debug(f"Using API key slot {self.index}")
        self.index = (self.index + 1) % len(self.clients)
        return client.chat


api_keys_raw = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", ""))
api_keys = api_keys_raw.split(",") if "," in api_keys_raw else [api_keys_raw]

client = RotatingClient(
    keys=api_keys,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

BUILDER_MODEL = "gemini-3.1-flash-lite-preview"
CONTENT_MODEL = "gemini-3.1-flash-lite-preview"
_STATE_DIR = pathlib.Path(__file__).parent

# ---------------------------------------------------------------------------
# Static World Grid
# ---------------------------------------------------------------------------
WORLD_ANCHOR = [0, 64, 0]
SPAWN_HALF = 10
CORRIDOR_LEN = 20

_AX, _AY, _AZ = WORLD_ANCHOR
_FLOOR_Y = _AY - 1


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    def __init__(self):
        self.decomposer = DecompositionSearch(client)
        self.ultra_dir = UltraDirector(client)

        self.world_soul = None
        self.world_soul_seed = None
        self.world_seed = None

        self.plan = []
        self.narrative_log = []
        self.telemetry_history = []
        self.pending_sounds = []

        self.room_counter = 0
        self.next_x = _AX + SPAWN_HALF + CORRIDOR_LEN
        self._setup_done = False
        self._state_file = None

    # ------------------------------------------------------------------ state

    def _load_state(self):
        if self._state_file and self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text())
                self._setup_done = data.get("setup_done", False)
                self.room_counter = data.get("room_counter", 0)
                self.world_soul = data.get("world_soul")
                self.world_soul_seed = data.get("world_soul_seed")
                self.plan = data.get("plan", [])
                self.narrative_log = data.get("narrative_log", [])

                if self.plan:
                    last_r = self.plan[-1]
                    self.next_x = (
                        last_r["origin"][0] + last_r["dimensions"][0] + CORRIDOR_LEN
                    )

                log.info(
                    f"State loaded — soul: {self.world_soul_seed!r}  rooms: {self.room_counter}  setup_done: {self._setup_done}"
                )
            except Exception as e:
                log.error(f"State load error: {e}", exc_info=True)

    def _save_state(self):
        if self._state_file:
            self._state_file.write_text(
                json.dumps(
                    {
                        "setup_done": self._setup_done,
                        "room_counter": self.room_counter,
                        "world_soul": self.world_soul,
                        "world_soul_seed": self.world_soul_seed,
                        "world_seed": self.world_seed,
                        "plan": self.plan,
                        "narrative_log": self.narrative_log,
                    }
                )
            )
            log.debug(f"State saved → {self._state_file.name}")

    # ------------------------------------------------------------------ setup

    def _init_world(self, telemetry):
        seed = telemetry.get("world_seed")

        if self.world_seed is not None and self.world_seed != seed:
            log.warning(
                f"World seed changed {self.world_seed} → {seed}. Resetting all state."
            )
            self.world_soul = None
            self.plan = []
            self.room_counter = 0
            self.next_x = _AX + SPAWN_HALF + CORRIDOR_LEN
            self._setup_done = False
            self._state_file = None

        self.world_seed = seed
        self._state_file = _STATE_DIR / f".ephemera_{seed}.json"
        self._load_state()

        if self.world_soul is None:
            log.info("No World Soul found — generating now (takes several minutes)…")
            t0 = time.time()
            self.world_soul_seed, self.world_soul = (
                self.decomposer.generate_world_soul()
            )
            log.info(
                f"World Soul ready in {time.time()-t0:.1f}s — seed: {self.world_soul_seed!r}"
            )
            self._save_state()

    def _world_setup(self):
        log.info("Running world setup (gamerules, spawn room, first corridor)…")
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
        _chunked_fill(
            self.send_cmd,
            _AX - 10,
            fy,
            _AZ - 10,
            _AX + 10,
            fy + 7,
            _AZ + 10,
            "minecraft:smooth_stone",
        )
        _chunked_fill(
            self.send_cmd,
            _AX - 9,
            fy + 1,
            _AZ - 9,
            _AX + 9,
            fy + 6,
            _AZ + 9,
            "minecraft:air",
        )

        for dz in [-1, 0, 1]:
            for dy in range(1, 5):
                self.send_cmd(f"setblock {_AX+10} {fy+dy} {_AZ+dz} minecraft:air")

        self._build_corridor_between(_AX + 10, self.next_x, 8, 10)
        self._setup_done = True
        self._save_state()
        log.info("World setup complete.")

    def _build_corridor_between(self, from_x: int, to_x: int, h: int, d: int):
        fy = _FLOOR_Y
        hw = d // 2
        hh = h - 1
        log.debug(f"Corridor  x={from_x}→{to_x}  h={h}  d={d}")
        _chunked_fill(
            self.send_cmd,
            from_x,
            fy,
            _AZ - hw,
            to_x,
            fy + hh,
            _AZ + hw,
            "minecraft:smooth_stone",
        )
        _chunked_fill(
            self.send_cmd,
            from_x,
            fy + 1,
            _AZ - hw + 1,
            to_x,
            fy + hh - 1,
            _AZ + hw - 1,
            "minecraft:air",
        )
        mid_x = (from_x + to_x) // 2
        self.send_cmd(f"setblock {mid_x} {fy+hh} {_AZ} minecraft:glowstone")

    # ------------------------------------------------------------------ comms

    def get_telemetry(self):
        try:
            resp = requests.get(f"{MIDDLEWARE_URL}/state")
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            log.debug(f"Telemetry fetch failed: {e}")
        return None

    def send_cmd(self, cmd):
        try:
            requests.post(f"{MIDDLEWARE_URL}/command", json={"command": cmd})
            log.debug(f"CMD: {cmd}")
        except Exception as e:
            log.warning(f"send_cmd failed: {e}")

    def _call_llm_fast(self, system, prompt, json_mode=False):
        for attempt in range(3):
            time.sleep(REQUEST_DELAY)
            t0 = time.time()
            log.debug(
                f"→ {CONTENT_MODEL}  content  attempt {attempt+1}/3  ({len(system)+len(prompt)} chars in)"
            )
            try:
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ]
                response_format = {"type": "json_object"} if json_mode else None
                resp = client.chat.completions.create(
                    model=CONTENT_MODEL,
                    messages=messages,
                    temperature=0.7,
                    response_format=response_format,
                )
                content = _strip_fences(resp.choices[0].message.content)
                log.info(
                    f"← {CONTENT_MODEL}  content OK  {time.time()-t0:.1f}s  ({len(content)} chars out)"
                )
                if json_mode:
                    try:
                        return json.loads(content)
                    except json.JSONDecodeError as je:
                        log.warning(
                            f"Content JSON parse failed: {je} | raw: {content[:200]}"
                        )
                        return {}
                return content
            except Exception as e:
                elapsed = time.time() - t0
                if "429" in str(e) or "rate" in str(e).lower():
                    wait = 30 * (2**attempt)
                    log.warning(
                        f"Rate limited on {CONTENT_MODEL} after {elapsed:.1f}s (attempt {attempt+1}/3) — waiting {wait}s"
                    )
                    time.sleep(wait)
                else:
                    log.error(f"Content LLM error: {e}")
                    raise
        log.error("_call_llm_fast failed after 3 attempts")
        return {} if json_mode else ""

    # ---------------------------------------------------------------- telemetry

    def _compute_telemetry_aggregate(self):
        if not self.telemetry_history:
            return {
                "avg_speed": 0.0,
                "total_health_lost": 0.0,
                "time_in_rooms": 0.0,
                "actions_seen": [],
                "items_carried": [],
            }

        speeds = [t.get("speed", 0) for t in self.telemetry_history]
        health_deltas = [t.get("health_delta", 0) for t in self.telemetry_history]
        actions = list(set(t.get("action", "idle") for t in self.telemetry_history))
        items = list(
            set(item for t in self.telemetry_history for item in t.get("inventory", []))
        )

        agg = {
            "avg_speed": sum(speeds) / len(speeds),
            "total_health_lost": abs(sum(d for d in health_deltas if d < 0)),
            "time_in_rooms": len(self.telemetry_history) * POLL_INTERVAL,
            "actions_seen": actions,
            "items_carried": items,
        }
        log.debug(
            f"Telemetry aggregate: speed={agg['avg_speed']:.2f}  health_lost={agg['total_health_lost']:.1f}  time={agg['time_in_rooms']:.0f}s"
        )
        self.telemetry_history = []
        return agg

    # ---------------------------------------------------------------- content layer

    def apply_content(self, room_id: int, brief: dict, origin: list, dims: list):
        hint = brief.get("content_hint", "empty")
        log.info(f"Content hint for room {room_id}: {hint!r}")
        if hint == "empty":
            return

        x, y, z = origin
        w, h, d = dims
        cx, cy, cz = x + w // 2, y + 1, z + d // 2

        if hint == "journal":
            self._place_journal(brief, [cx, cy, cz])
        elif hint == "artifact":
            self._place_artifact(brief, [cx, cy, cz])
        elif hint == "npc":
            self._place_npc([x + 5, cy, z + 5])
        elif hint == "sound_only":
            self._schedule_sound(origin, brief)
        else:
            log.warning(f"Unknown content_hint: {hint!r}")

    def _place_journal(self, brief, pos):
        prompt = f"Write 2-4 cryptic paragraphs for a journal. Soul: {self.world_soul[:500]}. Room: {brief['description']}. Return JSON array of strings (pages)."
        pages = self._call_llm_fast("You are a cryptic writer.", prompt, json_mode=True)
        if isinstance(pages, dict):
            pages = pages.get("pages", ["The ink is dry."])
        log.info(f"Placing journal at {pos} ({len(pages)} pages)")
        _place_lectern(
            self.send_cmd, pos[0], pos[1], pos[2], "Journal", "Unknown", pages
        )

    def _place_artifact(self, brief, pos):
        prompt = f"Choose a Minecraft item and cryptic name. Soul: {self.world_soul[:500]}. Room: {brief['description']}. Return JSON: {{'item': '...', 'name': '...'}}"
        res = self._call_llm_fast("You choose artifacts.", prompt, json_mode=True)
        item = res.get("item", "minecraft:clock")
        name = res.get("name", "Remnant")
        log.info(f"Placing artifact at {pos}: {item} ({name!r})")
        self.send_cmd(
            f"setblock {pos[0]} {pos[1]} {pos[2]} minecraft:polished_andesite"
        )
        nbt = f'{{Item:{{id:"{item}",Count:1b}},CustomName:\'{{"text":"{name}"}}\'}}'
        self.send_cmd(f"summon item_frame {pos[0]} {pos[1]+1} {pos[2]} {nbt}")

    def _place_npc(self, pos):
        log.info(f"Spawning NPC at {pos}")
        self.send_cmd(f"summon ephemera:npc {pos[0]} {pos[1]} {pos[2]}")

    def _schedule_sound(self, origin, brief):
        prompt = f"Choose eerie sound and pitch (0.5-2.0). Room: {brief['description']}. Return JSON: {{'sound': '...', 'pitch': 1.0}}"
        res = self._call_llm_fast("You choose sounds.", prompt, json_mode=True)
        sound = res.get("sound", "ambient.cave")
        pitch = res.get("pitch", 1.0)
        log.info(f"Scheduled sound: {sound!r} pitch={pitch} at {origin}")
        self.pending_sounds.append({"origin": origin, "sound": sound, "pitch": pitch})

    # ---------------------------------------------------------------- builder

    def call_builder(
        self,
        description: str,
        room_id: int,
        origin: list,
        dims: list,
        entrance_w: int,
        entrance_h: int,
    ):
        x1, y1, z1 = origin
        w, h, d = dims
        x2, y2, z2 = x1 + w - 1, y1 + h - 1, z1 + d - 1
        log.info(
            f"Builder: room {room_id}  {w}×{h}×{d}  origin={origin}  entrance={entrance_w}×{entrance_h}"
        )

        system_prompt = f"""\
You are a Minecraft procedural programmer. Write a Python function `def build(send_cmd, origin):`.
- FIRST: chunked_fill(send_cmd, {x1}, {y1}, {z1}, {x2}, {y2}, {z2}, "minecraft:air")
- NO SOLID-FILL-THEN-CARVE. Build additively (floor, ceiling, walls, details).
- ENTRANCE/EXIT: Leave a {entrance_w}-wide, {entrance_h}-tall air gap centered on Z at both the west wall (x={x1}) and east wall (x={x2}). These must match the connecting corridors exactly.
- TOOLKIT: send_cmd, chunked_fill, math, range, etc.
Output ONLY raw Python code."""

        prompt = (
            f"Box: ({x1},{y1},{z1}) to ({x2},{y2},{z2}). Description: {description}"
        )

        for attempt in range(3):
            time.sleep(REQUEST_DELAY)
            t0 = time.time()
            log.debug(f"→ {BUILDER_MODEL}  builder  attempt {attempt+1}/3")
            try:
                resp = client.chat.completions.create(
                    model=BUILDER_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                )
                raw = _strip_fences(resp.choices[0].message.content)
                elapsed = time.time() - t0
                log.info(
                    f"← {BUILDER_MODEL}  builder OK  {elapsed:.1f}s  ({len(raw)} chars)"
                )
                log.debug(f"Builder code preview:\n{raw[:400]}")
                namespace = {"math": math, "chunked_fill": _chunked_fill}
                try:
                    exec(raw, namespace)
                    if "build" not in namespace:
                        log.warning("Builder returned code with no 'build' function")
                        continue
                    return namespace["build"]
                except Exception as compile_err:
                    log.warning(
                        f"Builder compile error (attempt {attempt+1}): {compile_err}"
                    )
                    continue
            except Exception as e:
                elapsed = time.time() - t0
                if "429" in str(e) or "rate" in str(e).lower():
                    wait = 30 * (2**attempt)
                    log.warning(
                        f"Rate limited on {BUILDER_MODEL} after {elapsed:.1f}s (attempt {attempt+1}/3) — waiting {wait}s"
                    )
                    time.sleep(wait)
                else:
                    log.error(f"Builder LLM error: {e}")
                    break

        log.warning(f"Builder failed for room {room_id} — using fallback")
        return _fallback_build

    # ---------------------------------------------------------- trigger rings

    def _draw_trigger_rings(self):
        TRIGGER_R = 40
        fy = _FLOOR_Y + 1
        unvisited = [r for r in self.plan if r.get("built") and not r.get("visited")]
        if unvisited:
            log.debug(f"Drawing trigger rings for {len(unvisited)} unvisited room(s)")
        for room in unvisited:
            ex = float(room["origin"][0])
            for deg in range(0, 360, 20):
                rad = math.radians(deg)
                px = ex + TRIGGER_R * math.cos(rad)
                pz = _AZ + TRIGGER_R * math.sin(rad)
                self.send_cmd(
                    f"particle minecraft:end_rod {px:.1f} {fy:.1f} {pz:.1f} 0 0.1 0 0 1 force"
                )
            for dy in range(0, 12, 3):
                self.send_cmd(
                    f"particle minecraft:end_rod {ex:.1f} {fy+dy:.1f} {float(_AZ):.1f} 0 0 0 0 1 force"
                )

    # ---------------------------------------------------------------- main loop

    def run(self):
        log.info("Ephemera Ultra Orchestrator starting")
        particle_tick = 0
        loop_count = 0

        while True:
            telemetry = self.get_telemetry()
            if not telemetry or "player_pos" not in telemetry:
                log.debug("Waiting for player telemetry…")
                time.sleep(POLL_INTERVAL)
                continue

            if self._state_file is None:
                self._init_world(telemetry)
            if not self._setup_done:
                self._world_setup()

            self.telemetry_history.append(telemetry)
            pos = telemetry["player_pos"]
            loop_count += 1

            if loop_count % 10 == 0:
                built = sum(1 for r in self.plan if r.get("built"))
                visited = sum(1 for r in self.plan if r.get("visited"))
                unbuilt = len(self.plan) - built
                log.debug(
                    f"Loop #{loop_count}  pos={[round(p,1) for p in pos]}  "
                    f"plan={len(self.plan)}  built={built}  visited={visited}  unbuilt={unbuilt}"
                )

            # Particle rings every 3 ticks (~6s)
            particle_tick += 1
            if particle_tick >= 3:
                particle_tick = 0
                self._draw_trigger_rings()

            # Sound triggers
            for s in list(self.pending_sounds):
                if _dist(pos, s["origin"]) < 30:
                    log.info(f"Playing sound {s['sound']!r} (player in range)")
                    self.send_cmd(
                        f"playsound minecraft:{s['sound']} ambient @a "
                        f"{s['origin'][0]} {s['origin'][1]} {s['origin'][2]} 1.0 {s['pitch']}"
                    )
                    self.pending_sounds.remove(s)

            # Replenish plan
            unbuilt = [r for r in self.plan if not r.get("built")]
            if len(unbuilt) < 2:
                log.info(
                    f"Plan buffer low ({len(unbuilt)} unbuilt) — requesting next scene from Director"
                )
                agg = self._compute_telemetry_aggregate()
                briefs = self.ultra_dir.get_next_scene_briefs(
                    agg,
                    self.world_soul,
                    self.world_soul_seed,
                    self.narrative_log,
                    self.room_counter % 20,
                )
                if isinstance(briefs, list) and briefs:
                    for b in briefs:
                        sc = b.get("size_class", "chamber")
                        dims_dict = SIZE_CLASSES.get(sc, SIZE_CLASSES["chamber"])
                        dims = [
                            dims_dict["width"],
                            dims_dict["height"],
                            dims_dict["depth"],
                        ]
                        origin = [self.next_x, _FLOOR_Y, _AZ - dims[2] // 2]
                        self.plan.append(
                            {
                                "brief": b,
                                "origin": origin,
                                "dimensions": dims,
                                "built": False,
                                "visited": False,
                                "deleted": False,
                                "id": self.room_counter,
                            }
                        )
                        log.debug(
                            f"Queued room {self.room_counter}: {sc} {dims} at x={self.next_x}"
                        )
                        self.next_x += dims[0] + CORRIDOR_LEN
                        self.room_counter += 1
                    log.info(
                        f"Added {len(briefs)} rooms to plan (total queued: {self.room_counter})"
                    )
                else:
                    log.warning(f"Director returned invalid briefs: {briefs}")
                self._save_state()

            # Build buffer
            unvisited_built = [r for r in self.plan if r["built"] and not r["visited"]]
            if len(unvisited_built) < 2:
                room = next((r for r in self.plan if not r.get("built")), None)
                if room:
                    rid = room["id"]
                    origin = room["origin"]
                    dims = room["dimensions"]
                    brief = room["brief"]
                    ch = min(dims[1], 10)
                    cd = min(dims[2], 10)
                    entrance_h = ch - 1
                    entrance_w = cd
                    t_build = time.time()
                    build_fn = self.call_builder(
                        brief["description"], rid, origin, dims, entrance_w, entrance_h
                    )
                    try:
                        build_fn(self.send_cmd, origin)
                        self.apply_content(rid, brief, origin, dims)
                        room["built"] = True
                        self.narrative_log.append(brief["description"][:80])
                        if len(self.narrative_log) > 5:
                            self.narrative_log.pop(0)

                        prev_room = next(
                            (r for r in self.plan if r["id"] == rid - 1), None
                        )
                        prev_x = (
                            _AX + 10
                            if prev_room is None
                            else prev_room["origin"][0] + prev_room["dimensions"][0]
                        )
                        self._build_corridor_between(prev_x, origin[0], ch, cd)
                        room["corridor_from_x"] = prev_x
                        room["corridor_h"] = ch
                        room["corridor_d"] = cd

                        if rid == 0:
                            self.send_cmd(f"tp @a {origin[0]+5} {_AY} {_AZ}")
                        log.info(
                            f"Room {rid} built in {time.time()-t_build:.1f}s at {origin}"
                        )
                        self._save_state()
                    except Exception as e:
                        log.error(
                            f"Build execution error room {rid}: {e}", exc_info=True
                        )
                        x1, y1, z1 = origin
                        w, h, d = dims
                        log.info(f"Clearing failed room {rid} bounding box with air")
                        _chunked_fill(
                            self.send_cmd,
                            x1,
                            y1,
                            z1,
                            x1 + w - 1,
                            y1 + h - 1,
                            z1 + d - 1,
                            "minecraft:air",
                        )
                        room["built"] = True

            # Mark visited (no pruning — all builds persist)
            for r in self.plan:
                if r["built"] and not r["visited"]:
                    dist = _dist(
                        pos, [r["origin"][0] + r["dimensions"][0] // 2, _AY, _AZ]
                    )
                    log.debug(f"Room {r['id']} distance: {dist:.1f}")
                    if dist < 40:
                        r["visited"] = True
                        log.info(f"Player entered room {r['id']}")

            time.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _place_lectern(send_cmd, x, y, z, title, author, pages):
    pgs = ",".join([json.dumps({"text": p}) for p in pages])
    cmd = (
        f"setblock {int(x)} {int(y)} {int(z)} "
        f'minecraft:lectern{{Book:{{id:"minecraft:written_book",Count:1b,'
        f'tag:{{title:"{title}",author:"{author}",pages:[{pgs}]}}}}}}'
    )
    send_cmd(cmd)


def _strip_fences(text):
    text = text.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:-1])
    return text.strip()


def _chunked_fill(send_cmd, x1, y1, z1, x2, y2, z2, block):
    CHUNK = 32
    lx, hx = sorted([int(x1), int(x2)])
    ly, hy = sorted([int(y1), int(y2)])
    lz, hz = sorted([int(z1), int(z2)])
    for x in range(lx, hx + 1, CHUNK):
        for y in range(ly, hy + 1, CHUNK):
            for z in range(lz, hz + 1, CHUNK):
                send_cmd(
                    f"fill {x} {y} {z} "
                    f"{min(x+CHUNK-1,hx)} {min(y+CHUNK-1,hy)} {min(z+CHUNK-1,hz)} {block}"
                )


def _dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _fallback_build(send_cmd, origin):
    _chunked_fill(
        send_cmd,
        origin[0],
        origin[1],
        _AZ - 2,
        origin[0] + 20,
        origin[1] + 5,
        _AZ + 2,
        "minecraft:cobblestone",
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("ephemera.log", encoding="utf-8"),
        ],
    )
    # Quiet down the noisy HTTP libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    Orchestrator().run()
