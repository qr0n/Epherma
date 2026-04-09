import json
import logging
import time

log = logging.getLogger(__name__)

REQUEST_DELAY = 2.0

SIZE_CLASSES = {
    "corridor": {"width": 60, "depth": 20, "height": 8},
    "chamber": {"width": 80, "depth": 60, "height": 40},
    "cathedral": {"width": 80, "depth": 80, "height": 80},
    "void": {"width": 120, "depth": 120, "height": 60},
}


class UltraDirector:
    def __init__(
        self,
        client,
        model_fast="gemini-3.1-flash-lite-preview",
        model_deep="gemini-3.1-flash-lite-preview",
    ):
        self.client = client
        self.model_fast = model_fast
        self.model_deep = model_deep
        self.current_treatment = None
        self.previous_act_summary = None

    def get_next_scene_briefs(
        self,
        telemetry_aggregate,
        world_soul,
        world_soul_seed,
        narrative_log,
        rooms_into_act,
    ) -> list[dict]:
        if self.current_treatment is None or rooms_into_act == 0:
            log.info(f"Generating new act treatment (rooms_into_act={rooms_into_act})")
            t0 = time.time()
            self.current_treatment = self._generate_treatment(
                world_soul, world_soul_seed, telemetry_aggregate
            )
            log.info(
                f"Act treatment forged in {time.time()-t0:.1f}s ({len(self.current_treatment)} chars)"
            )

        return self._generate_scene_briefs(
            self.current_treatment, narrative_log, rooms_into_act
        )

    def _call_llm(
        self, model, system_prompt, user_prompt, temperature=0.7, json_mode=False
    ):
        for attempt in range(3):
            time.sleep(REQUEST_DELAY)
            t0 = time.time()
            prompt_chars = len(system_prompt) + len(user_prompt)
            log.debug(f"→ {model}  attempt {attempt+1}/3  ({prompt_chars} chars in)")
            try:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
                response_format = {"type": "json_object"} if json_mode else None
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    response_format=response_format,
                )
                content = resp.choices[0].message.content.strip()
                elapsed = time.time() - t0
                log.info(f"← {model}  OK  {elapsed:.1f}s  ({len(content)} chars out)")

                if json_mode:
                    if content.startswith("```json"):
                        content = content[7:]
                    elif content.startswith("```"):
                        content = content[3:]
                    if content.endswith("```"):
                        content = content[:-3]
                    try:
                        return json.loads(content.strip())
                    except json.JSONDecodeError as je:
                        log.warning(f"JSON parse failed: {je} | raw: {content[:300]}")
                        return {}

                return content

            except Exception as e:
                elapsed = time.time() - t0
                if "429" in str(e) or "rate" in str(e).lower():
                    wait = 30 * (2**attempt)  # 30s, 60s, 120s
                    log.warning(
                        f"Rate limited on {model} after {elapsed:.1f}s (attempt {attempt+1}/3) — waiting {wait}s"
                    )
                    time.sleep(wait)
                else:
                    log.error(f"LLM error on {model}: {e}")
                    raise

        raise Exception(f"LLM call failed after 3 attempts ({model})")

    def _generate_treatment(
        self, world_soul, world_soul_seed, telemetry_aggregate
    ) -> str:
        system = """You are the Ultra Director of Ephemera — a world that is alive, aware of its player,
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
a sequence in a film that has not been made yet."""

        user = f"""World Soul Seed: {world_soul_seed}
World Soul:
{world_soul}

Telemetry Aggregate:
{json.dumps(telemetry_aggregate, indent=2)}

Previous Act Summary:
{self.previous_act_summary or "First Act."}

Write the treatment:"""

        treatment = self._call_llm(self.model_deep, system, user)
        self.previous_act_summary = treatment[:500] + "..."
        return treatment

    def _generate_scene_briefs(
        self, treatment, narrative_log, rooms_into_act
    ) -> list[dict]:
        system = """You are LOCUS — the scene planner for Ephemera.

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

Output ONLY a raw JSON array of exactly 5 objects. No markdown. No explanation."""

        narrative = (
            "\n".join([f"{i+1}. {d}" for i, d in enumerate(narrative_log)])
            or "No rooms built yet."
        )

        user = f"""Current Act Treatment:
{treatment}

Rooms already built in this act: {rooms_into_act}
Last 5 rooms history:
{narrative}

Plan the next 5 scene briefs as a JSON array:"""

        log.info(f"Generating scene briefs (room {rooms_into_act} of act)…")
        res = self._call_llm(self.model_fast, system, user, json_mode=True)

        if isinstance(res, dict):
            for key in ["briefs", "scenes", "rooms"]:
                if key in res and isinstance(res[key], list):
                    log.debug(f"Unwrapped briefs from key '{key}'")
                    res = res[key]
                    break

        if isinstance(res, list):
            log.info(
                f"Got {len(res)} scene briefs: {[b.get('size_class','?') for b in res]}"
            )
        else:
            log.warning(f"Unexpected briefs format: {type(res)} — {str(res)[:200]}")

        return res
