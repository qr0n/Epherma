# Ephemera — Where We Are Right Now

## What's Working

The full pipeline is live and tested end-to-end:

- **World Soul generation** — DecompositionSearch picks a real obscure subject, researches it across 5–7 branches, synthesizes an 800–1200 word narrative bible. Every world is genuinely unique.
- **Act treatment + scene briefs** — UltraDirector reads the soul and player telemetry, writes a narrative arc, LOCUS translates it into 5-room scene batches with deliberate size_class pacing.
- **Procedural geometry** — Builder LLM generates live Python code per room. Rooms clear their bounding box first, build additively, and leave matched corridor entrances.
- **Content layer** — Journals (written books on lecterns), named artifacts in item frames, custom NPCs, and ambient sounds — all contextualised by the World Soul.
- **Static world grid** — Rooms on absolute X-axis coordinates, no clipping, no relative offsets. First room starts adjacent to spawn.
- **Corridor system** — Pre-built stone corridors connect rooms. Entrance dimensions are passed to the Builder so openings match exactly.
- **Particle triggers** — end_rod rings mark unvisited room entrances. Visible from the corridor as a beacon.
- **Per-world state** — State files keyed on Minecraft world seed. Different worlds don't interfere.
- **Key rotation** — RotatingClient cycles across multiple Gemini API keys on every call.
- **Full logging** — Every LLM call logged with model, latency, char count. Rate limits, build errors, cleanup events all surfaced. Output mirrors to `ephemera.log`.

---

## Current Configuration

- **Model:** `gemini-3.1-flash-lite-preview` (globally — dialed down to avoid rate limits)
- **Rate limit handling:** Exponential backoff 30s → 60s → 120s. 2s inter-call delay.
- **Pruning:** Disabled. All builds persist in the world permanently.

---

## Known Limitations

- Flash-lite produces noticeably simpler room geometry and less atmospheric World Souls than a pro model would. The architecture is correct — the output quality is model-budget constrained.
- `_research_branches` runs sequentially (5–7 deep model calls one after another). First-world generation takes several minutes.
- Builder-generated code is `exec()`'d at runtime. Compilation errors fall back to a cobblestone corridor.

---

## What's Next

- **Phase 6 (ARG layer):** A global layer where discoveries in one player's world leave traces in others. Toynbee Tiles energy.
- Upgrade to pro model with real budget — the whole pipeline was designed for it.
- Parallelize `_research_branches` to cut world generation time.
- Improve Builder prompt reliability for cathedral/void-scale geometry.
