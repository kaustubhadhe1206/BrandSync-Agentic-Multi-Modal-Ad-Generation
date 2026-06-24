"""Smart image ranker. Uses Gemini multimodal reasoning to pick the strongest hero shot.

Sends all candidate images in a single multimodal turn and asks the model to
score and justify. Returns a structured ranking.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from google import genai
from google.genai import types as genai_types

from ..config import settings
from ..schemas import ImageCandidate, RankedImage


_RANK_PROMPT = """\
You are a senior art director evaluating hero-image candidates for a video ad.

The brief:
{brief_summary}

You are looking at {n} candidate images. For each, score it 0-10 on how well it would
serve as the OPENING FRAME of an 8-second video ad for this brand. Consider, in order
of importance:
- Brand identity: does this image visibly belong to THIS SPECIFIC business —
  logo, signage, packaging, or other distinctive brand marks — or is it a generic
  shot of the product category that could be any competitor's? A generic-but-pretty
  shot with zero brand identity should score LOW even if well-composed; a viewer
  must be able to tell whose ad this is.
- Aesthetic fit (does it match the visual style and audience from the brief?)
- Compositional strength as a hero shot (depth, focal point, room for motion)
- Whether it can credibly be extended into video by Veo (clear subject, no chaotic
  detail that breaks under motion synthesis)
- Whether voiceover and music can land over it

Return ONLY a JSON array, no prose, no markdown fences:
[
  {{"index": 0, "score": 8.5, "reasoning": "one sentence"}},
  ...
]
Order by index, not by score. Be honest — at least one image should score under 6
unless they are genuinely all strong.
"""


async def rank_images(
    candidates: list[ImageCandidate],
    brief_summary: str,
) -> list[RankedImage]:
    if not candidates:
        return []

    def _call() -> list[RankedImage]:
        client = genai.Client()
        parts: list = [_RANK_PROMPT.format(n=len(candidates), brief_summary=brief_summary)]
        for c in candidates:
            data = Path(c.path).read_bytes()
            parts.append(
                genai_types.Part.from_bytes(data=data, mime_type="image/png")
            )

        resp = client.models.generate_content(
            model=settings.MODEL_FAST,
            contents=parts,
        )
        text = resp.text or ""
        # Strip code fences if the model added them despite instructions
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
        try:
            scores = json.loads(text)
        except json.JSONDecodeError:
            # Fallback: assign equal scores so the pipeline doesn't dead-end
            return [
                RankedImage(candidate=c, score=5.0, reasoning="Ranker parse failed; default score.")
                for c in candidates
            ]

        by_index = {int(s["index"]): s for s in scores}
        out: list[RankedImage] = []
        for c in candidates:
            s = by_index.get(c.index, {"score": 5.0, "reasoning": "Missing from ranker output."})
            out.append(
                RankedImage(
                    candidate=c,
                    score=float(s.get("score", 5.0)),
                    reasoning=str(s.get("reasoning", "")),
                )
            )
        return out

    return await asyncio.to_thread(_call)


def pick_winner(ranked: list[RankedImage]) -> RankedImage:
    return max(ranked, key=lambda r: r.score)
