import json
import logging
import time

log = logging.getLogger(__name__)

REQUEST_DELAY = 2.0  # seconds between API calls — reduces cascading 429s


class DecompositionSearch:
    def __init__(
        self,
        client,
        model_fast="gemini-3.1-flash-lite-preview",
        model_deep="gemini-3.1-flash-lite-preview",
    ):
        self.client = client
        self.model_fast = model_fast
        self.model_deep = model_deep

    def generate_world_soul(self) -> tuple[str, str]:
        """Returns (seed_name, world_soul_text)."""
        t_total = time.time()
        try:
            seed = self._generate_seed()
            log.info(f"Seed chosen: {seed!r}")

            questions = self._decompose(seed)
            log.info(f"Decomposed into {len(questions)} research branches")

            research = self._research_branches(seed, questions)
            log.info("All branches complete")

            soul = self._synthesize(seed, research)
            log.info(
                f"World Soul forged in {time.time()-t_total:.1f}s  ({len(soul)} chars)"
            )

            return seed, soul
        except Exception as e:
            log.error(f"World Soul generation failed: {e}", exc_info=True)
            return (
                "The Void",
                "A place built from nothing. Cold. Mathematical. Indifferent.",
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

    def _generate_seed(self) -> str:
        system = """You are a researcher of obscure phenomena. Name one specific, real-world thing —
a piece of folklore, a Fortean event, a weird fiction element, an anomalous
location, or a historical mystery — that has genuine cultural depth and is not
widely known. Not a genre. Not a trope. A specific named thing.
Respond with ONLY the name. Nothing else."""

        user = "Give me one seed for a world that should feel unique, unsettling, and real."
        return self._call_llm(self.model_fast, system, user, temperature=1.0)

    def _decompose(self, seed: str) -> list[str]:
        system = """You are a research decomposer. Given a subject, generate 5-7 specific
research questions that together would give a researcher deep understanding
of the subject — not just facts, but atmosphere, cultural context, emotional
register, symbolic meaning, and narrative possibility.
Return ONLY a JSON array of question strings."""

        user = f'Subject: "{seed}"'
        res = self._call_llm(self.model_fast, system, user, json_mode=True)
        if isinstance(res, dict) and "questions" in res:
            return res["questions"]
        return res

    def _research_branches(self, seed: str, questions: list[str]) -> dict:
        research_notes = {}
        system = """You are a research specialist. Answer the following question with maximum
specificity. Cite specific names, dates, places, quotes where you know them.
Do not pad. Do not hedge. If you don't know something specific, say so and
move on. This research will be used to build a narrative world."""

        for i, q in enumerate(questions):
            log.info(f"Research branch {i+1}/{len(questions)}: {q[:80]}…")
            t0 = time.time()
            user = f'Research question: "{q}"\nSubject context: "{seed}"'
            answer = self._call_llm(self.model_deep, system, user)
            research_notes[q] = answer
            log.debug(
                f"Branch {i+1} answered in {time.time()-t0:.1f}s ({len(answer)} chars)"
            )

        return research_notes

    def _synthesize(self, seed: str, research: dict) -> str:
        system = """You are a production designer and narrative architect. You have been given
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
Write in present tense as if describing a place that exists right now."""

        formatted_notes = ""
        for q, a in research.items():
            formatted_notes += f"Q: {q}\nA: {a}\n\n"

        user = f'Seed: "{seed}"\n\nResearch notes:\n{formatted_notes}\n\nWrite the World Soul:'
        log.info("Synthesizing World Soul…")
        return self._call_llm(self.model_deep, system, user)
